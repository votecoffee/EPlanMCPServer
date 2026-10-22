"""Pure handle/thread stubs; no COM, management listener, process or engineering app startup."""

import threading
from types import SimpleNamespace

import pytest

from eplan_mcp.local_data import close_access_resources
from eplan_mcp.management import Reporting


def test_access_cleanup_attempts_remaining_handles_after_failure():
    events = []

    class Record:
        State = 1

        def Close(self):
            events.append("record")
            raise RuntimeError("synthetic read-only record close refusal")

    schema = SimpleNamespace(State=1, Close=lambda: events.append("schema"))
    connection = SimpleNamespace(State=1, Close=lambda: events.append("connection"))
    catalog = SimpleNamespace(ActiveConnection=connection)
    with pytest.raises(ValueError, match="cleanup is unverified"):
        close_access_resources(connection, schema, Record(), catalog)
    assert events == ["record", "schema", "connection"]
    assert catalog.ActiveConnection is None


def test_access_cleanup_does_not_close_already_closed_recordsets():
    def forbidden():
        pytest.fail("Already closed handle must not be closed again")

    closed = SimpleNamespace(State=0, Close=forbidden)
    close_access_resources(closed, closed, closed, None)


def test_reporting_startup_failure_closes_its_agent(monkeypatch):
    events = []
    reporting = object.__new__(Reporting)
    reporting.stopped = threading.Event()
    reporting.agent = SimpleNamespace(
        start=lambda: events.append("agent_start"), close=lambda: events.append("agent_close")
    )

    class FailedThread:
        def __init__(self, **kwargs):
            pass

        def start(self):
            raise RuntimeError("synthetic cache-thread startup failure")

    monkeypatch.setattr("eplan_mcp.management.threading.Thread", FailedThread)
    with pytest.raises(RuntimeError, match="startup failure"):
        reporting.__enter__()
    assert events == ["agent_start", "agent_close"]
    assert reporting.stopped.is_set()


def test_reporting_join_failure_still_closes_its_agent():
    events = []
    reporting = object.__new__(Reporting)
    reporting.stopped = threading.Event()
    reporting.agent = SimpleNamespace(close=lambda: events.append("agent_close"))

    def join(**kwargs):
        raise RuntimeError("synthetic join failure")

    reporting.thread = SimpleNamespace(join=join)
    with pytest.raises(RuntimeError, match="join failure"):
        reporting.__exit__()
    assert reporting.stopped.is_set() and events == ["agent_close"]
