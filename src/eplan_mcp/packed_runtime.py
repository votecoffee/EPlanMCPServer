"""Opt-in packed-source preparation. Never selects a launcher or starts a service.

The caller owns the trusted bootstrap and holds this object for the process
lifetime. Existing schema1 installations are deliberately not migrated here.
"""

from __future__ import annotations

import hashlib
import importlib.abc
import importlib.machinery
import importlib.resources.abc
import importlib.util
import io
import json
import os
import re
import sys
import threading
import zipfile
from pathlib import Path, PurePosixPath

from .runtime_creation import create_private_directory
from .runtime_leases import WindowsLease

SITE = "runtime/Lib/site-packages"
REVIEWED_FAMILIES = ("annotated_types", "typing_inspection", "mcp", "mcp_types", "anyio", "universal_tools")
CONTROL = {"layout.json", "sources.index.json", "sources.pack"}
# Exact reviewed pure-source trees; a dependency update needs a new review.
FAMILY_POLICY = {
    "annotated_types": "874cb49a51955ae1252aa1781129175e41dcb590c2d7fe7ba9d4618180d086ca",
    "typing_inspection": "52997107592eb8b19f7a7ce3165ac9c4ef995e5ff870a98e557dc65a47f7f8d6",
    "mcp": "21a83bf7786929987345f642074068d47d70aef688f3d53342a00978b7ea5910",
    "mcp_types": "8126bbff80d4e68eb34e53f9d25d006584d6e59ab775b89252c6d06540e31e10",
    "anyio": "13d79f7102b549948fd93c5efc9d15fb7da218b99c7e9bed18aac44559a3896d",
    "universal_tools": "77b32373da179259d73f5eca18408abf14db8d8f2e0ab4b53fe7739e7b6a5d0e",
}


def canonical(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def name(value):
    if not isinstance(value, str) or not value or "\\" in value or ":" in value:
        raise ValueError("Invalid logical path")
    p = PurePosixPath(value)
    if p.is_absolute() or str(p) != value:
        raise ValueError("Noncanonical logical path")
    for part in p.parts:
        if (
            part in (".", "..")
            or part.rstrip(" .") != part
            or part.split(".")[0].upper()
            in {
                "CON",
                "PRN",
                "AUX",
                "NUL",
                *(f"COM{i}" for i in range(1, 10)),
                *(f"LPT{i}" for i in range(1, 10)),
            }
        ):
            raise ValueError("Unsafe logical component")
    return value


def paths(values):
    result = list(values)
    for value in result:
        name(value)
    if len(result) != len({n.casefold() for n in result}):
        raise ValueError("Duplicate/case-alias paths")
    return result


def decode(data):
    if len(data) > 8 * 1024**2:
        raise ValueError("Manifest exceeds budget")

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate JSON key")
            result[key] = value
        return result

    return json.loads(
        data, object_pairs_hook=pairs, parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value))
    )


def digest_map(files):
    if not isinstance(files, dict) or not 1 <= len(files) <= 15000:
        raise ValueError("Invalid logical inventory")
    paths(files)
    if any(not isinstance(v, str) or not re.fullmatch("[a-f0-9]{64}", v) for v in files.values()):
        raise ValueError("Invalid logical hash")


def family(path):
    return path.removeprefix(SITE + "/").split("/")[0] if path.startswith(SITE + "/") else None


def family_fingerprint(files, selected):
    return sha(
        canonical(
            {
                p.removeprefix(SITE + "/"): digest
                for p, digest in files.items()
                if family(p) == selected and p.endswith(".py")
            }
        )
    )


def module_row(path, root):
    prefix = root + "/" if root else ""
    if not path.startswith(prefix):
        return None
    relative = path[len(prefix) :]
    parts = relative.split("/")
    package = parts[-1] == "__init__.py"
    if relative.endswith(".py"):
        parts = parts[:-1] if package else [*parts[:-1], parts[-1][:-3]]
    else:
        suffix = next((s for s in importlib.machinery.EXTENSION_SUFFIXES if relative.endswith(s)), None)
        if suffix is None:
            return None
        parts[-1] = parts[-1][: -len(suffix)]
    if not parts or not all(p.isidentifier() for p in parts):
        return None
    return ".".join(parts), package


