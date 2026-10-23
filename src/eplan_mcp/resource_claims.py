"""EPLAN claims in the shared manager ledger; containment remains app-owned."""

from __future__ import annotations

import json
import os
from pathlib import Path


class ResourceClaims:
    def __init__(self, *, ledger=None, owner_id=None, evidence=None, job_absent=None):
        if ledger is None:
            from universal_tools.resources import ResourceLedger

            ledger = ResourceLedger(os.environ.get("EPLAN_MANAGEMENT_REGISTRY"), max_active_per_app=32)
        self.ledger = ledger
        # This object is constructed inside the actual exclusive supervisor, never a CLI helper.
        self.owner = ledger.owner("eplan", owner_id=owner_id)
        self.pending = set()
        if evidence is not None:
            self.reconcile_dead_jobs(Path(evidence), job_absent or owner_job_absent)

    def reconcile_dead_jobs(self, evidence, absent):
        """Retire only departed full owner jobs with matching app attestations.

        Legacy records, live peers, uncertain receipts/barriers and all request journals
        are untouched. No process termination, domain replay or native attachment.
        """
        records = self.ledger.records()
        for record in records:
            if (
                record.app_id != "eplan"
                or record.kind != "offline-worker"
                or record.state not in {"launching", "active"}
                or record.ownership != "private"
                or record.cleanup_mode != "terminate"
                or record.recovery_barrier
                or record.receipt
                or record.reconciliation
                or record.owner_id == self.owner.owner_id
            ):
                continue
            if self.ledger.driver.state(record.owner.model_dump()) not in {"absent", "different"}:
                continue
            if record.process and self.ledger.driver.state(record.process.model_dump()) not in {
                "absent",
                "different",
            }:
                continue
            # Bound local lookup; a corrupt or missing proof leaves admission fenced.
            paths = list(evidence.glob("*.json"))
            if len(paths) > 4096:
                raise ValueError("Owned evidence inventory exceeds recovery budget")
            proofs = []
            for path in paths:
                if (
                    path.name.startswith("recovery-")
                    or path.is_symlink()
                    or getattr(path.stat(), "st_file_attributes", 0) & 0x400
                ):
                    continue
                if path.stat().st_size > 65536:
                    continue
                try:
                    row = json.loads(path.read_bytes())
                except (ValueError, OSError):
                    continue
                if row.get("framework_resource_id") == record.resource_id:
                    proofs.append(row)
            expected_job = "Local\\EPlanMCP-owner-" + record.owner_id
            if len(proofs) != 1:
                continue
            proof = proofs[0]
            if (
                proof.get("owner_job_contract") != 1
                or proof.get("owner_job") != expected_job
                or proof.get("owner_identity") != record.owner.model_dump(mode="json")
                or proof.get("state") == "cleanup_unverified"
                or not absent(expected_job)
            ):
                continue
            # Persist the independent observation first; never rewrite the old app proof.
            from universal_tools.resources import durable_json

            target = evidence / ("recovery-" + record.resource_id + "-" + record.revision + ".json")
            durable_json(
                target,
                {
                    "resource_id": record.resource_id,
                    "previous_revision": record.revision,
                    "owner_job": expected_job,
                    "observed": "owner/process departed; named full-generation job no longer exists",
                },
            )
            self.owner.reconcile(
                record.resource_id,
                record.revision,
                "Exact owner/process generations departed; durable app-owned full-generation named kill-on-close job is absent; no request replay",
            )

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
            "cleanup": "Exact departed full-generation job proofs may retire claims; legacy/uncertain claims require review; no termination or journal replay",
        }


def owner_job_absent(name):
    import pywintypes
    import win32job

    try:
        handle = win32job.OpenJobObject(4, False, name)  # query only; no termination authority
    except pywintypes.error as error:
        return error.winerror == 2  # Unknown/denied is not absence.
    else:
        handle.Close()
        return False
