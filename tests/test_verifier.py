"""One test per verifier rule and per reason code. Pure, offline, fixture-driven."""

import pytest
from pydantic import ValidationError

from triage.claims import Claim, ClaimType
from triage.payments_lab import DeliveryState, PaymentState
from triage.verifier import Details, Outcome, ReasonCode, VerificationResult, verify

CREATED_AT = 1_000  # tests/fixtures/evidence/generate.py: TICKET_CREATED_AT
GRANT = "grant-research-01"


def claim(claim_type, purchase_id=None, grant_id=None):
    return Claim(
        claim_type=claim_type, purchase_id=purchase_id, grant_id=grant_id, created_at=CREATED_AT
    )


def unverifiable(result, reason):
    assert result.outcome is Outcome.UNVERIFIABLE
    assert result.reason is reason
    return result


# --- claims ------------------------------------------------------------------------------------


def test_claim_carries_no_ticket_text():
    with pytest.raises(ValidationError):
        Claim(
            claim_type=ClaimType.CHARGED_NOT_DELIVERED,
            purchase_id="p-01",
            created_at=CREATED_AT,
            text="I was charged and got nothing",
        )


def test_claim_needs_a_subject():
    with pytest.raises(ValidationError, match="purchase_id, a grant_id"):
        Claim(claim_type=ClaimType.DUPLICATE_CHARGE, created_at=CREATED_AT)


@pytest.mark.parametrize(
    "claim_type",
    [
        ClaimType.CHARGED_NOT_DELIVERED,
        ClaimType.UNAUTHORIZED_PURCHASE,
        ClaimType.CHARGED_BUT_DENIED,
    ],
)
def test_purchase_scoped_claims_require_a_purchase_id(claim_type):
    with pytest.raises(ValidationError, match="purchase_id required"):
        Claim(claim_type=claim_type, grant_id=GRANT, created_at=CREATED_AT)


def test_duplicate_charge_may_be_scoped_by_grant_alone():
    assert claim(ClaimType.DUPLICATE_CHARGE, grant_id=GRANT).purchase_id is None


# --- result contract ---------------------------------------------------------------------------


def test_unverifiable_result_must_carry_a_reason():
    with pytest.raises(ValidationError, match="reason code"):
        VerificationResult(
            claim=claim(ClaimType.CHARGED_NOT_DELIVERED, "p-01"),
            outcome=Outcome.UNVERIFIABLE,
            reason=None,
            evidence_used=(),
        )


def test_verify_is_pure_and_results_are_frozen(evidence):
    items = [evidence("purchase_settled_delivered")]
    c = claim(ClaimType.CHARGED_NOT_DELIVERED, "p-01")
    first, second = verify(c, items), verify(c, items)
    assert first == second
    with pytest.raises(ValidationError):
        first.outcome = Outcome.CONFIRMED


# --- in-flight states --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("fixture", "purchase_id", "state"),
    [
        ("purchase_reserved", "p-04", PaymentState.RESERVED),
        ("purchase_executing", "p-05", PaymentState.EXECUTING),
        ("purchase_unknown", "p-06", PaymentState.UNKNOWN),
    ],
)
def test_in_flight_purchase_is_unverifiable(evidence, fixture, purchase_id, state):
    result = verify(claim(ClaimType.CHARGED_NOT_DELIVERED, purchase_id), [evidence(fixture)])
    unverifiable(result, ReasonCode.IN_FLIGHT_STATE)
    assert result.details.payment_state is state
    assert [ref.purchase_id for ref in result.evidence_used] == [purchase_id]


# --- charged_not_delivered ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("fixture", "purchase_id", "delivery"),
    [
        ("purchase_settled_delivery_failed", "p-02", DeliveryState.FAILED),
        ("purchase_settled_not_requested", "p-03", DeliveryState.NOT_REQUESTED),
    ],
)
def test_charged_not_delivered_confirmed_when_settled_without_delivery(
    evidence, fixture, purchase_id, delivery
):
    result = verify(claim(ClaimType.CHARGED_NOT_DELIVERED, purchase_id), [evidence(fixture)])
    assert result.outcome is Outcome.CONFIRMED
    assert result.reason is None
    assert result.details == Details(payment_state=PaymentState.SETTLED, delivery_state=delivery)


