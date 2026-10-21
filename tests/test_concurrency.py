import contextlib
import multiprocessing
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import anyio
import pytest

from eplan_mcp.coordination import Coordinator, RequestScheduler, ResourceBusy
from eplan_mcp.transactions import Transactions


def hold_lock(state, entered, release):
    with Coordinator(Path(state), timeout=2).lock("shared"):
        entered.set()
        release.wait(20)


def occupy_pool(state, entered, release):
    with Coordinator(Path(state), timeout=10).pool("test", 2):
        entered.put("entered")
        release.wait(20)


def abandon_transaction(state, entered, release):
    path = Path(state)
    tx = Transactions(path, Coordinator(path))

    def effect():
        (path / "effect.txt").write_text("executed once")
        entered.set()
        release.wait(20)
        return {"done": True}

    tx.execute("crashed", "export", {}, effect)


def test_cross_process_lock_released_after_owner_death(tmp_path):
    context = multiprocessing.get_context("spawn")
    entered, release = context.Event(), context.Event()
    process = context.Process(target=hold_lock, args=(str(tmp_path), entered, release))
    process.start()
    try:
        assert entered.wait(10)
        with pytest.raises(ResourceBusy):
            with Coordinator(tmp_path).lock("shared", timeout=0.05):
                pass
        process.terminate()
        process.join(10)
        with Coordinator(tmp_path).lock("shared", timeout=1):
            pass
    finally:
        if process.is_alive():
            process.terminate()
        process.join(10)


def test_cross_process_worker_capacity(tmp_path):
    context = multiprocessing.get_context("spawn")
    entered, release = context.Queue(), context.Event()
    processes = [
        context.Process(target=occupy_pool, args=(str(tmp_path), entered, release)) for _ in range(4)
    ]
    for process in processes:
        process.start()
    try:
        assert entered.get(timeout=10) == "entered"
        assert entered.get(timeout=10) == "entered"
        import queue

        with pytest.raises(queue.Empty):
            entered.get(timeout=0.2)
        release.set()
        assert entered.get(timeout=10) == "entered"
        assert entered.get(timeout=10) == "entered"
        for process in processes:
            process.join(10)
            assert process.exitcode == 0
    finally:
        release.set()
        for process in processes:
            if process.is_alive():
                process.terminate()
            process.join(10)


def test_duplicate_cold_extraction_runs_one_worker(drawing_service, monkeypatch):
    service, _ = drawing_service
    original, guard, count = service._extract_to_cache, threading.Lock(), 0

    def counted(*args):
        nonlocal count
        with guard:
            count += 1
        return original(*args)

    monkeypatch.setattr(service, "_extract_to_cache", counted)
    with ThreadPoolExecutor(4) as pool:
        documents = list(pool.map(lambda _: service.load("test", "sample.pdf"), range(4)))
    assert count == 1
    assert all(doc == documents[0] for doc in documents)
    assert not list((service.config.state / "cache").glob("*.tmp"))


def test_index_failure_rolls_back_rows_and_metadata(drawing_service, monkeypatch):
    service, _ = drawing_service
    service._index_file("test", "sample.dxf")
    original = service.database
    with original() as db:
        before_records = db.execute("SELECT * FROM records ORDER BY record_index").fetchall()
        before_documents = db.execute("SELECT * FROM documents").fetchall()

    class Interrupted:
        def execute(self, *args):
            return self.db.execute(*args)

        def executemany(self, sql, rows):
            self.db.execute(sql, next(iter(rows)))
            raise RuntimeError("injected failure after a partial insert")

    @contextlib.contextmanager
    def interrupted():
        with original() as db:
            wrapper = Interrupted()
            wrapper.db = db
            yield wrapper

    monkeypatch.setattr(service, "database", interrupted)
    with pytest.raises(RuntimeError, match="partial insert"):
        service._index_file("test", "sample.dxf")
    with original() as db:
        assert db.execute("SELECT * FROM records ORDER BY record_index").fetchall() == before_records
        assert db.execute("SELECT * FROM documents").fetchall() == before_documents


def test_concurrent_write_idempotency_and_argument_conflict(tmp_path):
    tx = Transactions(tmp_path, Coordinator(tmp_path))
    count = 0

    def effect():
        nonlocal count
        count += 1
        return {"output": "one artifact"}

    with ThreadPoolExecutor(4) as pool:
        results = list(pool.map(lambda _: tx.execute("same", "export", {"project": "p"}, effect), range(4)))
    assert count == 1 and sum(r["transaction"]["replayed"] for r in results) == 3
    assert tx.get("same", include_result=True)["result"] == {"output": "one artifact"}
    with pytest.raises(ValueError, match="conflicts"):
        tx.execute("same", "export", {"project": "different"}, effect)


