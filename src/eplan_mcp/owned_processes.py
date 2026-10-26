"""Exclusive Windows child trees. No PID discovery, attachment, shared app adoption or retries.

Source implementation only: isolated Windows lifetime acceptance is still required.
"""

from __future__ import annotations

import contextvars
import json
import os
import subprocess
import tempfile
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

cancel_requested = contextvars.ContextVar("eplan_child_cancel", default=None)
_guard = threading.RLock()
_active = {}
_recent = []
_closing = False
_owner = uuid.uuid4().hex
_evidence = None
_owner_job = None
_exclusive_owner = False
_claims = None
_job_name = "Local\\EPlanMCP-owner-" + _owner
_owner_limits = (64, None)


def contain_frontdoor():
    """Bound this exclusive metadata/analysis tree before serving any requests."""
    global _owner_limits
    if not _exclusive_owner or _owner_job is not None:
        raise ValueError("Frontdoor containment requires a fresh exclusive owner")
    _owner_limits = (12, 768 * 1024 * 1024)
    import win32api
    import win32job

    _contain_owner(win32job, win32api)


def _resource_claims():
    global _claims
    if _claims is None:
        from .resource_claims import ResourceClaims

        _claims = ResourceClaims(owner_id=_owner, evidence=_evidence)
    return _claims


def _contain_owner(api, kernel):
    """Contain this exclusive app process before creation, closing the pre-assignment death gap.

    Retain this non-inherited job handle until OS process exit. Closing it explicitly would kill
    the owner itself. Children inherit membership at creation, without breakaway permission.
    """
    global _owner_job
    with _guard:
        if _owner_job is not None:
            return
        candidate = api.CreateJobObject(None, _job_name)
        try:
            limits = api.QueryInformationJobObject(candidate, api.JobObjectExtendedLimitInformation)
            limits["BasicLimitInformation"]["LimitFlags"] = (
                api.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE | api.JOB_OBJECT_LIMIT_ACTIVE_PROCESS
            )
            limits["BasicLimitInformation"]["ActiveProcessLimit"] = _owner_limits[0]
            if _owner_limits[1] is not None:
                limits["BasicLimitInformation"]["LimitFlags"] |= api.JOB_OBJECT_LIMIT_JOB_MEMORY
                limits["JobMemoryLimit"] = _owner_limits[1]
            api.SetInformationJobObject(candidate, api.JobObjectExtendedLimitInformation, limits)
            api.AssignProcessToJobObject(candidate, kernel.GetCurrentProcess())
        except BaseException:
            candidate.Close()
            raise
        # A PyHANDLE destructor during interpreter finalization could terminate the owner too
        # early. Transfer the handle to OS process-lifetime ownership, without closing it.
        _owner_job = candidate.Detach()


def bind_evidence(state):
    global _evidence
    with _guard:
        selected = Path(state).resolve() / "owned-resources"
        if selected.exists() and selected.resolve() != selected:
            raise ValueError("Resource evidence directory must not redirect outside selected state")
        if _evidence is not None and _evidence != selected:
            raise ValueError("Cannot switch resource-owner state within a process")
        _evidence = selected


def _persist(record):
    if _evidence is None:
        raise ValueError("Bind private resource evidence before launching a child")
    _evidence.mkdir(parents=True, exist_ok=True)
    path = _evidence / (record["resource_id"] + ".json")
    temporary = path.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        stream.write(json.dumps(record, sort_keys=True))
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def snapshot():
    with _guard:
        return {
            "owner_id": _owner,
            "active_trees": len(_active),
            "max_active_trees": 16,
            "ownership": "Exclusive app-launched children only; PIDs are diagnostic, handles authorize cleanup",
            "attached_or_shared_apps": "Not acquired; never enumerated or terminated",
            "runtime_acceptance": "Artifact-specific selected direct-profile evidence; status is not a deployment certificate",
            "shared_ledger": _claims.snapshot() if _claims is not None else {"initialized": False},
            "items": [dict(item[0]) for item in _active.values()] + [dict(r) for r in _recent[-16:]],
        }


def close_owned():
    """Request teardown by retained job handles; worker threads own final handle disposal."""
    global _closing
    with _guard:
        _closing = True
        failures = []
        for record, stop in list(_active.values()):
            record["state"] = "owner_closing"
            try:
                _persist(record)
            except BaseException as error:
                failures.append(error)
            finally:
                try:
                    stop()
                except BaseException as error:
                    record["state"] = "cleanup_unverified"
                    failures.append(error)
        if failures:
            raise RuntimeError(
                "Owned resource cleanup/persistence is unverified; retained handles and records require inspection"
            ) from failures[0]
    deadline = time.monotonic() + 5
    while True:
        with _guard:
            if not _active:
                if _claims is not None:
                    _claims.close()
                return
        if time.monotonic() >= deadline:
            raise RuntimeError("Owned resource close is unverified; workers have not released their handles")
        time.sleep(0.025)


