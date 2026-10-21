import csv

import pytest

from eplan_mcp.electrical_model import (
    aliases,
    attribute_values,
    drawing_metadata,
    network_observations,
    normalize_instance,
    pdf_candidates,
    physical_entities,
    plc_channels,
)
from eplan_mcp.electrical_reports import parse_report, parse_wdp


def entity(handle, kind="INSERT", block=None, attrs=None, **properties):
    return {
        "handle": handle,
        "type": kind,
        "layout": "@block" if block else "Model",
        "layer": "WIRE",
        "block_definition": block,
        "properties": properties,
        "attributes": [{"tag": k, "text": v, "insert": [0, 0, 0]} for k, v in (attrs or {}).items()],
    }


def document(rows, blocks=None):
    return {
        "format": "cad",
        "source": {"root_id": "test", "relative_path": "sample.dxf", "sha256": "a" * 64},
        "entities": rows,
        "blocks": blocks or [],
        "references": [],
    }


def device(attrs):
    doc = document([entity("10", attrs=attrs, name="SENSOR")])
    row = list(physical_entities(doc, []))[0]
    return normalize_instance(row, drawing_metadata(doc), aliases())


def test_direct_fields_and_interpretations_are_distinct():
    row = device(
        {"TAG1": "PE101", "DESC1": "Photoeye", "MFG": "EXAMPLE", "CAT": "S-1", "INST": "A", "LOC": "B"}
    )
    assert row["tag"] == "PE101" and row["device_type"] == "sensor"
    assert row["sources"][0]["kind"] == "electrical_attribute_convention"
    assert row["sources"][0]["native_relationship"] is False
    assert row["field_sources"]["manufacturer"]["interpreted"] is False
    assert row["field_sources"]["device_type"]["interpreted"] is True
    assert row["sources"][0]["reference_path"] == ["10"]
    assert row["sources"][0]["drawing"]["sha256"] == "a" * 64


def test_ordinary_block_aliases_are_explicit():
    doc = document([entity("10", attrs={"ASSET": "CAM10", "LABEL": "Camera"})])
    row = list(physical_entities(doc, []))[0]
    result = normalize_instance(
        row, drawing_metadata(doc), aliases({"tag": ["ASSET"], "description": ["LABEL"]})
    )
    assert result["tag"] == "CAM10" and result["device_type"] == "camera"
    assert result["sources"][0]["kind"] == "block_attributes"


def test_nested_instances_and_definition_coordinates():
    child = entity("20", block="ASSEMBLY", attrs={"TAG1": "VALVE1"}, insert=[2, 0, 0], name="VALVE")
    child["attributes"][0]["insert"] = [2, 0, 0]
    doc = document(
        [
            entity("10", name="ASSEMBLY", insert=[10, 20, 0], rotation=90),
            entity("11", name="ASSEMBLY", insert=[30, 40, 0]),
            child,
        ],
        [{"name": "ASSEMBLY", "base_point": [0, 0, 0]}, {"name": "VALVE", "base_point": [0, 0, 0]}],
    )
    rows = [r for r in physical_entities(doc, []) if r["handle"] == "20"]
    assert len(rows) == 2
    assert rows[0]["world_position"] == pytest.approx([10, 22, 0])
    assert rows[0]["attributes"][0]["world_position"] == pytest.approx([10, 22, 0])
    assert rows[1]["world_position"] == pytest.approx([32, 40, 0])
    assert rows[0]["reference_path"] == ["10", "20"]
    assert (
        normalize_instance(rows[0], doc["source"], aliases())["id"]
        != normalize_instance(rows[1], doc["source"], aliases())["id"]
    )


def test_only_placed_definitions_and_constant_attributes_are_used():
    variable = entity("30", "ATTDEF", block="B", tag="CAT", flags=0)
    variable["text"] = "UNASSIGNED_DEFAULT"
    constant = entity("31", "ATTDEF", block="B", tag="MFG", flags=2)
    constant["text"] = "EXAMPLE"
    unplaced = entity("32", block="UNUSED", attrs={"TAG1": "NEVER_PLACED"})
    doc = document([entity("10", name="B", attrs={"TAG1": "P1"}), variable, constant, unplaced])
    rows = list(physical_entities(doc, []))
    assert len(rows) == 1
    attrs, _ = attribute_values(rows[0])
    assert attrs["MFG"] == "EXAMPLE" and "CAT" not in attrs


def test_plc_address_suffix_is_not_assumed_to_be_hardware_channel():
    row = device(
        {
            "TAG": "PLC1",
            "TAGA01": "I:2/0",
            "TERM01": "0",
            "DESCA01": "Guard",
            "LINE1": "RACK 2",
            "LINE2": "SLOT 4",
            "X1TERM01": "01",
        }
    )
    channel = plc_channels(row)[0]
    assert channel["address"] == "I:2/0" and channel["terminal"] == "0"
    assert channel["terminal_code"] == "01" and channel["channel"] is None
    assert channel["controller"] is None and channel["rack"] is None
    assert channel["inferred_fields"] == {"rack": "2", "slot": "4"}