def test_failed_request_is_not_reexecuted(tmp_path):
    tx = Transactions(tmp_path, Coordinator(tmp_path))
    count = 0

    def fail():
        nonlocal count
        count += 1
        raise ValueError("failure")

    with pytest.raises(ValueError):
        tx.execute("failed", "build", {}, fail)
    with pytest.raises(ValueError, match="not re-executed"):
        tx.execute("failed", "build", {}, fail)
    assert count == 1 and tx.get("failed")["state"] == "failed"


def test_unknown_result_retains_reason_and_empty_ids_are_rejected(tmp_path):
    tx = Transactions(tmp_path, Coordinator(tmp_path))
    with pytest.raises(ValueError, match="request_id"):
        tx.execute("", "export", {}, lambda: {"done": True})
    tx.execute("uncertain", "highlight", {}, lambda: {"status": "unknown", "error": "Timed out"})
    assert tx.get("uncertain")["error"] == "Timed out"
    replay = tx.execute("uncertain", "highlight", {}, lambda: pytest.fail("Uncertain action was repeated"))
    assert replay["transaction"]["state"] == "unknown" and replay["transaction"]["replayed"]


def test_crashed_write_is_unknown_and_not_reexecuted(tmp_path):
    context = multiprocessing.get_context("spawn")
    entered, release = context.Event(), context.Event()
    process = context.Process(target=abandon_transaction, args=(str(tmp_path), entered, release))
    process.start()
    try:
        assert entered.wait(10)
        process.terminate()
        process.join(10)
        tx = Transactions(tmp_path, Coordinator(tmp_path))
        assert tx.get("crashed")["state"] == "unknown"

        def prohibited_retry():
            pytest.fail("An uncertain operation must not execute twice")

        with pytest.raises(ValueError, match="not re-executed"):
            tx.execute("crashed", "export", {}, prohibited_retry)
        assert (tmp_path / "effect.txt").read_text() == "executed once"
    finally:
        if process.is_alive():
            process.terminate()
        process.join(10)


@pytest.mark.anyio
async def test_bounded_queue_and_responsive_control_calls():
    scheduler = RequestScheduler(workers=1, queued=0)
    entered, release = threading.Event(), threading.Event()

    def blocked():
        entered.set()
        assert release.wait(10)

    async with anyio.create_task_group() as group:
        group.start_soon(scheduler.run, blocked)
        assert await anyio.to_thread.run_sync(entered.wait, 5)
        try:
            with pytest.raises(ResourceBusy, match="queue is full"):
                await scheduler.run(lambda: None)
            status = await scheduler.run(scheduler.status, control=True)
            assert status["active"] == 1 and status["rejected"] == 1
        finally:
            release.set()
    assert scheduler.status()["active"] == 0


@pytest.mark.anyio
async def test_cancelled_caller_does_not_abandon_running_write(tmp_path):
    scheduler = RequestScheduler(workers=1)
    tx = Transactions(tmp_path, Coordinator(tmp_path))
    entered, release = threading.Event(), threading.Event()
    scope = anyio.CancelScope()

    def effect():
        entered.set()
        assert release.wait(10)
        return {"done": True}

    async def request():
        with scope:
            await scheduler.run(tx.execute, "cancelled", "export", {}, effect)

    async with anyio.create_task_group() as group:
        group.start_soon(request)
        assert await anyio.to_thread.run_sync(entered.wait, 5)
        scope.cancel()
        release.set()
    assert tx.get("cancelled")["state"] == "succeeded"


@pytest.mark.anyio
async def test_mcp_wrapper_keeps_event_loop_responsive(drawing_service, monkeypatch):
    from eplan_mcp.server import create_server

    service, _ = drawing_service
    entered, release = threading.Event(), threading.Event()

    def inspect(*args):
        entered.set()
        assert release.wait(10)
        return {"completed": True}

    monkeypatch.setattr(service, "inspect", inspect)
    server = create_server(service)
    results = []

    async def blocked():
        results.append(
            await server.call_tool("eplan_inspect", {"root_id": "test", "relative_path": "sample.pdf"})
        )

    async with anyio.create_task_group() as group:
        group.start_soon(blocked)
        assert await anyio.to_thread.run_sync(entered.wait, 5)
        try:
            result = await server.call_tool("eplan_concurrency_status", {})
            assert result and not results
        finally:
            release.set()
    assert results