def test_charged_not_delivered_contradicted_when_delivered(evidence):
    result = verify(
        claim(ClaimType.CHARGED_NOT_DELIVERED, "p-01"), [evidence("purchase_settled_delivered")]
    )
    assert result.outcome is Outcome.CONTRADICTED
    assert result.details.delivery_state is DeliveryState.DELIVERED


@pytest.mark.parametrize(
    ("fixture", "purchase_id"),
    [("purchase_failed", "p-09"), ("purchase_denied", "p-07"), ("purchase_not_required", "p-08")],
)
def test_charged_not_delivered_contradicted_when_nothing_was_charged(
    evidence, fixture, purchase_id
):
    # Not in the brief: a terminal non-settled purchase took no money, so "charged" is false.
    result = verify(claim(ClaimType.CHARGED_NOT_DELIVERED, purchase_id), [evidence(fixture)])
    assert result.outcome is Outcome.CONTRADICTED
    assert result.details.payment_state is not PaymentState.SETTLED


# --- purchase_not_found ------------------------------------------------------------------------


def test_missing_purchase_is_unverifiable(evidence):
    result = verify(
        claim(ClaimType.CHARGED_NOT_DELIVERED, "p-99"), [evidence("purchase_settled_delivered")]
    )
    unverifiable(result, ReasonCode.PURCHASE_NOT_FOUND)
    assert result.evidence_used == ()


def test_no_evidence_at_all_is_purchase_not_found():
    result = verify(claim(ClaimType.CHARGED_NOT_DELIVERED, "p-01"), [])
    unverifiable(result, ReasonCode.PURCHASE_NOT_FOUND)


def test_purchase_under_a_different_grant_than_claimed_is_not_found(evidence):
    result = verify(
        claim(ClaimType.CHARGED_NOT_DELIVERED, "p-01", grant_id="grant-other"),
        [evidence("purchase_settled_delivered")],
    )
    unverifiable(result, ReasonCode.PURCHASE_NOT_FOUND)
    assert result.evidence_used[0].grant_id == GRANT


# --- staleness ---------------------------------------------------------------------------------


def test_stale_in_flight_evidence_is_stale_not_in_flight(evidence):
    result = verify(
        claim(ClaimType.CHARGED_NOT_DELIVERED, "p-10"), [evidence("purchase_stale_in_flight")]
    )
    unverifiable(result, ReasonCode.STALE)
    assert result.evidence_used[0].captured_at < CREATED_AT


def test_stale_terminal_evidence_is_still_usable(evidence):
    result = verify(
        claim(ClaimType.CHARGED_NOT_DELIVERED, "p-11"), [evidence("purchase_stale_terminal")]
    )
    assert result.outcome is Outcome.CONTRADICTED


# --- multiple items for one purchase ---------------------------------------------------------


def test_equal_capture_time_with_different_states_is_a_conflict(evidence):
    items = [evidence("conflict_executing"), evidence("conflict_settled")]
    result = verify(claim(ClaimType.CHARGED_NOT_DELIVERED, "p-12"), items)
    unverifiable(result, ReasonCode.SOURCES_CONFLICT)
    assert result.details.conflicting_states == ("executing/not_requested", "settled/delivered")
    assert len(result.evidence_used) == 2


def test_newest_capture_wins(evidence):
    items = [evidence("supersede_older"), evidence("supersede_newer")]
    result = verify(claim(ClaimType.CHARGED_NOT_DELIVERED, "p-13"), items)
    assert result.outcome is Outcome.CONTRADICTED  # the newer export says delivered
    assert [ref.captured_at for ref in result.evidence_used] == [1_200]


def test_identical_duplicate_items_corroborate_rather_than_conflict(evidence):
    item = evidence("purchase_settled_delivered")
    result = verify(claim(ClaimType.CHARGED_NOT_DELIVERED, "p-01"), [item, item])
    assert result.outcome is Outcome.CONTRADICTED
    assert len(result.evidence_used) == 2


# --- duplicate_charge --------------------------------------------------------------------------


def test_duplicate_confirmed_from_two_purchase_exports(evidence):
    items = [evidence("duplicate_first"), evidence("duplicate_second")]
    result = verify(claim(ClaimType.DUPLICATE_CHARGE, "p-14"), items)
    assert result.outcome is Outcome.CONFIRMED
    assert result.details.settled_duplicate_ids == ("p-14", "p-15")


