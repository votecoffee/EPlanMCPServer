"""Shared-ledger integration with synthetic process identities only; no OS process launches."""

import os

import pytest
from universal_tools.resources import ProcessIdentity, ResourceLedger

from eplan_mcp.resource_claims import ResourceClaims


class IdentityDriver:
    def __init__(self):
        self.alive = True
        self.mismatch = False

    def capture(self, pid):
        return {
            "host_id": "a" * 64,
            "pid": pid,
            "created": "100" if pid == os.getpid() else "200",
            "executable": "C:\\fixture\\supervisor.exe" if pid == os.getpid() else "C:\\fixture\\worker.exe",
        }

    def capture_handle(self, handle, pid):
        assert handle == 101
        value = self.capture(pid)
        if self.mismatch:
            value["created"] = "300"
        return value

    def state(self, identity):
        return "alive" if identity["pid"] == os.getpid() or self.alive else "absent"


@pytest.fixture
def claims(tmp_path):
    driver = IdentityDriver()
    ledger = ResourceLedger(tmp_path / "private-registry", driver=driver)
    return ResourceClaims(ledger=ledger, owner_id="b" * 32), driver


def test_claim_uses_actual_supervisor_and_private_termination_policy(claims):
    owner, driver = claims
    resource = owner.begin("Synthetic parser")
    record = owner.ledger.get(resource)
    assert record.owner.pid == os.getpid()
    assert record.owner_id == "b" * 32
    assert record.app_id == "eplan" and record.ownership == "private"
    assert record.cleanup_mode == "terminate" and record.state == "launching"
    owner.bind(resource, 777, 101)
    record = owner.ledger.get(resource)
    assert record.process == ProcessIdentity.model_validate(driver.capture(777))
    assert record.containment == "app_owned"
    with pytest.raises(ValueError, match="inspect/stop"):
        owner.completed(resource)
    driver.alive = False
    owner.completed(resource)
    record = owner.ledger.get(resource)
    assert record.state == "released" and record.reconciliation
    owner.close()


def test_identity_mismatch_records_barrier_and_never_silently_rebinds(claims):
    owner, driver = claims
    resource = owner.begin("Synthetic parser")
    driver.mismatch = True
    with pytest.raises(ValueError, match="retained process handle"):
        owner.bind(resource, 777, 101)
    record = owner.ledger.get(resource)
    assert record.recovery_barrier and record.process.created == "200"
    driver.alive = False
    with pytest.raises(ValueError, match="barrier/receipt"):
        owner.completed(resource)
    with pytest.raises(ValueError, match="remain unresolved"):
        owner.close()


def test_failed_creation_can_retire_unbound_reservation_without_guessing_pid(claims):
    owner, _ = claims
    resource = owner.begin("Synthetic failed creation")
    owner.completed(resource)
    record = owner.ledger.get(resource)
    assert record.process is None and record.state == "released"
    assert record.reconciliation and not record.receipt


def test_uncertain_tree_cleanup_keeps_claim_for_review(claims):
    owner, _ = claims
    resource = owner.begin("Synthetic parser")
    owner.bind(resource, 777, 101)
    owner.barrier(resource, "Synthetic tree closure cannot be confirmed")
    with pytest.raises(ValueError, match="remain unresolved"):
        owner.close()
    assert owner.ledger.get(resource).state == "active"
