"""Pure OS stubs: never starts a process, job, server, plugin or native application."""

import json
import os
import subprocess
import sys
import threading
from types import SimpleNamespace

import pytest

from eplan_mcp import owned_processes as owned
from eplan_mcp.operation_progress import OperationCancelled


@pytest.fixture
def fake_windows(tmp_path, monkeypatch):
    events = []
    values = SimpleNamespace(code=0, waits=[], fail_assign=False, fail_create=False, fail_stop=False)
    handles = []

    class Handle:
        def __init__(self, kind, fd=None):
            self.kind, self.fd = kind, fd
            self.value = 3000 + len(handles)
            handles.append(self)

        def __int__(self):
            return self.value

        def Close(self):
            events.append(("close", self.kind, self.value))

        def Detach(self):
            return self.value

    def job_info(handle, kind):
        return {"BasicLimitInformation": {}} if kind == 1 else {"ActiveProcesses": 0}

    def assign(job, process):
        events.append(("assign", job.value, process))
        if values.fail_assign and process != -1:
            raise OSError("synthetic assignment refusal")

    def create_job(security, name):
        assert name == ""  # pywin32 requires an empty string, not None, for an unnamed job.
        return Handle("job")

    def terminate(job, code):
        events.append(("stop_tree", job.value))
        if values.fail_stop:
            raise OSError("synthetic termination failure")

    def create(*args):
        events.append(("create", args[5], args[6]))
        if values.fail_create:
            raise OSError("synthetic startup failure")
        for handle in handles:
            if handle.kind == "stdio" and handle.value == args[8].hStdOutput:
                os.write(handle.fd, b"synthetic output")
        return 101, 102, 777, 888

    def wait(process, timeout):
        return values.waits.pop(0) if values.waits else 0

    fake_job = SimpleNamespace(
        CreateJobObject=create_job,
        QueryInformationJobObject=job_info,
        SetInformationJobObject=lambda *args: None,
        AssignProcessToJobObject=assign,
        TerminateJobObject=terminate,
        JobObjectExtendedLimitInformation=1,
        JobObjectBasicAccountingInformation=2,
        JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE=0x2000,
        JOB_OBJECT_LIMIT_ACTIVE_PROCESS=8,
    )
    modules = {
        "_winapi": SimpleNamespace(
            CreateProcess=create,
            CloseHandle=lambda h: events.append(("close_process_handle", h)),
            TerminateProcess=lambda h, code: events.append(("stop_process_handle", h)),
        ),
        "msvcrt": SimpleNamespace(get_osfhandle=lambda fd: fd),
        "win32api": SimpleNamespace(
            GetCurrentProcess=lambda: -1, DuplicateHandle=lambda owner, fd, *args: Handle("stdio", fd)
        ),
        "win32con": SimpleNamespace(DUPLICATE_SAME_ACCESS=2, CREATE_SUSPENDED=4),
        "win32event": SimpleNamespace(WaitForSingleObject=wait, WAIT_TIMEOUT=258),
        "win32job": fake_job,
        "win32process": SimpleNamespace(
            GetProcessTimes=lambda h: {"CreationTime": f"creation-{h}"},
            ResumeThread=lambda h: events.append(("resume", h)),
            GetExitCodeProcess=lambda h: values.code,
        ),
    }
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)
    claims = SimpleNamespace(
        begin=lambda label: "f" * 32,
        bind=lambda *args: events.append(("ledger_bind",)),
        barrier=lambda *args: events.append(("ledger_barrier",)),
        completed=lambda *args: events.append(("ledger_reconciled",)),
        close=lambda: events.append(("ledger_owner_closed",)),
        snapshot=lambda: {"initialized": True, "unresolved_claims": 0},
    )
    for name, value in {
        "_active": {},
        "_recent": [],
        "_closing": False,
        "_owner_job": None,
        "_evidence": None,
        "_exclusive_owner": True,
        "_claims": claims,
    }.items():
        monkeypatch.setattr(owned, name, value)
    owned.bind_evidence(tmp_path)
    return values, events, handles, tmp_path / "owned-resources"


def test_containment_precedes_creation_and_resume_with_persistent_identity(fake_windows):
    _, events, handles, folder = fake_windows
    result = owned.run(["parser.exe", "literal argument"], timeout=1, encoding="utf-8")
    assert result.stdout == "synthetic output"
    names = [event[0] for event in events]
    assert names.index("assign") < names.index("create") < names.index("resume") < names.index("stop_tree")
    assert names.index("create") < names.index("ledger_bind") < names.index("resume")
    record = json.loads(next(folder.glob("*.json")).read_bytes())
    assert record["state"] == "closed" and record["creation_time"] == "creation-101"
    assert record["owner_creation_time"] == "creation--1"
    assert record["exclusive"] and record["pid"] == 777
    assert owned.snapshot()["active_trees"] == 0
    jobs = [h for h in handles if h.kind == "job"]
    assert ("close", "job", jobs[0].value) not in events  # Owner job lives until OS process exit.
    assert ("close", "job", jobs[1].value) in events
    assert all(event[1] != 777 for event in events if event[0] == "stop_process_handle")


