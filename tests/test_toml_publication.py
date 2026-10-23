import hashlib
import tomllib

import pytest

from scripts.toml_publication import encode_toml, publish_copy

TEXT = '''title = "å·¥ç¨‹ â€“ cafÃ©"
notes = """first line
second line"""
[unrelated]
enabled = true
literal = 'C:\\Design Files\\Î±'
[plugins.fixture]
enabled = false
'''


@pytest.mark.parametrize("input_newline", ["\n", "\r\n"])
@pytest.mark.parametrize("output_newline", ["\n", "\r\n"])
def test_utf8_toml_bytes_and_unrelated_settings(tmp_path, input_newline, output_newline):
    path = tmp_path / "space directory" / "settings.toml"
    path.parent.mkdir()
    before = TEXT.replace("\n", input_newline).encode("utf-8")
    path.write_bytes(before)
    updated = TEXT.replace("enabled = false", "enabled = true").replace("\n", input_newline)
    result = publish_copy(
        path,
        updated,
        expected_sha256=hashlib.sha256(before).hexdigest(),
        allowed_changes=(("plugins", "fixture", "enabled"),),
        newline=output_newline,
    )
    actual = path.read_bytes()
    assert actual == updated.replace("\r\n", "\n").replace("\n", output_newline).encode("utf-8")
    assert b"\r\r\n" not in actual and b"\r" not in actual.replace(b"\r\n", b"")
    parsed = tomllib.loads(actual.decode("utf-8"))
    assert parsed["unrelated"] == tomllib.loads(TEXT)["unrelated"]
    assert parsed["notes"] == "first line\nsecond line"
    assert parsed["plugins"]["fixture"]["enabled"] is True
    assert not result["live_config_written"]


def test_bad_input_and_unrelated_mutation_preserve_original(tmp_path):
    path = tmp_path / "settings.toml"
    original = TEXT.encode("utf-8")
    path.write_bytes(original)
    for malformed in (TEXT.replace("\n", "\r\r\n"), TEXT.replace("\n", "\r")):
        with pytest.raises(ValueError, match="CR"):
            encode_toml(malformed)
    with pytest.raises(ValueError, match="Unrelated"):
        publish_copy(
            path,
            TEXT.replace("enabled = true", "enabled = false"),
            expected_sha256=hashlib.sha256(original).hexdigest(),
        )
    assert path.read_bytes() == original


def test_live_target_refused_before_io(tmp_path, monkeypatch):
    protected = tmp_path / "repaired-live.toml"
    monkeypatch.setattr("scripts.toml_publication.LIVE_CONFIG", protected)
    with pytest.raises(ValueError, match="protected"):
        publish_copy(protected, TEXT, expected_sha256=None)
    assert not protected.exists()


def test_stale_copy_refused(tmp_path):
    path = tmp_path / "copy.toml"
    path.write_bytes(TEXT.encode())
    with pytest.raises(ValueError, match="changed since"):
        publish_copy(path, TEXT, expected_sha256="0" * 64)


def test_platform_default_is_explicit_bytes():
    import os

    expected = "\r\n" if os.name == "nt" else "\n"
    assert encode_toml(TEXT) == TEXT.replace("\n", expected).encode("utf-8")


def test_new_named_table_preserves_existing_document(tmp_path):
    path = tmp_path / "new-route-copy.toml"
    before = TEXT.encode("utf-8")
    path.write_bytes(before)
    updated = TEXT + "\n[mcp_servers.eplan]\nenabled = true\n"
    publish_copy(
        path,
        updated,
        expected_sha256=hashlib.sha256(before).hexdigest(),
        allowed_changes=(("mcp_servers", "eplan"),),
        newline="\r\n",
    )
    parsed = tomllib.loads(path.read_bytes().decode("utf-8"))
    parsed.pop("mcp_servers")
    assert parsed == tomllib.loads(TEXT)