class LeaseTree:
    """Pin all ancestors before reading files; reject unexpected physical paths."""

    def __init__(self, root, *, _lease_factory=WindowsLease):
        self.root = Path(root).absolute()
        self.factory = _lease_factory
        self.files, self.directories, self.order = {}, {}, []
        self.closed = False
        try:
            for path in reversed((self.root, *self.root.parents)):
                lease = self.factory(path, directory=True, check_owner=path == self.root)
                self.directories[path] = lease
                self.order.append(lease)
        except BaseException:
            self.close()
            raise

    def directory(self, relative, security=None):
        path = self.root if relative == "." else self.root / name(relative)
        if path not in self.directories:
            self.directory(path.parent.relative_to(self.root).as_posix())
            lease = self.factory(path, directory=True, expected_security=security)
            self.directories[path] = lease
            self.order.append(lease)
        elif security is not None and self.directories[path].security != security:
            raise ValueError("Directory security mismatch")

    def file(self, relative, security=None):
        name(relative)
        self.directory((self.root / relative).parent.relative_to(self.root).as_posix())
        if relative not in self.files:
            lease = self.factory(self.root / relative, expected_security=security)
            self.files[relative] = lease
            self.order.append(lease)
        elif security is not None and self.files[relative].security != security:
            raise ValueError("File security mismatch")
        return self.files[relative]

    def check_parents(self, relative):
        if self.closed:
            raise ImportError("Closed runtime lease tree")
        path = (self.root / relative).parent
        for directory in (path, *path.parents):
            if directory in self.directories:
                self.directories[directory].check()

    def exact(self, files, directories=None):
        observed, observed_dirs = set(), {"."}
        for base, folders, names in os.walk(self.root, followlinks=False):
            for part in folders + names:
                path = Path(base, part)
                st = path.lstat()
                if path.is_symlink() or getattr(st, "st_file_attributes", 0) & 0x400:
                    raise ValueError("Reparse physical inventory")
                relative = path.relative_to(self.root).as_posix()
                if part in folders:
                    observed_dirs.add(relative)
                else:
                    observed.add(relative)
        paths(observed)
        if observed != set(files) or directories is not None and observed_dirs != set(directories):
            raise ValueError("Physical inventory mismatch")

    def close(self):
        for lease in reversed(self.order):
            lease.close()
        self.closed = True


