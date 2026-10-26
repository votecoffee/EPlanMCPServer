import importlib.resources
import importlib.util
import mmap
import zipfile
from pathlib import Path

import pytest

from eplan_mcp.packed_runtime import (
    EngineClosure,
    PackedRuntime,
    VerifiedSourceFinder,
    build_layout,
    canonical,
    decode,
    name,
    sha,
)

POLICY = {
    "fixture_packed": sha(
        canonical(
            {"fixture_packed/__init__.py": sha(b"VALUE=42\n"), "fixture_packed/sub.py": sha(b"VALUE=43\n")}
        )
    )
}


class FakeLease:
    """Pure algorithm fixture ONLY; deliberately no native sharing claim."""

    def __init__(self, path, *, directory=False, expected_security=None, check_owner=True):
        self.path = Path(path)
        self.directory = directory
        self.security = "fixture-owner-DACL"
        self.closed = False
        if self.path.is_symlink() or not self.path.exists():
            raise ValueError("Invalid fixture path")
        if expected_security is not None and expected_security != self.security:
            raise ValueError("Changed descriptor")

    def check(self):
        if self.closed:
            raise ValueError("Closed original fixture")

    def read(self):
        self.check()
        return self.path.read_bytes()

    def digest(self):
        return sha(self.read())

    def map_readonly(self):
        with self.path.open("rb") as stream:
            return mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ)

    def close(self):
        self.closed = True


@pytest.fixture
def layout(tmp_path):
    source, target = tmp_path / "source", tmp_path / "layout"
    payload = {
        "runtime/Lib/site-packages/fixture_packed/__init__.py": b"VALUE=42\n",
        "runtime/Lib/site-packages/fixture_packed/sub.py": b"VALUE=43\n",
        "runtime/Lib/site-packages/fixture_packed/data.txt": b"original resource\n",
        "runtime/Lib/site-packages/expanded/__init__.py": b"UNCHANGED=True\n",
    }
    for relative, data in payload.items():
        path = source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    hashes = {n: sha(v) for n, v in payload.items()}
    receipt = build_layout(
        source,
        target,
        hashes,
        reviewed_families=("fixture_packed",),
        family_policy=POLICY,
        _lease_factory=FakeLease,
    )
    return source, target, hashes, receipt


def verify(layout):
    _, root, _, receipt = layout
    return PackedRuntime(root, receipt["manifest_sha256"], family_policy=POLICY, _lease_factory=FakeLease)


def rewrite(root, transform):
    manifest = decode((root / "layout.json").read_bytes())
    transform(manifest)
    data = canonical(manifest)
    (root / "layout.json").write_bytes(data)
    return sha(data)


def test_deterministic_complete_logical_union_and_consuming_source_resource_loader(layout, tmp_path):
    source, root, hashes, receipt = layout
    second = tmp_path / "second"
    again = build_layout(
        source,
        second,
        hashes,
        reviewed_families=("fixture_packed",),
        family_policy=POLICY,
        _lease_factory=FakeLease,
    )
    assert receipt == again
    for control in ("sources.pack", "sources.index.json", "layout.json"):
        assert (root / control).read_bytes() == (second / control).read_bytes()
    runtime = verify(layout)
    try:
        assert all(sha(runtime.read(n)) == v for n, v in hashes.items())
        assert not (root / "runtime/Lib/site-packages/fixture_packed/__init__.py").exists()
        finder = VerifiedSourceFinder(runtime)
        spec = finder.find_spec("fixture_packed")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        assert module.VALUE == 42
        assert spec.loader.get_source("fixture_packed") == "VALUE=42\n"
        assert (
            spec.loader.get_resource_reader("fixture_packed").files().joinpath("data.txt").read_text()
            == "original resource\n"
        )
        assert (
            spec.loader.get_resource_reader("fixture_packed").files().joinpath("__init__.py").read_bytes()
            == b"VALUE=42\n"
        )
    finally:
        runtime.close()


@pytest.mark.parametrize(
    "value", ["../x", "/x", "a/../x", "a\\b", "x:y", "a//b", "a/./b", "CON.py", "name. ", ""]
)
def test_unsafe_paths(value):
    with pytest.raises(ValueError):
        name(value)


def test_duplicate_json_keys_refused():
    with pytest.raises(ValueError):
        decode(b'{"schema":1,"schema":2}')


