"""Conservative, source-bound electrical observations from CAD instances and PDF text."""

from __future__ import annotations

import collections
import hashlib
import ipaddress
import json
import math
import re

from ezdxf.math import Matrix44

SCHEMA_VERSION = 1
ALIASES = {
    "tag": [
        "P_TAG1",
        "P_TAGSTRIP",
        "TAGSTRIP",
        "TAG1",
        "TAG1F",
        "TAG2",
        "TAG2F",
        "TAG",
        "DEVICE_TAG",
        "COMPONENT_TAG",
    ],
    "description": ["DESC1", "DESC2", "DESC3", "DESCRIPTION", "DESC"],
    "manufacturer": ["MFG", "MANUFACTURER", "VENDOR"],
    "catalog": ["CAT", "CATALOG", "CATALOG_NUMBER", "CATALOG_NO", "PART_NUMBER"],
    "installation": ["INST", "INSTALLATION"],
    "location": ["LOC", "LOCATION"],
    "panel": ["PANEL", "PANEL_ID", "ENCLOSURE"],
    "station": ["STATION", "STATION_ID"],
    "controller": ["CONTROLLER", "CPU", "PLC_CONTROLLER"],
    "rack": ["RACK", "PLC_RACK"],
    "slot": ["SLOT", "PLC_SLOT"],
    "channel": ["CHANNEL", "PLC_CHANNEL"],
    "network": ["NETWORK", "NETWORK_NAME", "SUBNET_NAME"],
    "ip_address": ["IP", "IPADDR", "IP_ADDRESS", "IPADDRESS"],
    "mac_address": ["MAC", "MAC_ADDRESS"],
    "hostname": ["HOSTNAME", "HOST_NAME"],
    "interface": ["INTERFACE", "PROTOCOL", "COMM_INTERFACE"],
    "device_type": ["DEVICE_TYPE", "TYPE"],
}
TYPE_RULES = [
    ("remote_io", r"\bremote\s*(?:i/o|io)|\bremote\s+input|\bremote\s+output"),
    ("camera", r"\bcamera\b|\bvision\b|\bx-ray\b"),
    ("robot", r"\brobot\b"),
    ("drive", r"\bdrive\b|\bservo\b|\bvfd\b|\bacopos\b"),
    ("valve", r"\bvalve\b|\bsolenoid\b"),
    ("sensor", r"\bsensor\b|\bphoto\s*eye\b|\bphotoelectric\b|\bproximity\b|\bpressure switch\b"),
    ("network_switch", r"\b(?:ethernet|network)\s+switch\b"),
    ("connector", r"\bconnector\b|\bplug\b"),
    ("controller", r"\bcontroller\b|\bcpu\b|\bplc\b"),
]