def build_layout(
    source,
    destination,
    logical_hashes,
    *,
    reviewed_families=REVIEWED_FAMILIES,
    family_policy=None,
    _lease_factory=WindowsLease,
):
    """Create a NEW schema2layout, preserving every selected logical byte/hash.

    No global selection, installer migration, source project or native operation.
    """
    digest_map(logical_hashes)
    if CONTROL & logical_hashes.keys():
        raise ValueError("Reserved layout path")
    if not reviewed_families or any(not f.isidentifier() for f in reviewed_families):
        raise ValueError("Explicit reviewed families required")
    native = {family(p) for p in logical_hashes if Path(p).suffix.lower() in {".pyd", ".dll"}}
    if native & set(reviewed_families):
        raise ValueError("Native family cannot be packed")
    policy = FAMILY_POLICY if family_policy is None else family_policy
    for selected in reviewed_families:
        if family_fingerprint(logical_hashes, selected) != policy.get(selected):
            raise ValueError("Unreviewed family source bytes")
    source = Path(source).absolute()
    destination = Path(destination).absolute()
    if destination.is_relative_to(source) or source.is_relative_to(destination):
        raise ValueError("Source and destination overlap")
    created = None
    if _lease_factory is WindowsLease:
        created = create_private_directory(destination)
    else:
        destination.mkdir(parents=True, exist_ok=False)
    tree = None
    packed = {}
    try:
        tree = LeaseTree(source, _lease_factory=_lease_factory)
        # Source inventories may include their own external inventory receipt.
        tree.exact(
            set(logical_hashes)
            | (
                {"inventory.json"}
                if (source / "inventory.json").is_file() and "inventory.json" not in logical_hashes
                else set()
            )
        )
        with zipfile.ZipFile(destination / "sources.pack", "x", compression=zipfile.ZIP_STORED) as archive:
            for relative, expected in sorted(logical_hashes.items()):
                lease = tree.file(relative)
                try:
                    data = lease.read()
                finally:
                    # Source file is consumed once; selected bytes/hash preserved.
                    # Directory generations stay pinned throughout the build.
                    pass
                if sha(data) != expected:
                    raise ValueError("Source byte/hash drift")
                (destination / relative).parent.mkdir(parents=True, exist_ok=True)
                if family(relative) in reviewed_families and relative.endswith(".py"):
                    identity = module_row(relative, SITE)
                    if identity is None:
                        raise ValueError("Packed source lacks module identity")
                    info = zipfile.ZipInfo(relative, (1980, 1, 1, 0, 0, 0))
                    info.create_system = 3
                    info.external_attr = 0o100444 << 16
                    archive.writestr(info, data)
                    packed[relative] = {
                        "module": identity[0],
                        "package": identity[1],
                        "sha256": expected,
                        "bytes": len(data),
                    }
                else:
                    (destination / relative).write_bytes(data)
        if not packed:
            raise ValueError("No reviewed sources selected")
        index_bytes = canonical({"schema": 1, "packed": packed})
        (destination / "sources.index.json").write_bytes(index_bytes)
        (destination / "layout.json").write_bytes(b"")
        security, directories = {}, {}
        target = LeaseTree(destination, _lease_factory=_lease_factory)
        try:
            for path in [destination, *sorted(p for p in destination.rglob("*") if p.is_dir())]:
                relative = path.relative_to(destination).as_posix()
                target.directory(relative)
                directories[relative] = target.directories[path].security
            for path in sorted(p for p in destination.rglob("*") if p.is_file()):
                relative = path.relative_to(destination).as_posix()
                security[relative] = target.file(relative).security
        finally:
            target.close()
        manifest = {
            "schema": 2,
            "logical_files": logical_hashes,
            "index_sha256": sha(index_bytes),
            "pack_sha256": sha((destination / "sources.pack").read_bytes()),
            "families": sorted(reviewed_families),
            "security": security,
            "directories": directories,
        }
        raw = canonical(manifest)
        (destination / "layout.json").write_bytes(raw)
        return {
            "manifest_sha256": sha(raw),
            "packed_sources": len(packed),
            "expanded_files": len(logical_hashes) - len(packed),
            "logical_files": len(logical_hashes),
        }
    finally:
        if tree is not None:
            tree.close()
        if created is not None:
            created.close()


class _Resource(importlib.resources.abc.TraversableResources):
    def __init__(self, runtime, directory):
        self.runtime, self.directory = runtime, directory

    def files(self):
        return _Node(self.runtime, self.directory)


class _MapReader(io.RawIOBase):
    def __init__(self, mapping):
        self.mapping = mapping

    def read(self, size=-1):
        return self.mapping.read(size)

    def seek(self, offset, whence=0):
        self.mapping.seek(offset, whence)
        return self.mapping.tell()

    def tell(self):
        return self.mapping.tell()

    def seekable(self):
        return True


class _Node(importlib.resources.abc.Traversable):
    def __init__(self, runtime, path):
        self.runtime, self.path = runtime, path

    @property
    def name(self):
        return PurePosixPath(self.path).name

    def is_file(self):
        return self.path in self.runtime.logical

    def is_dir(self):
        return any(p.startswith(self.path + "/") for p in self.runtime.logical)

    def iterdir(self):
        prefix = self.path + "/"
        return iter(
            _Node(self.runtime, prefix + p)
            for p in sorted(
                {n[len(prefix) :].split("/")[0] for n in self.runtime.logical if n.startswith(prefix)}
            )
        )

    def joinpath(self, *descendants):
        return _Node(self.runtime, name("/".join((self.path, *map(str, descendants)))))

    def open(self, mode="r", *args, **kwargs):
        if mode not in ("r", "rb"):
            raise ValueError("Verified resources are read-only")
        data = self.runtime.read(self.path)
        return (
            io.BytesIO(data)
            if mode == "rb"
            else io.StringIO(data.decode(kwargs.get("encoding") or "utf-8", kwargs.get("errors") or "strict"))
        )