def test_duplicate_confirmed_by_grant_id_alone(evidence):
    items = [evidence("duplicate_first"), evidence("duplicate_second")]
    result = verify(claim(ClaimType.DUPLICATE_CHARGE, grant_id=GRANT), items)
    assert result.outcome is Outcome.CONFIRMED


def test_duplicate_confirmed_from_bundle(evidence):
    result = verify(
        claim(ClaimType.DUPLICATE_CHARGE, "p-14"), [evidence("grant_complete_with_duplicates")]
    )
    assert result.outcome is Outcome.CONFIRMED
    assert result.details.settled_duplicate_ids == ("p-14", "p-15")


def test_duplicate_purchase_scope_only_is_incomplete_scope(evidence):
    result = verify(claim(ClaimType.DUPLICATE_CHARGE, "p-14"), [evidence("duplicate_first")])
    unverifiable(result, ReasonCode.INCOMPLETE_SCOPE)


def test_duplicate_contradicted_only_by_complete_consistent_bundle(evidence):
    result = verify(claim(ClaimType.DUPLICATE_CHARGE, "p-20"), [evidence("grant_complete_single")])
    assert result.outcome is Outcome.CONTRADICTED
    assert result.details.settled_duplicate_ids == ("p-20",)
    assert result.evidence_used[0].kind == "grant"
    assert result.evidence_used[0].grant_id == "grant-single"


def test_duplicate_incomplete_bundle_missing_export(evidence):
    result = verify(
        claim(ClaimType.DUPLICATE_CHARGE, "p-30"), [evidence("grant_incomplete_missing")]
    )
    unverifiable(result, ReasonCode.INCOMPLETE_SCOPE)
    assert result.details.missing_purchase_ids == ("p-32",)


def test_duplicate_incomplete_bundle_unlisted_export(evidence):
    result = verify(
        claim(ClaimType.DUPLICATE_CHARGE, "p-40"), [evidence("grant_incomplete_unlisted")]
    )
    unverifiable(result, ReasonCode.INCOMPLETE_SCOPE)
    assert result.details.unlisted_purchase_ids == ("p-41",)


def test_duplicate_skewed_bundle_is_inconsistent(evidence):
    result = verify(claim(ClaimType.DUPLICATE_CHARGE, "p-50"), [evidence("grant_skewed")])
    unverifiable(result, ReasonCode.INCONSISTENT_BUNDLE)
    assert (result.details.skew_seconds, result.details.max_skew_seconds) == (400, 300)


def test_skew_threshold_is_configurable(evidence):
    result = verify(
        claim(ClaimType.DUPLICATE_CHARGE, "p-50"),
        [evidence("grant_skewed")],
        max_bundle_skew_seconds=500,
    )
    assert result.outcome is Outcome.CONTRADICTED


def test_duplicate_bundle_with_foreign_export_is_inconsistent(evidence):
    result = verify(claim(ClaimType.DUPLICATE_CHARGE, "p-60"), [evidence("grant_foreign_export")])
    unverifiable(result, ReasonCode.INCONSISTENT_BUNDLE)
    assert result.details.foreign_purchase_ids == ("p-61",)


def test_duplicate_not_contradicted_while_a_sibling_is_in_flight(evidence):
    result = verify(claim(ClaimType.DUPLICATE_CHARGE, "p-70"), [evidence("grant_with_in_flight")])
    unverifiable(result, ReasonCode.IN_FLIGHT_STATE)
    assert result.details.in_flight_purchase_ids == ("p-71",)


def test_duplicate_stale_in_flight_sibling_is_stale(evidence):
    result = verify(claim(ClaimType.DUPLICATE_CHARGE, "p-70"), [evidence("grant_stale_in_flight")])
    unverifiable(result, ReasonCode.STALE)


def test_duplicate_anchor_purchase_in_flight(evidence):
    result = verify(claim(ClaimType.DUPLICATE_CHARGE, "p-71"), [evidence("grant_with_in_flight")])
    unverifiable(result, ReasonCode.IN_FLIGHT_STATE)


def test_duplicate_conflicting_sibling_is_sources_conflict(evidence):
    items = [evidence("conflict_executing"), evidence("conflict_settled")]
    result = verify(claim(ClaimType.DUPLICATE_CHARGE, grant_id=GRANT), items)
    unverifiable(result, ReasonCode.SOURCES_CONFLICT)


