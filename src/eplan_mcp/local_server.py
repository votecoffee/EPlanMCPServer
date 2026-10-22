"""MCP adapters for independently readable local file content."""

from .local_data import LocalDataService


def register_local(tool, drawings):
    service = LocalDataService(drawings)

    @tool()
    def eplan_read_archive(
        root_id: str,
        relative_path: str,
        member: str | None = None,
        member_operation: str = "text",
        reader_options: dict | None = None,
        offset: int = 0,
        limit: int = 25,
    ) -> dict:
        """List ordinary ZIP entries or read one exact member using xml/access/link/text/bytes/streams.
        Native ZW1/ZW9 are not treated as ZIP. Members are size-bounded, CRC-verified and isolated.
        reader_options supports record_tag, query, table, byte_offset, byte_length, stream_offset,
        minimum_length, text_encoding only. Pagination applies to the selected member reader or ZIP inventory.
        """
        options = reader_options or {}
        if not isinstance(options, dict) or set(options) - {
            "record_tag",
            "query",
            "table",
            "byte_offset",
            "byte_length",
            "stream_offset",
            "minimum_length",
            "text_encoding",
        }:
            raise ValueError("Unsupported archive reader_options")
        return service.read(
            root_id,
            relative_path,
            "archive",
            member=member,
            member_operation=member_operation,
            offset=offset,
            limit=limit,
            **options,
        )

    @tool()
    def eplan_read_eod_slots(
        root_id: str, relative_path: str, slot_size: int | None = None, offset: int = 0, limit: int = 25
    ) -> dict:
        """Experimental EOD byte-slot reader with raw header integers and offset-bound text candidates.
        Infer slot size only from repeated header intervals that exactly divide the file, or provide
        an explicit size. Does not establish active objects, property meanings or connectivity.
        """
        return service.read(root_id, relative_path, "slots", slot_size=slot_size, offset=offset, limit=limit)

    @tool()
    def eplan_read_xml(
        root_id: str,
        relative_path: str,
        record_tag: str | None = None,
        query: str | None = None,
        offset: int = 0,
        limit: int = 25,
    ) -> dict:
        """Inspect XML tags or read exact record_tag matches with raw attributes and nested children.
        Omit record_tag for schema discovery. Includes ordinal provenance; no property IDs are guessed.
        """
        return service.read(
            root_id, relative_path, "xml", record_tag=record_tag, query=query, offset=offset, limit=limit
        )

    @tool()
    def eplan_read_access(
        root_id: str,
        relative_path: str,
        table: str | None = None,
        offset: int = 0,
        limit: int = 25,
        column: str | None = None,
        start: int = 0,
        length: int = 8000,
    ) -> dict:
        """List local Access base tables or read rows from an exact returned table name.
        Uses Windows ACE in read-only mode against an isolated copy. No arbitrary SQL or saved queries.
        Table row ordinals reflect provider order under the returned source hash, not inferred keys.
        For a full cell, supply column and zero-based row offset; start/length slice text or binary data.
        """
        return service.read(
            root_id,
            relative_path,
            "access",
            table=table,
            offset=offset,
            limit=limit,
            column=column,
            start=start,
            length=length,
        )

    @tool()
    def eplan_read_project_link(root_id: str, relative_path: str, offset: int = 0, limit: int = 50) -> dict:
        """Read ELK/ELL link text and bounded inventory of its local EDB folder, without opening EPLAN.
        Target must stay under the configured root. Folder inventory is not an atomic project snapshot.
        """
        return service.project(root_id, relative_path, offset, limit)

    @tool()
    def eplan_read_binary_bytes(
        root_id: str,
        relative_path: str,
        byte_offset: int = 0,
        byte_length: int = 256,
        stream_offset: int | None = None,
    ) -> dict:
        """Read at most 4096 bytes as hex from local EPLAN data or a checksum-valid zlib stream.
        byte_offset refers to source bytes, or inflated bytes when stream_offset selects a stream.
        """
        return service.read(
            root_id,
            relative_path,
            "bytes",
            byte_offset=byte_offset,
            byte_length=byte_length,
            stream_offset=stream_offset,
        )

    @tool()
    def eplan_find_compressed_streams(
        root_id: str,
        relative_path: str,
        byte_offset: int = 0,
        byte_length: int = 4194304,
        offset: int = 0,
        limit: int = 50,
    ) -> dict:
        """Find checksum-valid zlib streams whose headers start within a bounded 4 MiB source window.
        Continue next_scan_byte_offset for coverage; scan budgets and record pagination are separate.
        These are compressed byte streams, not decoded EPLAN object records.
        """
        return service.read(
            root_id,
            relative_path,
            "streams",
            byte_offset=byte_offset,
            byte_length=byte_length,
            offset=offset,
            limit=limit,
        )

    @tool()
    def eplan_read_binary_text(
        root_id: str,
        relative_path: str,
        byte_offset: int = 0,
        byte_length: int = 65536,
        stream_offset: int | None = None,
        minimum_length: int = 4,
        query: str | None = None,
        offset: int = 0,
        limit: int = 50,
        text_encoding: str | None = None,
    ) -> dict:
        """Read offset-bound text candidates from raw or inflated local data.
        Default is ASCII/ASCII-compatible UTF-16. Explicit text_encoding accepts utf-8, utf-16-le,
        utf-16-be or cp1252; invalid units split runs. Align UTF-16 at the selected byte_offset.
        False positives and window-edge fragments are possible. No electrical identity/relationship inferred.
        """
        return service.read(
            root_id,
            relative_path,
            "text",
            byte_offset=byte_offset,
            byte_length=byte_length,
            stream_offset=stream_offset,
            minimum_length=minimum_length,
            text_encoding=text_encoding,
            query=query,
            offset=offset,
            limit=limit,
        )