class _Source(importlib.abc.SourceLoader):
    def __init__(self, runtime, fullname, logical, package):
        self.runtime, self.fullname, self.logical, self.package = runtime, fullname, logical, package

    def get_filename(self, fullname):
        return str(self.runtime.root / self.logical)

    def get_data(self, path):
        relative = Path(path).absolute().relative_to(self.runtime.root).as_posix()
        return self.runtime.read(relative)

    def get_resource_reader(self, fullname):
        return _Resource(self.runtime, str(PurePosixPath(self.logical).parent)) if self.package else None

    def set_data(self, path, data, **kwargs):
        raise ImportError("No mutable bytecode cache in verified layout")


class _Native(importlib.abc.Loader):
    def __init__(self, runtime, fullname, logical):
        self.runtime, self.logical = runtime, logical
        self.delegate = importlib.machinery.ExtensionFileLoader(fullname, str(runtime.root / logical))

    def create_module(self, spec):
        self.runtime.check(self.logical)
        return self.delegate.create_module(spec)

    def exec_module(self, module):
        self.runtime.check(self.logical)
        return self.delegate.exec_module(module)


class VerifiedSourceFinder(importlib.abc.MetaPathFinder):
    def __init__(self, runtime):
        self.runtime = runtime

    def find_spec(self, fullname, path=None, target=None):
        self.runtime.check("sources.pack")
        if fullname in self.runtime.modules:
            logical, package = self.runtime.modules[fullname]
            loader = (
                _Source(self.runtime, fullname, logical, package)
                if logical.endswith(".py")
                else _Native(self.runtime, fullname, logical)
            )
            return importlib.util.spec_from_file_location(
                fullname,
                self.runtime.root / logical,
                loader=loader,
                submodule_search_locations=[str((self.runtime.root / logical).parent)] if package else None,
            )
        if fullname in self.runtime.namespaces:
            spec = importlib.machinery.ModuleSpec(fullname, loader=None, is_package=True)
            spec.submodule_search_locations = [
                str(self.runtime.root / p) for p in self.runtime.namespaces[fullname]
            ]
            return spec
        # An indexed provider must never fall back to a newly created loose file.
        if fullname.split(".")[0] in self.runtime.providers:
            raise ModuleNotFoundError("Unindexed verified provider module: " + fullname)
        return None


class EngineClosure:
    """Unchanged expanded CPython inventory, fully hashed and retained.

    CPython's pre-verifier bootstrap remains a separate trusted boundary.
    """

    def __init__(self, root, inventory_sha256, *, _lease_factory=WindowsLease):
        self.tree = LeaseTree(root, _lease_factory=_lease_factory)
        self.root = self.tree.root
        try:
            raw = self.tree.file("inventory.json").read()
            if sha(raw) != inventory_sha256:
                raise ValueError("Engine inventory hash changed")
            self.logical = decode(raw)
            digest_map(self.logical)
            for relative, expected in self.logical.items():
                if self.tree.file(relative).digest() != expected:
                    raise ValueError("Engine payload changed")
            self.tree.exact(set(self.logical) | {"inventory.json"})
        except BaseException:
            self.close()
            raise

    def check(self, relative):
        self.tree.check_parents(relative)
        self.tree.files[relative].check()

    def read(self, relative):
        self.check(relative)
        return self.tree.files[relative].read()

    def close(self):
        self.tree.close()


class _ClosedPathFinder(importlib.abc.MetaPathFinder):
    def __init__(self, runtime, engine):
        self.closures = (runtime, engine)

    def find_spec(self, fullname, path=None, target=None):
        spec = importlib.machinery.PathFinder.find_spec(fullname, path, target)
        if spec is None:
            return None
        if spec.origin in (None, "namespace"):
            for location in spec.submodule_search_locations or ():
                if not any(Path(location).absolute() in c.tree.directories for c in self.closures):
                    raise ImportError("Namespace outside retained provider closure")
            return spec
        origin = Path(spec.origin).absolute()
        for closure in self.closures:
            if origin.is_relative_to(closure.root):
                logical = origin.relative_to(closure.root).as_posix()
                if logical not in closure.logical:
                    raise ImportError("Unindexed expanded module")
                closure.check(logical)
                package = spec.submodule_search_locations is not None
                spec.loader = (
                    _Source(closure, fullname, logical, package)
                    if logical.endswith(".py")
                    else _Native(closure, fullname, logical)
                )
                return spec
        raise ImportError("Module outside retained engine/runtime closure")


