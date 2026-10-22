"""EPLAN claims in the shared manager ledger; containment remains app-owned."""

from __future__ import annotations

import os


class ResourceClaims:
    def __init__(self, *, ledger=None, owner_id=None):
        if ledger is None:
            from universal_tools.resources import ResourceLedger

            ledger = ResourceLedger(os.environ.get("EPLAN_MANAGEMENT_REGISTRY"), max_active_per_app=32)
        self.ledger = ledger
        # This object is constructed inside the actual exclusive supervisor, never a CLI helper.
        self.owner = ledger.owner("eplan", owner_id=owner_id)
        self.pending = set()

    def begin(self, label):
        record = self.owner.begin_launch(label, kind="offline-worker", cleanup_mode="terminate")
        self.pending.add(record.resource_id)
        return record.resource_id

    def bind(self, resource_id, pid, handle):
        from universal_tools.resources import ProcessIdentity

        # Compare the record against identity captured from the retained creation handle.
        expected = ProcessIdentity.model_validate(self.ledger.driver.capture_handle(handle, pid))
        record = self.owner.bind_process(resource_id, pid, containment="app_owned")
        if record.process != expected:
            self.barrier(
                resource_id, "Identity differs from retained creation handle; inspect before recovery"
            )
            raise ValueError("Shared resource identity differs from retained process handle")

    def barrier(self, resource_id, reason):
        self.owner.set_recovery_barrier(resource_id, reason)

    def completed(self, resource_id):
        record = self.ledger.get(resource_id)
        if record.recovery_barrier or record.receipt:
            raise ValueError("Resource recovery barrier/receipt requires independent inspection; no replay")
        # This attests only the app's verified tree teardown. The shared API rechecks process exit.
        self.owner.reconcile(
            resource_id,
            record.revision,
            "App-owned job teardown verified empty and creation handle signalled, or child creation never occurred",
        )
        self.pending.discard(resource_id)

    def close(self):
        if self.pending:
            raise ValueError(
                "Shared resource claims remain unresolved; preserve records and inspect recovery"
            )
        self.owner.close()

    def snapshot(self):
        return {
            "initialized": True,
            "owner_id": self.owner.owner_id,
            "supervisor_pid": self.owner.identity.pid,
            "unresolved_claims": len(self.pending),
            "resource_ids": sorted(self.pending),
            "app_admission_limit": self.ledger.maximum,
            "cleanup": "Reviewed manager recovery only; no automatic orphan cleanup or journal replay",
        }