def stable_id(prefix: str, *values) -> str:
    data = json.dumps(values, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return prefix + "_" + hashlib.sha256(data.encode()).hexdigest()[:24]


def issue(code: str, message: str, sources: list | None = None, **details) -> dict:
    return {"code": code, "message": message, "severity": "review", "sources": sources or [], **details}


def aliases(custom: dict | None = None) -> dict:
    result = {key: list(value) for key, value in ALIASES.items()}
    for key, names in (custom or {}).items():
        if key not in result or not isinstance(names, list) or not 1 <= len(names) <= 12:
            raise ValueError("attribute_map must map supported field names to 1..12 attribute names")
        if any(not isinstance(n, str) or not re.fullmatch(r"[A-Za-z0-9_?\-]{1,64}", n) for n in names):
            raise ValueError("Invalid attribute name")
        result[key] = [n.upper() for n in names]
    return result


def attribute_values(row: dict) -> tuple[dict, list]:
    values, conflicts = {}, []
    for attr in row.get("attributes", []):
        name, value = attr["tag"].upper(), str(attr.get("text", "")).strip()
        if name in values and values[name] != value:
            conflicts.append(name)
        else:
            values[name] = value
    # Split Electrical tags have a documented, explicit joining convention.
    for prefix in ("TAG1", "TAG1F", "TAG2", "TAG2F"):
        if not values.get(prefix) and values.get(prefix + "_PART1"):
            values[prefix] = (
                values[prefix + "_PART1"]
                + values.get(prefix + "_PARTX", "")
                + values.get(prefix + "_PART2", "")
            )
    return values, conflicts


def drawing_metadata(doc: dict) -> dict:
    observed = collections.defaultdict(set)
    defaults = []
    native_sheets = set()
    for row in doc["entities"]:
        if row["type"] == "INSERT" and row["layout"] != "@block":
            attrs, _ = attribute_values(row)
            if row.get("properties", {}).get("name", "").upper() == "WD_M":
                native_sheets.update(attrs[n] for n in ("SHEET", "SHEET_") if attrs.get(n))
                defaults.append(
                    {
                        "object_handle": row["handle"],
                        "installation": attrs.get("IEC_INST"),
                        "location": attrs.get("IEC_LOC"),
                        "inheritance_applied": False,
                    }
                )
            for field, names in (
                ("sheet", ("SHEET", "SHT_NO", "SHEET_NO", "SHT")),
                ("revision", ("REVISION", "REV", "DWG_REV")),
            ):
                observed[field].update(attrs[n] for n in names if attrs.get(n))
    sheet_values = native_sheets or observed["sheet"]
    return {
        **doc["source"],
        "sheet": next(iter(sheet_values)) if len(sheet_values) == 1 else None,
        "sheet_basis": "WD_M_drawing_attribute" if native_sheets else "unique_placed_attribute",
        "native_sheet_candidates": sorted(native_sheets),
        "revision": next(iter(observed["revision"])) if len(observed["revision"]) == 1 else None,
        "sheet_candidates": sorted(observed["sheet"]),
        "revision_candidates": sorted(observed["revision"]),
        "electrical_drawing_defaults": defaults,
    }


def provenance(drawing: dict, row: dict, path: list[str], *, kind="block_attributes") -> dict:
    return {
        "kind": kind,
        "native_relationship": False,
        "drawing": drawing,
        "sheet": drawing.get("sheet"),
        "object_handle": row.get("handle"),
        "layout": row.get("layout"),
        "reference_path": path,
        "reference": "/".join([drawing["root_id"], drawing["relative_path"], str(row.get("layout")), *path]),
    }


def physical_entities(doc: dict, diagnostics: list, max_instances=100_000):
    """Expand placed INSERTs; attached attributes are already in their parent layout's coordinates."""
    definitions = collections.defaultdict(list)
    bases = {b["name"]: b.get("base_point") or [0, 0, 0] for b in doc["blocks"]}
    for row in doc["entities"]:
        if row.get("block_definition"):
            definitions[row["block_definition"]].append(row)
    count = 0

    def visit(row, matrix, chain, names, layout_name, inherited_layer):
        nonlocal count
        count += 1
        if count > max_instances:
            raise ValueError("Physical occurrence limit exceeded; narrow the drawing scope")
        path = chain + [row["handle"]]
        props = row["properties"]
        effective_layer = row["layer"] if row["layer"] != "0" else inherited_layer
        observed = {
            **row,
            "layout": layout_name,
            "effective_layer": effective_layer,
            "reference_path": path,
            "world_matrix": list(matrix),
        }
        if row["type"] == "INSERT":
            attrs = [dict(a) for a in row.get("attributes", [])]
            name = props.get("name", "")
            existing = {a["tag"].upper() for a in attrs}
            for definition in definitions[name]:
                if (
                    definition["type"] == "ATTDEF"
                    and definition["properties"].get("flags", 0) & 2
                    and definition["properties"].get("tag", "").upper() not in existing
                ):
                    # Constants are observed on the definition; never invent missing variable attribute values.
                    attrs.append(
                        {
                            "tag": definition["properties"]["tag"],
                            "text": definition.get("text", ""),
                            "insert": None,
                            "constant_definition": True,
                        }
                    )
            observed["attributes"] = [
                {**a, "world_position": list(matrix.transform(a["insert"])) if a.get("insert") else None}
                for a in attrs
            ]
            observed["world_position"] = list(matrix.transform(props.get("insert", (0, 0, 0))))
            yield observed
            if name in names or len(names) >= 16:
                diagnostics.append(
                    issue(
                        "block_expansion_incomplete",
                        "Cyclic/deep block reference skipped",
                        [provenance(doc["source"], row, path)],
                        block=name,
                    )
                )
                return
            if props.get("row_count", 1) > 1 or props.get("column_count", 1) > 1:
                diagnostics.append(
                    issue(
                        "insert_array_not_expanded",
                        "Only the base INSERT occurrence is reported",
                        [provenance(doc["source"], row, path)],
                    )
                )
            if props.get("extrusion", [0, 0, 1]) != [0, 0, 1]:
                diagnostics.append(
                    issue(
                        "nonplanar_insert",
                        "Nested geometry for non-default extrusion skipped",
                        [provenance(doc["source"], row, path)],
                    )
                )
                return
            base = bases.get(name, (0, 0, 0))
            local = (
                Matrix44.translate(*[-v for v in base])
                @ Matrix44.scale(props.get("xscale", 1), props.get("yscale", 1), props.get("zscale", 1))
                @ Matrix44.z_rotate(math.radians(props.get("rotation", 0)))
                @ Matrix44.translate(*props.get("insert", (0, 0, 0)))
            )
            for child in definitions[name]:
                if child["type"] != "ATTDEF":
                    yield from visit(
                        child, local @ matrix, path, names + [name], layout_name, effective_layer
                    )
        else:
            yield observed

    for entity in doc["entities"]:
        if entity["layout"] != "@block":
            yield from visit(entity, Matrix44(), [], [], entity["layout"], entity["layer"])


def pick(attrs: dict, mapping: dict, field: str) -> tuple[str | None, list]:
    names = [name for name in mapping[field] if attrs.get(name)]
    value = (
        " ".join(dict.fromkeys(attrs[name] for name in names))
        if field == "description"
        else (attrs[names[0]] if names else None)
    )
    return value, names


def normalize_instance(row: dict, drawing: dict, mapping: dict) -> dict | None:
    attrs, conflicts = attribute_values(row)
    fields, field_sources = {}, {}
    for key in mapping:
        fields[key], names = pick(attrs, mapping, key)
        if names:
            if key == "tag":
                observed_names = {a["tag"].upper() for a in row.get("attributes", [])}
                names = [
                    part
                    for n in names
                    for part in (
                        [n]
                        if n in observed_names
                        else [
                            n + suffix
                            for suffix in ("_PART1", "_PARTX", "_PART2")
                            if n + suffix in observed_names
                        ]
                    )
                ]
            field_sources[key] = {"kind": "attribute", "names": names, "interpreted": False}
    is_plc = any(re.fullmatch(r"TAGA\d+", key) for key in attrs)
    if not (fields["tag"] or fields["manufacturer"] or fields["catalog"] or is_plc):
        return None
    role = (
        "plc_module"
        if is_plc
        else "panel"
        if attrs.get("P_TAG1")
        else "panel_terminal"
        if attrs.get("P_TAGSTRIP")
        else "terminal"
        if attrs.get("TAGSTRIP")
        else "child"
        if attrs.get("TAG2") or attrs.get("TAG2F")
        else "schematic"
        if attrs.get("TAG1") or attrs.get("TAG1F")
        else "ordinary_block"
    )
    source = provenance(drawing, row, row["reference_path"])
    source["kind"] = "electrical_attribute_convention" if role != "ordinary_block" else "block_attributes"
    device_type = fields.pop("device_type")
    if not device_type:
        description = fields.get("description") or ""
        device_type = next(
            (name for name, pattern in TYPE_RULES if re.search(pattern, description, re.I)), None
        )
        device_type = device_type or (
            "io_module"
            if is_plc
            else "terminal"
            if role in {"terminal", "panel_terminal"}
            else "unclassified"
        )
        field_sources["device_type"] = {
            "kind": "classification_rule",
            "interpreted": True,
            "input": "description/role",
        }
    terminals = [
        {"code": match.group(1), "number": value, "description": attrs.get("TERMDESC" + match.group(1))}
        for name, value in attrs.items()
        if (match := re.fullmatch(r"TERM(\d+)", name)) and value
    ]
    connections = [
        {
            "direction": match.group(1),
            "code": match.group(2),
            "position": a.get("world_position"),
            "attribute": a["tag"],
            "terminal": attrs.get("TERM" + match.group(2)),
            "wire_number": attrs.get("WIRENO" + match.group(2)),
        }
        for a in row.get("attributes", [])
        if (match := re.fullmatch(r"X([1248])TERM(\d+)", a["tag"].upper()))
    ]
    return {
        "id": stable_id("dev", drawing, row["layout"], row["reference_path"]),
        **fields,
        "device_type": device_type,
        "role": role,
        "block_name": row["properties"].get("name"),
        "family": attrs.get("FAMILY"),
        "attributes": attrs,
        "attribute_conflicts": conflicts,
        "terminals": terminals,
        "additional_catalogs": [
            {
                "suffix": key[3:],
                "manufacturer": attrs.get("MFG" + key[3:]),
                "catalog": value,
                "assembly_code": attrs.get("ASSYCODE" + key[3:]),
            }
            for key, value in attrs.items()
            if re.fullmatch(r"CAT\d+", key) and value
        ],
        "connection_points": connections,
        "sources": [source],
        "field_sources": field_sources,
        "position": row.get("world_position"),
        "cross_references": [attrs[n] for n in ("XREF", "XREFNO", "XREFNC") if attrs.get(n)],
    }


def plc_channels(device: dict) -> list:
    attrs, result = device["attributes"], []
    for name, address in attrs.items():
        match = re.fullmatch(r"TAGA(\d+)", name)
        if not match or not address:
            continue
        code = match.group(1)
        descriptions = [
            attrs[n + code] for n in ("DESCA", "DESCB", "DESCC", "DESCD", "DESCE") if attrs.get(n + code)
        ]
        controller, rack, slot = device.get("controller"), device.get("rack"), device.get("slot")
        inferred = {}
        # RACK/SLOT text is interpretation, kept distinct from explicit named fields.
        for field in ("rack", "slot"):
            if not device.get(field):
                candidates = [
                    re.search(r"\b" + field + r"\s*[:#]?\s*([A-Za-z0-9_.-]+)", attrs.get(n, ""), re.I)
                    for n in ("LINE1", "LINE2", "DESC1", "DESC2", "DESC3")
                ]
                values = {m.group(1) for m in candidates if m}
                if len(values) == 1:
                    inferred[field] = next(iter(values))
        result.append(
            {
                "id": stable_id("io", device["id"], code),
                "module_device_id": device["id"],
                "module_tag": device["tag"],
                "controller": controller,
                "rack": rack,
                "slot": slot,
                "inferred_fields": inferred,
                "terminal_code": code,
                "channel": attrs.get("CHANNEL" + code),
                "address": address,
                "terminal": attrs.get("TERM" + code),
                "description": " ".join(descriptions) or None,
                "connected_devices": [],
                "wire_numbers": [attrs["WIRENO" + code]] if attrs.get("WIRENO" + code) else [],
                "connection_status": "not_traced",
                "sources": device["sources"],
                "relationship_basis": "electrical_attribute_convention",
                "address_attribute": name,
            }
        )
    return result


def network_observations(device: dict, diagnostics: list) -> list:
    result = []
    attrs = device.get("attributes", {})
    has_network = any(
        device.get(k) for k in ("ip_address", "mac_address", "hostname", "interface", "network")
    )
    ports = [
        {
            "port": attrs[name],
            "peer": attrs.get("CONNECTED_TO" + match.group(1)) or attrs.get("PEER" + match.group(1)),
        }
        for name in attrs
        if (match := re.fullmatch(r"PORT(\d*)", name)) and attrs[name]
    ]
    if has_network or ports or device["device_type"] == "network_switch":
        address = device.get("ip_address")
        valid = None
        if address:
            try:
                ipaddress.ip_address(address)
                valid = True
            except ValueError:
                valid = False
                diagnostics.append(
                    issue(
                        "invalid_network_address",
                        "Documented address is not an IP literal",
                        device["sources"],
                        value=address,
                        device_id=device["id"],
                    )
                )
        result.append(
            {
                "id": stable_id("net", device["id"]),
                "device_id": device["id"],
                "tag": device["tag"],
                **{
                    k: device.get(k)
                    for k in ("ip_address", "mac_address", "hostname", "network", "interface")
                },
                "address_valid": valid,
                "ports": ports,
                "sources": device["sources"],
                "relationship_basis": "attribute_assertion",
            }
        )
    return result


def pdf_candidates(doc: dict) -> tuple[list, list]:
    """Unassociated candidates only; text proximity never becomes a physical connection."""
    devices, networks = [], []
    for index, row in enumerate(doc["text"]):
        text = row["text"].strip()
        source = {
            "kind": "pdf_text_interpretation",
            "native_relationship": False,
            "drawing": doc["source"],
            "sheet": None,
            "page": row["page"],
            "bbox": row["bbox"],
            "object_handle": None,
            "reference_path": [f"page:{row['page']}", f"text:{index}"],
            "reference": f"{doc['source']['root_id']}/{doc['source']['relative_path']}#page={row['page']}&text={index}",
        }
        if re.fullmatch(r"[A-Za-z]{1,12}[-_]?\d{2,8}(?:[._-][A-Za-z0-9]+){0,3}", text):
            devices.append(
                {
                    "id": stable_id("annotation", source),
                    "tag": text,
                    "description": None,
                    "role": "pdf_candidate",
                    "device_type": "unclassified",
                    "attributes": {},
                    "sources": [source],
                    "field_sources": {"tag": {"kind": "text_pattern", "interpreted": True}},
                }
            )
        for match in re.finditer(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])", text):
            try:
                ipaddress.ip_address(match.group())
            except ValueError:
                continue
            networks.append(
                {
                    "id": stable_id("net_annotation", source, match.group()),
                    "device_id": None,
                    "tag": None,
                    "ip_address": match.group(),
                    "address_valid": True,
                    "ports": [],
                    "network": None,
                    "interface": None,
                    "sources": [source],
                    "relationship_basis": "pdf_text_interpretation",
                    "association_status": "unassigned",
                }
            )
    return devices, networks