@pytest.mark.parametrize("failure", ["fail_assign", "fail_create"])
def test_startup_failure_never_resumes_child_and_closes_handles(fake_windows, failure):
    values, events, _, folder = fake_windows
    setattr(values, failure, True)
    with pytest.raises(OSError, match="synthetic"):
        owned.run(["parser.exe"], timeout=1)
    assert not any(e[0] == "resume" for e in events)
    assert owned.snapshot()["active_trees"] == 0
    assert json.loads(next(folder.glob("*.json")).read_bytes())["state"] == "interrupted_or_failed"


def test_cancellation_before_launch_and_after_resume(fake_windows):
    values, events, _, folder = fake_windows
    cancellation = threading.Event()
    token = owned.cancel_requested.set(cancellation)
    try:
        cancellation.set()
        with pytest.raises(OperationCancelled):
            owned.run(["parser.exe"], timeout=1)
        assert not any(e[0] == "create" for e in events)
        cancellation.clear()
        values.waits = [258]
        # Emulate caller cancellation arriving after the exclusively owned child is resumed.
        sys.modules["win32process"].ResumeThread = lambda h: cancellation.set()
        with pytest.raises(OperationCancelled):
            owned.run(["parser.exe"], timeout=1)
        assert any(e[0] == "stop_tree" for e in events)
        assert owned.snapshot()["active_trees"] == 0
        assert len(list(folder.glob("*.json"))) == 2
    finally:
        owned.cancel_requested.reset(token)


def test_timeout_and_cleanup_failure_are_not_success(fake_windows, monkeypatch):
    values, events, _, folder = fake_windows
    values.waits = [258]
    ticks = iter([0, 10])
    monkeypatch.setattr(owned.time, "monotonic", lambda: next(ticks, 10))
    with pytest.raises(subprocess.TimeoutExpired):
        owned.run(["parser.exe"], timeout=1)
    assert any(e[0] == "stop_tree" for e in events)


def test_failed_cleanup_retains_unverified_record(fake_windows):
    values, _, _, folder = fake_windows
    values.fail_stop = True
    with pytest.raises(ValueError, match="cleanup is unverified"):
        owned.run(["parser.exe"], timeout=1)
    assert json.loads(next(folder.glob("*.json")).read_bytes())["state"] == "cleanup_unverified"
    assert owned._closing
    with pytest.raises(ValueError, match="owner is closing"):
        owned.run(["parser.exe"], timeout=1)


def test_evidence_failure_before_launch_never_creates_process(fake_windows, monkeypatch):
    _, events, _, _ = fake_windows

    def fail(record):
        raise OSError("synthetic private evidence unavailable")

    monkeypatch.setattr(owned, "_persist", fail)
    with pytest.raises(OSError, match="evidence unavailable"):
        owned.run(["parser.exe"], timeout=1)
    assert not events
    assert owned.snapshot()["active_trees"] == 0


def test_pre_resume_evidence_failure_cleans_suspended_child(fake_windows, monkeypatch):
    _, events, _, folder = fake_windows
    persist = owned._persist

    def fail(record):
        if record["state"] == "contained_suspended":
            raise OSError("synthetic identity persistence failure")
        persist(record)

    monkeypatch.setattr(owned, "_persist", fail)
    with pytest.raises(OSError, match="identity persistence"):
        owned.run(["parser.exe"], timeout=1)
    assert not any(e[0] == "resume" for e in events)
    assert any(e[0] == "stop_tree" for e in events)
    assert json.loads(next(folder.glob("*.json")).read_bytes())["state"] == "interrupted_or_failed"


def test_close_capacity_and_borrowed_host_refuse_without_creation(fake_windows, monkeypatch):
    _, events, _, _ = fake_windows
    monkeypatch.setattr(owned, "_exclusive_owner", False)
    with pytest.raises(ValueError, match="exclusive process"):
        owned.run(["parser.exe"], timeout=1)
    monkeypatch.setattr(owned, "_exclusive_owner", True)
    monkeypatch.setattr(owned, "_active", {str(i): ({}, lambda: None) for i in range(16)})
    with pytest.raises(ValueError, match="capacity"):
        owned.run(["parser.exe"], timeout=1)
    assert not any(e[0] == "create" for e in events)


def test_owner_close_attempts_every_owned_tree_despite_one_failure(fake_windows):
    _, events, _, _ = fake_windows

    def fail():
        raise OSError("synthetic first resource refusal")

    for key, stop in [("first", fail), ("second", lambda: events.append(("second_stopped",)))]:
        owned._active[key] = ({"resource_id": key, "state": "running"}, stop)
    with pytest.raises(RuntimeError, match="cleanup/persistence"):
        owned.close_owned()
    assert ("second_stopped",) in events
    assert owned._closing
