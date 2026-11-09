"""Evidence contract models: mirrored enums, envelopes, and the fixtures that exercise them."""

import importlib.util
import json
import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from triage.evidence import GrantEvidence, PurchaseEvidence, parse_evidence
from triage.payments_lab import (
    IN_FLIGHT_PAYMENT_STATES,
    TERMINAL_PAYMENT_STATES,
    AuditExport,
    DeliveryState,
    PaymentState,
)
from triage.source import PAYMENTS_LAB_COMMIT

EVIDENCE_DIR = Path(__file__).parent / "fixtures" / "evidence"
FIXTURE_NAMES = sorted(path.stem for path in EVIDENCE_DIR.glob("*.json"))


def _generator():
    spec = importlib.util.spec_from_file_location("generate", EVIDENCE_DIR / "generate.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# --- mirror of the pinned upstream ------------------------------------------------------------


def test_source_is_pinned_to_a_full_commit_sha():
    assert re.fullmatch(r"[0-9a-f]{40}", PAYMENTS_LAB_COMMIT)


def test_payment_states_match_pinned_domain():
    assert [state.value for state in PaymentState] == [
        "denied", "reserved", "executing", "unknown", "settled", "failed", "not_required",
    ]  # fmt: skip
    assert TERMINAL_PAYMENT_STATES | IN_FLIGHT_PAYMENT_STATES == set(PaymentState)
    assert not TERMINAL_PAYMENT_STATES & IN_FLIGHT_PAYMENT_STATES


def test_delivery_states_match_pinned_domain():
    assert [state.value for state in DeliveryState] == ["not_requested", "failed", "delivered"]


def test_audit_export_rejects_unknown_fields_and_floats():
    base = _generator().export("p-x", "settled", "delivered")
    AuditExport.model_validate(base)
    with pytest.raises(ValidationError):
        AuditExport.model_validate({**base, "receipt": {}})
    with pytest.raises(ValidationError):
        AuditExport.model_validate({**base, "amount": 250000.0})
    with pytest.raises(ValidationError):
        AuditExport.model_validate({**base, "request_fingerprint": "not-a-sha256"})
    with pytest.raises(ValidationError):
        AuditExport.model_validate({**base, "payment_state": "pending"})


def test_models_are_frozen():
    export = AuditExport.model_validate(_generator().export("p-x", "settled"))
    with pytest.raises(ValidationError):
        export.payment_state = PaymentState.FAILED


# --- fixtures ---------------------------------------------------------------------------------


def test_fixture_set_is_present():
    assert len(FIXTURE_NAMES) == 25


@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_every_fixture_parses_as_an_envelope(name):
    with open(EVIDENCE_DIR / f"{name}.json", encoding="utf-8") as handle:
        data = json.load(handle)
    item = parse_evidence(data)
    assert isinstance(item, GrantEvidence if name.startswith("grant_") else PurchaseEvidence)
    assert item.source_version == PAYMENTS_LAB_COMMIT


def test_committed_fixtures_match_generator():
    expected = _generator().build_all()
    assert sorted(expected) == FIXTURE_NAMES
    for name, data in expected.items():
        with open(EVIDENCE_DIR / f"{name}.json", encoding="utf-8") as handle:
            assert json.load(handle) == data, name


def test_parse_evidence_needs_a_known_kind():
    with pytest.raises(ValidationError):
        parse_evidence({"kind": "ticket_text", "text": "I was charged twice"})


# --- grant bundles ----------------------------------------------------------------------------


def test_complete_consistent_bundle(evidence):
    bundle = evidence("grant_complete_single")
    assert bundle.is_complete
    assert bundle.missing_purchase_ids == ()
    assert bundle.unlisted_purchase_ids == ()
    assert bundle.duplicated_purchase_ids == ()
    assert bundle.foreign_purchase_ids == ()
    assert bundle.skew_seconds == 20
    assert bundle.is_consistent(300)
    assert not bundle.is_consistent(19)


def test_bundle_missing_export_is_incomplete(evidence):
    bundle = evidence("grant_incomplete_missing")
    assert not bundle.is_complete
    assert bundle.missing_purchase_ids == ("p-32",)


def test_bundle_with_unlisted_export_is_incomplete(evidence):
    bundle = evidence("grant_incomplete_unlisted")
    assert not bundle.is_complete
    assert bundle.unlisted_purchase_ids == ("p-41",)


def test_bundle_with_two_exports_for_one_purchase_is_incomplete(evidence):
    single = evidence("grant_complete_single")
    doubled = single.model_copy(update={"exports": single.exports + (single.exports[0],)})
    assert not doubled.is_complete
    assert doubled.duplicated_purchase_ids == ("p-20",)


def test_bundle_skew_and_foreign_exports_are_inconsistent(evidence):
    skewed = evidence("grant_skewed")
    assert skewed.is_complete
    assert skewed.skew_seconds == 400
    assert not skewed.is_consistent(300)
    foreign = evidence("grant_foreign_export")
    assert foreign.is_complete
    assert foreign.foreign_purchase_ids == ("p-61",)
    assert not foreign.is_consistent(300)


def test_manifest_may_not_repeat_a_purchase(evidence):
    single = evidence("grant_complete_single")
    with pytest.raises(ValidationError, match="more than once"):
        GrantEvidence.model_validate(
            {**single.model_dump(), "manifest": ["p-20", "p-20", "p-21", "p-22"]}
        )


def test_empty_bundle_has_zero_skew(evidence):
    single = evidence("grant_complete_single")
    empty = single.model_copy(update={"manifest": (), "exports": ()})
    assert empty.skew_seconds == 0
    assert empty.is_complete