@contextmanager
def owner_scope(*, exclusive=False):
    global _exclusive_owner
    if not exclusive or _exclusive_owner:
        raise ValueError(
            "Child containment requires a dedicated exclusive app process; no library-host adoption"
        )
    _exclusive_owner = True
    try:
        yield
    finally:
        try:
            close_owned()
        finally:
            _exclusive_owner = False


def run(
    args,
    *,
    timeout,
    check=False,
    capture_output=True,
    stdin=None,
    encoding=None,
    errors=None,
    text=False,
    creationflags=0,
):
    """Run argv without a shell in a suspended-then-assigned Windows kill-on-close job.

    Only disposable parser/converter/CLI children are allowed. No native editor or dirty project
    attachment. Normal completion also terminates remaining descendants. Output is disk-spooled
    and bounded, avoiding inherited MCP pipes and descendant-held capture pipes.
    """
    global _closing
    if os.name != "nt":
        raise ValueError("Owned child-tree containment requires Windows; no unmanaged fallback")
    if not _exclusive_owner or _evidence is None:
        raise ValueError("Child launch requires exclusive process ownership and private resource evidence")
    if not isinstance(args, (list, tuple)) or not args or not all(isinstance(a, str) for a in args):
        raise ValueError("Owned processes require a nonempty string argv; shell commands are unsupported")
    if not capture_output or stdin not in (None, subprocess.DEVNULL) or timeout <= 0:
        raise ValueError("Owned processes require bounded timeout, file capture and detached stdin")
    import _winapi
    import msvcrt

    import win32api
    import win32con
    import win32event
    import win32job
    import win32process

    from .operation_progress import OperationCancelled

    record = {
        "schema_version": 1,
        "resource_kind": "exclusive_process_tree",
        "resource_id": uuid.uuid4().hex,
        "owner_id": _owner,
        "owner_pid": os.getpid(),
        "owner_creation_time": str(
            win32process.GetProcessTimes(win32api.GetCurrentProcess())["CreationTime"]
        ),
        "state": "reserved",
        "exclusive": True,
        "containment": "windows-kill-on-close-job",
        "executable_name": Path(args[0]).name,
        "pid": None,
        "creation_time": None,
        "recovery": "No automatic replay; inspect app receipts after interruption",
    }
    job = None
    process = thread = None
    duplicates = []
    # Reserve before launch. No native process is created at capacity or after close begins.
    with _guard:
        if _closing or len(_active) >= 16:
            raise ValueError("Resource owner is closing or owned-tree capacity is exhausted")
        record["framework_resource_id"] = _resource_claims().begin(
            "EPLAN offline worker: " + Path(args[0]).name
        )
        record["owner_identity"] = _claims.owner.identity.model_dump(mode="json")
        record["owner_job"] = _job_name
        record["owner_job_contract"] = 1
        try:
            _persist(record)
        except BaseException:
            _closing = True
            raise
        _active[record["resource_id"]] = (record, lambda: None)
    try:
        cancellation = cancel_requested.get()
        if cancellation is not None and cancellation.is_set():
            raise OperationCancelled()
        _contain_owner(win32job, win32api)
        job = win32job.CreateJobObject(None, "")
        limits = win32job.QueryInformationJobObject(job, win32job.JobObjectExtendedLimitInformation)
        limits["BasicLimitInformation"]["LimitFlags"] = (
            win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE | win32job.JOB_OBJECT_LIMIT_ACTIVE_PROCESS
        )
        limits["BasicLimitInformation"]["ActiveProcessLimit"] = 16
        win32job.SetInformationJobObject(job, win32job.JobObjectExtendedLimitInformation, limits)
        with (
            tempfile.TemporaryFile() as output,
            tempfile.TemporaryFile() as error_output,
            open(os.devnull, "rb") as null,
        ):
            for stream in (null, output, error_output):
                duplicates.append(
                    win32api.DuplicateHandle(
                        win32api.GetCurrentProcess(),
                        msvcrt.get_osfhandle(stream.fileno()),
                        win32api.GetCurrentProcess(),
                        0,
                        True,
                        win32con.DUPLICATE_SAME_ACCESS,
                    )
                )
            startup = subprocess.STARTUPINFO()
            startup.dwFlags = subprocess.STARTF_USESTDHANDLES
            startup.hStdInput, startup.hStdOutput, startup.hStdError = map(int, duplicates)
            startup.lpAttributeList = {"handle_list": list(map(int, duplicates))}
            # CPython's same low-level creation API as subprocess, retaining the primary thread
            # handle so no child code runs before containment. No shell or breakaway flags.
            process, thread, pid, _ = _winapi.CreateProcess(
                None,
                subprocess.list2cmdline(args),
                None,
                None,
                True,
                win32con.CREATE_SUSPENDED | subprocess.CREATE_NO_WINDOW | 0x00080000,
                {**os.environ, "EPLAN_RESOURCE_OWNER_STATE": str(_evidence.parent)},
                None,
                startup,
            )
            win32job.AssignProcessToJobObject(job, process)
            _claims.bind(record["framework_resource_id"], pid, process)
            record.update(
                pid=pid,
                creation_time=str(win32process.GetProcessTimes(process)["CreationTime"]),
                state="contained_suspended",
            )
            with _guard:
                cancellation = cancel_requested.get()
                if _closing or (cancellation is not None and cancellation.is_set()):
                    raise OperationCancelled()
                _active[record["resource_id"]] = (record, lambda: win32job.TerminateJobObject(job, 1))
                _persist(record)
                win32process.ResumeThread(thread)
                record["state"] = "running"
                _persist(record)
            deadline = time.monotonic() + timeout
            while win32event.WaitForSingleObject(process, 100) == win32event.WAIT_TIMEOUT:
                cancellation = cancel_requested.get()
                if cancellation is not None and cancellation.is_set():
                    raise OperationCancelled()
                if time.monotonic() >= deadline:
                    raise subprocess.TimeoutExpired(args, timeout)
                if (
                    max(os.fstat(output.fileno()).st_size, os.fstat(error_output.fileno()).st_size)
                    > 4 * 1024 * 1024
                ):
                    raise ValueError("Owned child output exceeded 4 MiB capture budget")
            code = win32process.GetExitCodeProcess(process)
            record["state"] = "cleanup_requested"
            _persist(record)
            win32job.TerminateJobObject(job, 1)  # Child exit never authorizes background descendants.
            _wait_empty(win32job, job)
            record.update(state="closed", returncode=code)
            output.seek(0)
            error_output.seek(0)
            stdout, stderr = output.read(4 * 1024 * 1024 + 1), error_output.read(4 * 1024 * 1024 + 1)
            if max(len(stdout), len(stderr)) > 4 * 1024 * 1024:
                raise ValueError("Owned child output exceeded 4 MiB capture budget")
            if text or encoding is not None:
                stdout = stdout.decode(encoding or "utf-8", errors=errors or "strict")
                stderr = stderr.decode(encoding or "utf-8", errors=errors or "strict")
            result = subprocess.CompletedProcess(args, code, stdout, stderr)
            if check:
                result.check_returncode()
            return result
    except BaseException as error:
        record["state"] = "interrupted_or_failed"
        record["failure_type"] = type(error).__name__
        raise
    finally:
        # Creation/assignment/startup failure still owns its suspended child by handle.
        try:
            if record["state"] != "closed":
                record["cleanup_requested"] = True
                try:
                    _persist(record)
                except BaseException:
                    record["state"] = "cleanup_unverified"
            if process is not None and win32event.WaitForSingleObject(process, 0) == win32event.WAIT_TIMEOUT:
                _winapi.TerminateProcess(process, 1)
            if job is not None:
                win32job.TerminateJobObject(job, 1)
                _wait_empty(win32job, job)
            if (
                process is not None
                and win32event.WaitForSingleObject(process, 5000) == win32event.WAIT_TIMEOUT
            ):
                raise ValueError("Owned child handle has not signalled exit")
        except BaseException:
            record["state"] = "cleanup_unverified"
        finally:
            for handle in (thread, process):
                if handle is not None:
                    try:
                        _winapi.CloseHandle(handle)
                    except OSError:
                        record["state"] = "cleanup_unverified"
            for handle in duplicates:
                try:
                    handle.Close()
                except OSError:
                    record["state"] = "cleanup_unverified"
            with _guard:
                if job is not None:
                    try:
                        job.Close()  # Also enforces kill-on-close if explicit termination failed.
                    except OSError:
                        record["state"] = "cleanup_unverified"
                try:
                    if record["state"] == "cleanup_unverified":
                        _claims.barrier(
                            record["framework_resource_id"],
                            "App-owned tree cleanup is unverified; inspect retained app receipts",
                        )
                    else:
                        _claims.completed(record["framework_resource_id"])
                except BaseException:
                    record["state"] = "cleanup_unverified"
                _active.pop(record["resource_id"], None)
                _recent.append(dict(record))
                del _recent[:-32]
                if record["state"] == "cleanup_unverified":
                    _closing = True
                try:
                    _persist(record)
                except BaseException:
                    _closing = True
                    raise
            if record["state"] == "cleanup_unverified":
                raise ValueError(
                    "Owned resource cleanup is unverified; inspect retained records before further work"
                )


def _wait_empty(api, job):
    deadline = time.monotonic() + 5
    while api.QueryInformationJobObject(job, api.JobObjectBasicAccountingInformation)["ActiveProcesses"]:
        if time.monotonic() >= deadline:
            raise ValueError(
                "Owned tree termination is unverified; inspect retained resource and request records"
            )
        time.sleep(0.025)