@pytest.mark.parametrize(
    "target", ["sources.pack", "sources.index.json", "runtime/Lib/site-packages/expanded/__init__.py"]
)
def test_tamper_before_any_import_refused(layout, target):
    _, root, _, _ = layout
    path = root / target
    data = path.read_bytes()
    path.write_bytes(data[:-1] + bytes([data[-1] ^ 1]))
    with pytest.raises((ValueError, zipfile.BadZipFile)):
        verify(layout)


@pytest.mark.parametrize("fault", ["extra", "case", "security", "logical-union", "index-identity"])
def test_physical_case_descriptor_and_logical_index_refusal(layout, fault):
    _, root, _, receipt = layout
    if fault == "extra":
        (root / "unexpected.py").write_bytes(b"raise AssertionError\n")
        expected = receipt["manifest_sha256"]
    elif fault == "case":
        expected = rewrite(
            root,
            lambda m: m["logical_files"].update({"RUNTIME/Lib/site-packages/expanded/__init__.py": "0" * 64}),
        )
    elif fault == "security":
        expected = rewrite(root, lambda m: m["security"].update({"sources.pack": "foreign-DACL"}))
    elif fault == "logical-union":
        expected = rewrite(
            root, lambda m: m["logical_files"].pop("runtime/Lib/site-packages/fixture_packed/sub.py")
        )
    else:
        index = decode((root / "sources.index.json").read_bytes())
        index["packed"]["runtime/Lib/site-packages/fixture_packed/sub.py"]["module"] = "foreign"
        raw = canonical(index)
        (root / "sources.index.json").write_bytes(raw)
        expected = rewrite(root, lambda m: m.update(index_sha256=sha(raw)))
    with pytest.raises((ValueError, KeyError)):
        PackedRuntime(root, expected, family_policy=POLICY, _lease_factory=FakeLease)


def test_no_new_loose_module_fallback_and_no_closed_lease_use(layout):
    runtime = verify(layout)
    finder = VerifiedSourceFinder(runtime)
    try:
        (runtime.root / "runtime/Lib/site-packages/fixture_packed/foreign.py").write_bytes(
            b"raise AssertionError\n"
        )
        with pytest.raises(ModuleNotFoundError):
            finder.find_spec("fixture_packed.foreign")
    finally:
        runtime.close()
    with pytest.raises((ValueError, ImportError)):
        finder.find_spec("fixture_packed")


def test_native_family_cannot_be_selected(layout, tmp_path):
    source, _, hashes, _ = layout
    path = source / "runtime/Lib/site-packages/fixture_packed/native.pyd"
    path.write_bytes(b"not executable")
    with pytest.raises(ValueError, match="Native family"):
        build_layout(
            source,
            tmp_path / "refused",
            {**hashes, path.relative_to(source).as_posix(): sha(path.read_bytes())},
            reviewed_families=("fixture_packed",),
            family_policy=POLICY,
            _lease_factory=FakeLease,
        )


def test_duplicate_or_link_zip_member_refused_even_with_reselected_container_hash(layout):
    _, root, _, _ = layout
    with zipfile.ZipFile(root / "sources.pack", "a") as archive:
        archive.writestr("../outside.py", b"bad")
    expected = rewrite(root, lambda m: m.update(pack_sha256=sha((root / "sources.pack").read_bytes())))
    with pytest.raises(ValueError):
        PackedRuntime(root, expected, family_policy=POLICY, _lease_factory=FakeLease)


def test_duplicate_exact_member_refused(layout):
    _, root, _, _ = layout
    with zipfile.ZipFile(root / "sources.pack", "a") as archive:
        member = archive.infolist()[0]
        data = archive.read(member)
        with pytest.warns(UserWarning):
            archive.writestr(member, data)
    expected = rewrite(root, lambda m: m.update(pack_sha256=sha((root / "sources.pack").read_bytes())))
    with pytest.raises(ValueError, match="Duplicate"):
        PackedRuntime(root, expected, family_policy=POLICY, _lease_factory=FakeLease)


def test_engine_full_inventory_and_tamper(layout, tmp_path):
    engine = tmp_path / "engine"
    engine.mkdir()
    (engine / "library.py").write_bytes(b"ORIGINAL=1\n")
    raw = canonical({"library.py": sha((engine / "library.py").read_bytes())})
    (engine / "inventory.json").write_bytes(raw)
    closure = EngineClosure(engine, sha(raw), _lease_factory=FakeLease)
    closure.close()
    (engine / "library.py").write_bytes(b"TAMPER=1\n")
    with pytest.raises(ValueError):
        EngineClosure(engine, sha(raw), _lease_factory=FakeLease)
