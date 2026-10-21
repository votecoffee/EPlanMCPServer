import json
import os
import zipfile
import zlib

import pytest

from eplan_mcp.local_data import LocalDataService, inflate_at, project_link, text_candidates, xml_document
from eplan_mcp.service import sha256


@pytest.fixture
def local_files(drawing_service):
    drawings, root = drawing_service
    (root / "parts.xml").write_text(
        '<partsmanagement><part P_ARTICLE_PARTNR="EXAMPLE.1"><variant id="1">'
        "<description>Example contactor</description></variant></part>"
        '<part P_ARTICLE_PARTNR="EXAMPLE.2"><variant id="2"/></part></partsmanagement>',
        encoding="utf-8",
    )
    (root / "demo.edb").mkdir()
    (root / "demo.edb/Page.eod").write_bytes(
        b"\x01\x02PAGE ONE\x00" + zlib.compress(b"COMPRESSED PAGE\x00") + b"\x00TAIL"
    )
    (root / "demo.elk").write_bytes("demo.edb\n17.0\n".encode("utf-16"))
    return LocalDataService(drawings), root


def test_nested_xml_reader_preserves_properties_and_ordinals(local_files):
    service, root = local_files
    before = sha256(root / "parts.xml")
    schema = service.read("test", "parts.xml", "xml")
    assert schema["root_tag"] == "partsmanagement"
    assert next(t for t in schema["tags"] if t["tag"] == "part")["count"] == 2
    result = service.read("test", "parts.xml", "xml", record_tag="part", query="contactor")
    assert result["total"] == 1
    row = result["items"][0]
    assert row["record_ordinal"] == 1
    assert row["value"]["attributes"]["P_ARTICLE_PARTNR"] == "EXAMPLE.1"
    assert row["value"]["children"][0]["children"][0]["text"] == "Example contactor"
    assert result["source"]["sha256"] == before == sha256(root / "parts.xml")


def test_project_link_and_root_boundary(local_files):
    service, root = local_files
    result = service.project("test", "demo.elk")
    assert result["version_text"] == "17.0"
    assert result["items"][0]["relative_path"] == "demo.edb/Page.eod"
    (root / "bad.elk").write_text("../outside.edb\n17.0", encoding="utf-8")
    with pytest.raises(ValueError, match="relative"):
        service.project("test", "bad.elk")
    assert project_link(b"\r\n3.0\r\n")["database_reference"] is None
    with pytest.raises(ValueError):
        project_link(b"\x00native binary")


def test_binary_offsets_streams_checksum_and_source_preservation(local_files):
    service, root = local_files
    before = sha256(root / "demo.edb/Page.eod")
    streams = service.read("test", "demo.edb/Page.eod", "streams", byte_offset=0, byte_length=4096)
    stream = streams["items"][0]
    assert stream["checksum_verified"] and stream["inflated_bytes"] == 16
    result = service.read("test", "demo.edb/Page.eod", "text", stream_offset=stream["stream_offset"])
    assert result["coordinate_system"] == "inflated bytes"
    row = result["items"][0]
    assert row["byte_offset"] == 0 and row["text"] == "COMPRESSED PAGE"
    raw = service.read("test", "demo.edb/Page.eod", "bytes", byte_offset=0, byte_length=2)
    assert raw["hex"] == "0102"
    assert sha256(root / "demo.edb/Page.eod") == before
    with pytest.raises(ValueError, match="Local reader failed"):
        service.read("test", "demo.edb/Page.eod", "text", stream_offset=0)


def test_inflate_rejects_truncation_corruption_and_bombs(monkeypatch):
    from eplan_mcp import local_data

    data = zlib.compress(b"example text")
    for malformed in (data[:-1], data[:-1] + bytes([data[-1] ^ 1])):
        with pytest.raises((ValueError, zlib.error)):
            inflate_at(malformed, 0)
    monkeypatch.setattr(local_data, "INFLATED_LIMIT", 100)
    with pytest.raises(ValueError, match="budget"):
        inflate_at(zlib.compress(b"x" * 1000), 0)


def test_utf16_candidates_keep_byte_offsets():
    for encoding in ("utf-16-le", "utf-16-be"):
        rows = text_candidates(b"\xff\xff" + "Example".encode(encoding))
        assert any(
            r["text"] == "Example" and r["byte_offset"] == 2 and r["encoding"] == encoding for r in rows
        )


def test_experimental_slot_geometry_and_unknown_slots(local_files):
    service, root = local_files
    signature = bytes.fromhex("001100130000007e00130000007e")

    def slot(identifier, matched=True):
        value = identifier.to_bytes(4, "big") + (signature if matched else b"\x00" * 14) + b"EXAMPLE\x00"
        return value.ljust(96, b"\x00")

    path = root / "Functions.eod"
    path.write_bytes(slot(10) + slot(11) + slot(12, False) + slot(13))
    result = service.read("test", "Functions.eod", "slots", limit=4)
    assert result["slot_size"] == 96 and result["total"] == 4
    assert result["items"][0]["header_u32be_at_0"] == 10
    assert not result["items"][2]["matches_header_pattern"]
    assert result["items"][3]["byte_offset"] == 288
    path.write_bytes(path.read_bytes() + b"extra")
    with pytest.raises(ValueError, match="geometry"):
        service.read("test", "Functions.eod", "slots")