class PackedRuntime:
    def __init__(self, root, expected_manifest_sha256, *, family_policy=None, _lease_factory=WindowsLease):
        self.tree = LeaseTree(root, _lease_factory=_lease_factory)
        self.root, self.archive, self.mapping = self.tree.root, None, None
        self.finder = None
        self.import_state = None
        self.dll_handles = []
        self.lock = threading.RLock()
        try:
            manifest_data = self.tree.file("layout.json").read()
            if sha(manifest_data) != expected_manifest_sha256:
                raise ValueError("Layout manifest hash changed")
            manifest = decode(manifest_data)
            if (
                set(manifest)
                != {
                    "schema",
                    "logical_files",
                    "index_sha256",
                    "pack_sha256",
                    "families",
                    "security",
                    "directories",
                }
                or manifest["schema"] != 2
            ):
                raise ValueError("Unsupported packed layout")
            if (
                not isinstance(manifest["families"], list)
                or not manifest["families"]
                or len(set(manifest["families"])) != len(manifest["families"])
                or any(not isinstance(f, str) or not f.isidentifier() for f in manifest["families"])
            ):
                raise ValueError("Invalid reviewed family set")
            for key in ("security", "directories"):
                if not isinstance(manifest[key], dict) or any(
                    not isinstance(v, str) or not v for v in manifest[key].values()
                ):
                    raise ValueError("Invalid selected security descriptor")
            self.logical = manifest["logical_files"]
            digest_map(self.logical)
            policy = FAMILY_POLICY if family_policy is None else family_policy
            for selected in manifest["families"]:
                if family_fingerprint(self.logical, selected) != policy.get(selected):
                    raise ValueError("Unreviewed selected family bytes")
            index_lease = self.tree.file("sources.index.json", manifest["security"]["sources.index.json"])
            index_data = index_lease.read()
            if sha(index_data) != manifest["index_sha256"]:
                raise ValueError("Index hash changed")
            index = decode(index_data)
            if (
                set(index) != {"schema", "packed"}
                or index["schema"] != 1
                or not isinstance(index["packed"], dict)
            ):
                raise ValueError("Invalid source index")
            self.packed = index["packed"]
            paths(self.packed)
            if not self.packed or not set(self.packed) <= self.logical.keys():
                raise ValueError("Invalid logical hash union")
            for relative, row in self.packed.items():
                if (
                    set(row) != {"module", "package", "sha256", "bytes"}
                    or module_row(relative, SITE) != (row["module"], row["package"])
                    or type(row["package"]) is not bool
                    or type(row["bytes"]) is not int
                    or not 0 <= row["bytes"] <= 64 * 1024**2
                    or row["sha256"] != self.logical[relative]
                    or family(relative) not in manifest["families"]
                ):
                    raise ValueError("Invalid packed source identity")
            if {family(p) for p in self.logical if Path(p).suffix.lower() in {".pyd", ".dll"}} & set(
                manifest["families"]
            ):
                raise ValueError("Native family in source container")
            expanded = self.logical.keys() - self.packed.keys()
            expected = expanded | CONTROL
            if set(manifest["security"]) != expected:
                raise ValueError("Physical security inventory mismatch")
            paths(n for n in manifest["directories"] if n != ".")
            for relative, security in sorted(
                manifest["directories"].items(), key=lambda row: len(PurePosixPath(row[0]).parts)
            ):
                self.tree.directory(relative, security)
            for relative in expected:
                self.tree.file(relative, manifest["security"][relative])
            self.tree.exact(expected, manifest["directories"])
            pack_lease = self.tree.files["sources.pack"]
            self.mapping = pack_lease.map_readonly()
            if sha(self.mapping) != manifest["pack_sha256"]:
                raise ValueError("Container hash changed")
            self.archive = zipfile.ZipFile(_MapReader(self.mapping))
            names = self.archive.namelist()
            paths(names)
            if set(names) != set(self.packed):
                raise ValueError("Container index/member mismatch")
            for entry in self.archive.infolist():
                if (
                    entry.compress_type != zipfile.ZIP_STORED
                    or entry.flag_bits & 1
                    or entry.is_dir()
                    or entry.create_system != 3
                    or entry.external_attr >> 16 != 0o100444
                ):
                    raise ValueError("Noncanonical source member")
                data = self.archive.read(entry)
                if (
                    entry.file_size != self.packed[entry.filename]["bytes"]
                    or sha(data) != self.logical[entry.filename]
                ):
                    raise ValueError("Original source hash changed")
            for relative in expanded:
                if self.tree.files[relative].digest() != self.logical[relative]:
                    raise ValueError("Original expanded hash changed")
            self.modules, self.namespaces = {}, {}
            search = (SITE, SITE + "/win32", SITE + "/win32/lib", SITE + "/pythonwin")
            for relative in sorted(self.logical):
                for root_path in search:
                    identity = module_row(relative, root_path)
                    if identity:
                        fullname, package = identity
                        if fullname in self.modules and self.modules[fullname] != (relative, package):
                            raise ValueError("Ambiguous module providers")
                        self.modules[fullname] = (relative, package)
                        parts = fullname.split(".")
                        for size in range(1, len(parts)):
                            parent = ".".join(parts[:size])
                            path = root_path + "/" + "/".join(parts[:size])
                            self.namespaces.setdefault(parent, set()).add(path)
            self.providers = {n.split(".")[0] for n in self.modules}
        except BaseException:
            self.close()
            raise

    def check(self, relative):
        self.tree.check_parents(relative)
        self.tree.files["layout.json"].check()
        self.tree.files["sources.index.json"].check()
        self.tree.files["sources.pack"].check()
        if relative in self.tree.files:
            self.tree.files[relative].check()

    def read(self, relative):
        name(relative)
        if relative not in self.logical:
            raise FileNotFoundError(relative)
        with self.lock:
            self.check(relative)
            return (
                self.archive.read(relative) if relative in self.packed else self.tree.files[relative].read()
            )

    def install_finder(self, engine):
        """Use retained runtime/engine providers only; do not execute any .pth.

        Windows DLL search excludes PATH/CWD; only selected native directories
        and trusted System32 are added. Existing schema1 launchers are unchanged.
        This is a terminal-process bootstrap operation, never a hot reload.
        """
        packed_modules = {row["module"] for row in self.packed.values()}
        if self.finder is not None or packed_modules & sys.modules.keys():
            raise ImportError("Packed providers already loaded")
        self.check("sources.pack")
        if not isinstance(engine, EngineClosure) or engine.tree.closed:
            raise ImportError("A fully verified retained engine closure is required")
        self.import_state = (list(sys.meta_path), list(sys.path), sys.dont_write_bytecode)
        directories = [
            self.root / p
            for p in (SITE, SITE + "/win32", SITE + "/win32/lib", SITE + "/pythonwin")
            if self.root / p in self.tree.directories
        ]
        directories += [
            p
            for p in (engine.root / "Lib", engine.root / "DLLs", engine.root)
            if p in engine.tree.directories
        ]
        if os.name == "nt":
            import ctypes

            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            if not kernel.SetDefaultDllDirectories(0xC00):
                raise ctypes.WinError(ctypes.get_last_error())
            native_directories = {
                c.root / str(PurePosixPath(p).parent)
                for c in (self, engine)
                for p in c.logical
                if Path(p).suffix.lower() in (".pyd", ".dll")
            }
            try:
                for directory in sorted(native_directories):
                    self.dll_handles.append(os.add_dll_directory(str(directory)))
            except BaseException:
                for cookie in self.dll_handles:
                    cookie.close()
                self.dll_handles.clear()
                raise
        self.finder = VerifiedSourceFinder(self)
        sys.dont_write_bytecode = True
        sys.path[:] = [str(p) for p in directories]
        sys.meta_path[:] = [
            importlib.machinery.BuiltinImporter,
            importlib.machinery.FrozenImporter,
            self.finder,
            _ClosedPathFinder(self, engine),
        ]
        return self.finder

    def close(self):
        if self.import_state is not None:
            sys.meta_path[:], sys.path[:], sys.dont_write_bytecode = self.import_state
            self.import_state = None
            self.finder = None
        for cookie in self.dll_handles:
            cookie.close()
        self.dll_handles.clear()
        if self.archive is not None:
            self.archive.close()
        if self.mapping is not None:
            self.mapping.close()
        self.tree.close()