def test_duplicate_anchor_not_found(evidence):
    result = verify(claim(ClaimType.DUPLICATE_CHARGE, "p-99"), [evidence("grant_complete_single")])
    unverifiable(result, ReasonCode.PURCHASE_NOT_FOUND)


def test_duplicate_by_grant_with_no_evidence_is_incomplete_scope():
    result = verify(claim(ClaimType.DUPLICATE_CHARGE, grant_id=GRANT), [])
    unverifiable(result, ReasonCode.INCOMPLETE_SCOPE)


# --- unauthorized_purchase ---------------------------------------------------------------------


def test_unauthorized_existing_settled_purchase(evidence):
    result = verify(
        claim(ClaimType.UNAUTHORIZED_PURCHASE, "p-01"), [evidence("purchase_settled_delivered")]
    )
    assert result.outcome is Outcome.CONFIRMED
    assert result.reason is ReasonCode.REQUIRES_HUMAN_REVIEW
    assert result.details.settled is True


def test_unauthorized_existing_denied_purchase_flags_not_settled(evidence):
    result = verify(claim(ClaimType.UNAUTHORIZED_PURCHASE, "p-07"), [evidence("purchase_denied")])
    assert result.outcome is Outcome.CONFIRMED
    assert result.details.settled is False


def test_unauthorized_in_flight_purchase_still_exists(evidence):
    result = verify(
        claim(ClaimType.UNAUTHORIZED_PURCHASE, "p-05"), [evidence("purchase_executing")]
    )
    assert result.outcome is Outcome.CONFIRMED
    assert result.details.settled is False


def test_unauthorized_missing_purchase(evidence):
    result = verify(claim(ClaimType.UNAUTHORIZED_PURCHASE, "p-99"), [evidence("purchase_denied")])
    unverifiable(result, ReasonCode.PURCHASE_NOT_FOUND)


def test_unauthorized_conflicting_sources_do_not_pick_a_settled_flag(evidence):
    items = [evidence("conflict_executing"), evidence("conflict_settled")]
    result = verify(claim(ClaimType.UNAUTHORIZED_PURCHASE, "p-12"), items)
    assert result.outcome is Outcome.CONFIRMED
    assert result.reason is ReasonCode.REQUIRES_HUMAN_REVIEW
    assert result.details.settled is None
    assert result.details.conflicting_states


@pytest.mark.parametrize(
    "fixture",
    [
        "purchase_settled_delivered", "purchase_settled_delivery_failed",
        "purchase_settled_not_requested", "purchase_reserved", "purchase_executing",
        "purchase_unknown", "purchase_denied", "purchase_not_required", "purchase_failed",
        "purchase_stale_in_flight", "purchase_stale_terminal",
    ],
)  # fmt: skip
def test_unauthorized_is_never_contradicted(evidence, fixture):
    item = evidence(fixture)
    result = verify(claim(ClaimType.UNAUTHORIZED_PURCHASE, item.purchase_id), [item])
    assert result.outcome is not Outcome.CONTRADICTED
    assert result.reason is ReasonCode.REQUIRES_HUMAN_REVIEW


# --- charged_but_denied ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("fixture", "purchase_id"),
    [("purchase_denied", "p-07"), ("purchase_not_required", "p-08")],
)
def test_charged_but_denied_contradicted_when_denied_or_not_required(
    evidence, fixture, purchase_id
):
    result = verify(claim(ClaimType.CHARGED_BUT_DENIED, purchase_id), [evidence(fixture)])
    assert result.outcome is Outcome.CONTRADICTED


def test_charged_but_denied_unknown_is_unverifiable(evidence):
    result = verify(claim(ClaimType.CHARGED_BUT_DENIED, "p-06"), [evidence("purchase_unknown")])
    unverifiable(result, ReasonCode.IN_FLIGHT_STATE)


def test_charged_but_denied_settled_is_confirmed(evidence):
    # Not in the brief: a settled purchase means the charge the ticket reports is real.
    result = verify(
        claim(ClaimType.CHARGED_BUT_DENIED, "p-01"), [evidence("purchase_settled_delivered")]
    )
    assert result.outcome is Outcome.CONFIRMED


def test_charged_but_denied_failed_is_contradicted(evidence):
    # Not in the brief: a failed payment took no money.
    result = verify(claim(ClaimType.CHARGED_BUT_DENIED, "p-09"), [evidence("purchase_failed")])
    assert result.outcome is Outcome.CONTRADICTED