def test_xml_rejects_entities_and_excess_depth():
    with pytest.raises(ValueError, match="DTD"):
        xml_document(b'<!DOCTYPE R [<!ENTITY x "x">]><R>&x;</R>')
    with pytest.raises(ValueError, match="budget"):
        xml_document(b"<R>" * 66 + b"</R>" * 66)


def test_archive_member_reading_and_unsafe_names(local_files):
    service, root = local_files
    path = root / "project.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("Drawings/sample.pdf", (root / "sample.pdf").read_bytes())
        archive.writestr("Reports/parts.xml", '<Report><Part nr="EXAMPLE.1"/></Report>')
        archive.writestr("../outside.xml", "<private/>")
        archive.writestr("duplicate.xml", "<R/>")
        with pytest.warns(UserWarning):
            archive.writestr("duplicate.xml", "<R/>")
    before = sha256(path)
    inventory = service.read("test", "project.zip", "archive")
    assert inventory["total"] == 5 and not inventory["extracted"]
    pdf = service.read("test", "project.zip", "archive", member="Drawings/sample.pdf", limit=1)
    assert pdf["format"] == "pdf" and pdf["pages"] == 2 and pdf["items"][0]["text"]
    result = service.read(
        "test",
        "project.zip",
        "archive",
        member="Reports/parts.xml",
        member_operation="xml",
        record_tag="Part",
    )
    assert result["items"][0]["value"]["attributes"]["nr"] == "EXAMPLE.1"
    assert result["archive_member"]["sha256"]
    for member in ("../outside.xml", "duplicate.xml"):
        with pytest.raises(ValueError, match="Local reader failed"):
            service.read("test", "project.zip", "archive", member=member, member_operation="xml")
    assert sha256(path) == before


@pytest.mark.skipif(os.name != "nt", reason="Windows ACE integration")
def test_access_reads_real_synthetic_database_without_source_changes(local_files):
    service, root = local_files
    import win32com.client

    path = root / "parts.mdb"
    catalog = win32com.client.Dispatch("ADOX.Catalog")
    try:
        catalog.Create(f'Provider=Microsoft.ACE.OLEDB.12.0;Data Source="{path}";')
    except Exception as error:
        pytest.skip("ACE database creation unavailable: " + str(error))
    connection = catalog.ActiveConnection
    connection.Execute("CREATE TABLE Parts (PartNumber VARCHAR(50), Quantity INTEGER)")
    connection.Execute("INSERT INTO Parts VALUES ('EXAMPLE.1', 2)")
    connection.Execute("INSERT INTO Parts VALUES ('EXAMPLE.2', 3)")
    connection.Close()
    connection = catalog = None
    before = sha256(path)
    inventory = service.read("test", "parts.mdb", "access")
    assert inventory["items"] == [{"table": "Parts"}]
    result = service.read("test", "parts.mdb", "access", table="Parts", limit=1)
    assert result["read_only"] is True and result["next_offset"] == 1
    assert result["items"][0]["fields"] == {"PartNumber": "EXAMPLE.1", "Quantity": 2}
    second = service.read("test", "parts.mdb", "access", table="Parts", offset=1, limit=1)
    assert second["items"][0]["fields"]["PartNumber"] == "EXAMPLE.2"
    assert second["next_offset"] is None
    cell = service.read(
        "test", "parts.mdb", "access", table="Parts", column="PartNumber", offset=1, start=8, length=1
    )
    assert cell["text"] == "2" and cell["total_length"] == 9
    assert cell["row_ordinal"] == 2
    assert sha256(path) == before
    with pytest.raises(ValueError, match="base-table"):
        service.read("test", "parts.mdb", "access", table="Parts];DELETE FROM Parts")


@pytest.mark.anyio
async def test_local_readers_through_real_mcp(local_files):
    import sys

    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    _, root = local_files
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "eplan_mcp", "--config", str(root.parent / "config.json"), "serve"],
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write, read_timeout_seconds=60.0) as client:
            await client.initialize()
            tools = (await client.list_tools()).tools
            for tool in tools:
                if tool.name in {
                    "eplan_read_xml",
                    "eplan_read_access",
                    "eplan_read_project_link",
                    "eplan_read_binary_bytes",
                    "eplan_read_binary_text",
                    "eplan_find_compressed_streams",
                }:
                    assert tool.annotations.read_only_hint
            for name, args in [
                (
                    "eplan_read_xml",
                    {"root_id": "test", "relative_path": "parts.xml", "record_tag": "part", "limit": 1},
                ),
                ("eplan_read_project_link", {"root_id": "test", "relative_path": "demo.elk"}),
                ("eplan_read_binary_text", {"root_id": "test", "relative_path": "demo.edb/Page.eod"}),
                ("eplan_find_compressed_streams", {"root_id": "test", "relative_path": "demo.edb/Page.eod"}),
            ]:
                result = await client.call_tool(name, args)
                assert not result.is_error, json.dumps([c.model_dump() for c in result.content])
                assert result.structured_content["source"]["sha256"]