def test_split_tags_and_conflicting_attributes():
    row = entity("A", attrs={"TAG1_PART1": "MOT", "TAG1_PARTX": "-", "TAG1_PART2": "123"})
    row["attributes"].append({"tag": "TAG1_PART2", "text": "999"})
    values, conflicts = attribute_values(row)
    assert values["TAG1"] == "MOT-123" and conflicts == ["TAG1_PART2"]


def test_network_addresses_are_observed_not_probed():
    row = device(
        {"TAG1": "SW1", "DESC1": "Ethernet switch", "IP": "192.0.2.1", "PORT1": "P1", "CONNECTED_TO1": "CAM1"}
    )
    observations = network_observations(row, [])
    assert observations[0]["address_valid"] and observations[0]["ports"][0]["peer"] == "CAM1"
    row["ip_address"] = "999.0.0.1"
    diagnostics = []
    assert network_observations(row, diagnostics)[0]["address_valid"] is False
    assert diagnostics[0]["code"] == "invalid_network_address"


def test_pdf_candidates_never_become_connected_devices():
    doc = {
        "source": {"root_id": "test", "relative_path": "sample.pdf", "sha256": "b" * 64},
        "text": [
            {"text": "CAM101", "page": 2, "bbox": [1, 2, 3, 4]},
            {"text": "192.0.2.1", "page": 2, "bbox": [4, 5, 6, 7]},
        ],
    }
    rows, network = pdf_candidates(doc)
    assert rows[0]["role"] == "pdf_candidate" and rows[0]["sources"][0]["object_handle"] is None
    assert network[0]["device_id"] is None and network[0]["association_status"] == "unassigned"


def test_wdp_utf16_membership_and_root_boundaries(tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    (root / "one.dwg").write_bytes(b"dummy")
    path = root / "project.wdp"
    path.write_text(
        "*[1]Example\n+[1]not executed\n=STATION1\n==PANEL1\n===Robot power\none.dwg\n../outside.dwg\n",
        encoding="utf-16",
    )
    result = parse_wdp(path, root)
    assert result["drawings"][0]["descriptions"] == ["Robot power"]
    assert result["drawings"][0]["section"] == "STATION1"
    assert result["drawings"][0]["exists"] is True
    assert result["drawings"][1]["allowed"] is False
    assert result["native_relationship"] == "project_membership_only"


def test_native_plc_report_preserves_fields_and_explicit_mapping(tmp_path):
    path = tmp_path / "plc.csv"
    with path.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.writer(stream)
        writer.writerow(["Module", "PLCADDR", "CMPTAG", "PLCHDL", "CMPHDL", "PLCDWGIX", "CBL"])
        writer.writerow(["PLC1", "I:1/0", "PE101", "AB", "AC", "7", "CB1"])
    row = parse_report(path, "plc_connections", {"Module": "PLCTAG"})[0]
    assert row["row"] == 2
    assert row["fields"]["PLCHDL"] == "AB" and row["fields"]["PLCDWGIX"] == "7"
    assert row["fields"]["CBL"] == "CB1"
    with pytest.raises(ValueError, match="missing columns"):
        parse_report(path, "plc_connections")


def test_report_rejects_duplicate_columns_and_nested_json(tmp_path):
    path = tmp_path / "bad.csv"
    path.write_text("TAG,TAG\nA,B\n")
    with pytest.raises(ValueError, match="unique"):
        parse_report(path, "components")
    path = tmp_path / "bad.json"
    path.write_text('[{"TAG":"A", "nested":{}}]')
    with pytest.raises(ValueError, match="nested"):
        parse_report(path, "components")


def test_documented_from_to_handle_and_sheet_aliases(tmp_path):
    path = tmp_path / "connections.csv"
    path.write_text(
        "CMP1,PIN1,CMPHDL1,SH1,CMP2,PIN2,CMPHDL2,SH2,WIRENO\nPLC1,0,AB,1,PE1,1,CD,2,100\n", encoding="utf-8"
    )
    fields = parse_report(path, "from_to")[0]["fields"]
    assert fields["FROM_TAG"] == "PLC1" and fields["TO_HDL"] == "CD"
    assert fields["FROM_SH"] == "1" and fields["WIRENO"] == "100"


def test_native_drawing_sheet_does_not_use_signal_destination_sheet():
    doc = document(
        [entity("10", attrs={"SHEET": "7"}, name="WD_M"), entity("20", attrs={"SHEET": "42"}, name="HA1S1")]
    )
    result = drawing_metadata(doc)
    assert result["sheet"] == "7" and result["sheet_basis"] == "WD_M_drawing_attribute"
    assert result["sheet_candidates"] == ["42", "7"]
