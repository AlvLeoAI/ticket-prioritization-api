"""Deterministic verification of a claim against evidence.

`verify()` is a pure function: same claim and evidence in, same result out. It consults no
clock, no network and no model. Its output describes what the evidence supports; it decides
nothing. In particular a `contradicted` outcome is a statement about evidence, not an
instruction to close a ticket.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Literal, Optional, Sequence, Tuple

from pydantic import model_validator

from triage.claims import Claim, ClaimType
from triage.config import MAX_BUNDLE_SKEW_SECONDS
from triage.evidence import EvidenceItem, GrantEvidence, PurchaseEvidence
from triage.payments_lab import (
    IN_FLIGHT_PAYMENT_STATES,
    AuditExport,
    DeliveryState,
    Frozen,
    Identifier,
    PaymentState,
    Timestamp,
)


class Outcome(str, Enum):
    CONFIRMED = "confirmed"
    CONTRADICTED = "contradicted"
    UNVERIFIABLE = "unverifiable"


class ReasonCode(str, Enum):
    STALE = "stale"
    PURCHASE_NOT_FOUND = "purchase_not_found"
    INCOMPLETE_SCOPE = "incomplete_scope"
    IN_FLIGHT_STATE = "in_flight_state"
    SOURCES_CONFLICT = "sources_conflict"
    INCONSISTENT_BUNDLE = "inconsistent_bundle"
    REQUIRES_HUMAN_REVIEW = "requires_human_review"


class EvidenceRef(Frozen):
    """Which envelope a result rests on. Enough to find it again, no payload."""

    kind: Literal["purchase", "grant"]
    source: str
    source_version: str
    captured_at: Timestamp
    purchase_id: Optional[Identifier] = None
    grant_id: Optional[Identifier] = None


class Details(Frozen):
    """Facts the outcome rests on. Every field is optional; only relevant ones are filled."""

    payment_state: Optional[PaymentState] = None
    delivery_state: Optional[DeliveryState] = None
    # unauthorized_purchase: whether the purchase is settled; None when sources disagree.
    settled: Optional[bool] = None
    settled_duplicate_ids: Tuple[Identifier, ...] = ()
    missing_purchase_ids: Tuple[Identifier, ...] = ()
    duplicated_purchase_ids: Tuple[Identifier, ...] = ()
    unlisted_purchase_ids: Tuple[Identifier, ...] = ()
    foreign_purchase_ids: Tuple[Identifier, ...] = ()
    skew_seconds: Optional[int] = None
    max_skew_seconds: Optional[int] = None
    # sources_conflict: the disagreeing "payment_state/delivery_state" pairs.
    conflicting_states: Tuple[str, ...] = ()
    in_flight_purchase_ids: Tuple[Identifier, ...] = ()


class VerificationResult(Frozen):
    claim: Claim
    outcome: Outcome
    reason: Optional[ReasonCode]
    evidence_used: Tuple[EvidenceRef, ...]
    details: Details = Details()

    @model_validator(mode="after")
    def _unverifiable_says_why(self):
        if self.outcome is Outcome.UNVERIFIABLE and self.reason is None:
            raise ValueError("an unverifiable result must carry a reason code")
        return self


# --- evidence resolution ------------------------------------------------------------------


@dataclass(frozen=True)
class _Candidate:
    envelope: PurchaseEvidence
    ref: EvidenceRef


@dataclass(frozen=True)
class _Resolved:
    """The evidence that wins for one purchase, or the conflict that stops it from winning."""

    purchase_id: str
    export: Optional[AuditExport]
    captured_at: int
    refs: Tuple[EvidenceRef, ...]
    conflicting_states: Tuple[str, ...] = ()

    @property
    def conflicted(self) -> bool:
        return bool(self.conflicting_states)


def _purchase_ref(envelope: PurchaseEvidence) -> EvidenceRef:
    return EvidenceRef(
        kind="purchase",
        source=envelope.source,
        source_version=envelope.source_version,
        captured_at=envelope.captured_at,
        purchase_id=envelope.purchase_id,
        grant_id=envelope.payload.grant_id,
    )


def _grant_ref(bundle: GrantEvidence) -> EvidenceRef:
    return EvidenceRef(
        kind="grant",
        source=bundle.source,
        source_version=bundle.source_version,
        captured_at=bundle.manifest_captured_at,
        grant_id=bundle.grant_id,
    )


def _index(evidence_items: Sequence[EvidenceItem]) -> Dict[str, List[_Candidate]]:
    """Every purchase export, whether supplied on its own or inside a grant bundle."""
    index: Dict[str, List[_Candidate]] = {}
    for item in evidence_items:
        envelopes = (item,) if isinstance(item, PurchaseEvidence) else item.exports
        for envelope in envelopes:
            index.setdefault(envelope.purchase_id, []).append(
                _Candidate(envelope, _purchase_ref(envelope))
            )
    return index


def _state_label(export: AuditExport) -> str:
    return f"{export.payment_state.value}/{export.delivery_state.value}"


def _resolve(purchase_id: str, candidates: List[_Candidate]) -> _Resolved:
    """Newest `captured_at` wins. Equal `captured_at` with different states is a conflict."""
    newest = max(candidate.envelope.captured_at for candidate in candidates)
    top = [candidate for candidate in candidates if candidate.envelope.captured_at == newest]
    states = sorted({_state_label(candidate.envelope.payload) for candidate in top})
    refs = tuple(candidate.ref for candidate in top)
    if len(states) > 1:
        return _Resolved(purchase_id, None, newest, refs, conflicting_states=tuple(states))
    return _Resolved(purchase_id, top[0].envelope.payload, newest, refs)


# --- shared checks -------------------------------------------------------------------------


def _unverifiable(
    claim: Claim,
    reason: ReasonCode,
    refs: Sequence[EvidenceRef] = (),
    details: Optional[Details] = None,
) -> VerificationResult:
    return VerificationResult(
        claim=claim,
        outcome=Outcome.UNVERIFIABLE,
        reason=reason,
        evidence_used=tuple(refs),
        details=details or Details(),
    )


def _gate(claim: Claim, resolved: Optional[_Resolved]) -> Optional[VerificationResult]:
    """Checks every purchase-scoped rule needs before it can read a state.

    Order: not found, conflict, claimed grant mismatch, then staleness before in-flight (a
    stale in-flight export is both; `stale` is the more useful answer because re-pulling the
    evidence may resolve it).
    """
    if resolved is None:
        return _unverifiable(claim, ReasonCode.PURCHASE_NOT_FOUND)
    if resolved.conflicted:
        return _unverifiable(
            claim,
            ReasonCode.SOURCES_CONFLICT,
            resolved.refs,
            Details(conflicting_states=resolved.conflicting_states),
        )
    export = resolved.export
    assert export is not None
    if claim.grant_id is not None and export.grant_id != claim.grant_id:
        # The purchase exists, but not under the grant the claim names.
        return _unverifiable(claim, ReasonCode.PURCHASE_NOT_FOUND, resolved.refs)
    if export.payment_state in IN_FLIGHT_PAYMENT_STATES:
        details = Details(payment_state=export.payment_state, delivery_state=export.delivery_state)
        if resolved.captured_at < claim.created_at:
            return _unverifiable(claim, ReasonCode.STALE, resolved.refs, details)
        return _unverifiable(claim, ReasonCode.IN_FLIGHT_STATE, resolved.refs, details)
    return None


def _state_details(export: AuditExport) -> Details:
    return Details(payment_state=export.payment_state, delivery_state=export.delivery_state)


# --- rules -----------------------------------------------------------------------------------


def _charged_not_delivered(claim: Claim, resolved: Optional[_Resolved]) -> VerificationResult:
    blocked = _gate(claim, resolved)
    if blocked:
        return blocked
    assert resolved is not None and resolved.export is not None
    export = resolved.export
    if export.is_settled:
        outcome = (
            Outcome.CONTRADICTED
            if export.delivery_state is DeliveryState.DELIVERED
            else Outcome.CONFIRMED  # delivery failed or never requested
        )
    else:
        # denied / failed / not_required: the ledger shows no charge was taken.
        outcome = Outcome.CONTRADICTED
    return VerificationResult(
        claim=claim,
        outcome=outcome,
        reason=None,
        evidence_used=resolved.refs,
        details=_state_details(export),
    )


def _charged_but_denied(claim: Claim, resolved: Optional[_Resolved]) -> VerificationResult:
    blocked = _gate(claim, resolved)  # `unknown` is in-flight: unverifiable, in_flight_state
    if blocked:
        return blocked
    assert resolved is not None and resolved.export is not None
    export = resolved.export
    # settled: the charge is real. denied / not_required / failed: nothing was charged.
    outcome = Outcome.CONFIRMED if export.is_settled else Outcome.CONTRADICTED
    return VerificationResult(
        claim=claim,
        outcome=outcome,
        reason=None,
        evidence_used=resolved.refs,
        details=_state_details(export),
    )


def _unauthorized_purchase(claim: Claim, resolved: Optional[_Resolved]) -> VerificationResult:
    """Never contradicted: evidence can show a purchase exists, not that it was authorized."""
    if resolved is None:
        return _unverifiable(claim, ReasonCode.PURCHASE_NOT_FOUND)
    if resolved.conflicted:
        details = Details(settled=None, conflicting_states=resolved.conflicting_states)
    else:
        assert resolved.export is not None
        details = Details(
            payment_state=resolved.export.payment_state,
            delivery_state=resolved.export.delivery_state,
            settled=resolved.export.is_settled,
        )
    return VerificationResult(
        claim=claim,
        outcome=Outcome.CONFIRMED,
        reason=ReasonCode.REQUIRES_HUMAN_REVIEW,
        evidence_used=resolved.refs,
        details=details,
    )


def _pick_bundle(
    claim: Claim, grant_id: str, evidence_items: Sequence[EvidenceItem]
) -> Tuple[Optional[GrantEvidence], Optional[VerificationResult]]:
    bundles = [
        item
        for item in evidence_items
        if isinstance(item, GrantEvidence) and item.grant_id == grant_id
    ]
    if not bundles:
        return None, None
    newest = max(bundle.manifest_captured_at for bundle in bundles)
    top = [bundle for bundle in bundles if bundle.manifest_captured_at == newest]
    if len({bundle.manifest for bundle in top}) > 1:
        refs = [_grant_ref(bundle) for bundle in top]
        return None, _unverifiable(claim, ReasonCode.SOURCES_CONFLICT, refs)
    return top[0], None


def _duplicate_charge(
    claim: Claim,
    index: Dict[str, List[_Candidate]],
    evidence_items: Sequence[EvidenceItem],
    max_skew_seconds: int,
) -> VerificationResult:
    anchor_refs: Tuple[EvidenceRef, ...] = ()
    group: Optional[Tuple[str, str]] = None  # (grant_id, request_fingerprint)
    if claim.purchase_id is not None:
        candidates = index.get(claim.purchase_id)
        resolved = _resolve(claim.purchase_id, candidates) if candidates else None
        blocked = _gate(claim, resolved)
        if blocked:
            return blocked
        assert resolved is not None and resolved.export is not None
        grant_id = resolved.export.grant_id
        group = (grant_id, resolved.export.request_fingerprint)
        anchor_refs = resolved.refs
    else:
        assert claim.grant_id is not None
        grant_id = claim.grant_id

    # Resolve every purchase we know about under this grant, newest capture first.
    members: List[_Resolved] = []
    for purchase_id, candidates in index.items():
        resolved = _resolve(purchase_id, candidates)
        if resolved.conflicted:
            if any(c.envelope.payload.grant_id == grant_id for c in candidates):
                members.append(resolved)
            continue
        assert resolved.export is not None
        if resolved.export.grant_id == grant_id:
            members.append(resolved)

    def in_group(member: _Resolved) -> bool:
        if group is None or member.export is None:
            return True
        return member.export.request_fingerprint == group[1]

    relevant = [member for member in members if in_group(member)]
    conflicted = [member for member in relevant if member.conflicted]
    if conflicted:
        refs = [ref for member in conflicted for ref in member.refs]
        states = tuple(sorted({s for member in conflicted for s in member.conflicting_states}))
        return _unverifiable(
            claim, ReasonCode.SOURCES_CONFLICT, refs, Details(conflicting_states=states)
        )

    # Confirmation needs no bundle: two settled purchases with one fingerprint are enough.
    by_fingerprint: Dict[str, List[_Resolved]] = {}
    for member in relevant:
        assert member.export is not None
        if member.export.is_settled:
            by_fingerprint.setdefault(member.export.request_fingerprint, []).append(member)
    duplicates = [members_ for members_ in by_fingerprint.values() if len(members_) >= 2]
    if duplicates:
        settled_ids = tuple(sorted(m.purchase_id for members_ in duplicates for m in members_))
        refs = tuple(ref for members_ in duplicates for m in members_ for ref in m.refs)
        return VerificationResult(
            claim=claim,
            outcome=Outcome.CONFIRMED,
            reason=None,
            evidence_used=refs,
            details=Details(settled_duplicate_ids=settled_ids),
        )

    # Contradiction needs the whole grant: a complete, consistent bundle.
    bundle, blocked = _pick_bundle(claim, grant_id, evidence_items)
    if blocked:
        return blocked
    if bundle is None:
        return _unverifiable(claim, ReasonCode.INCOMPLETE_SCOPE, anchor_refs)
    bundle_ref = _grant_ref(bundle)
    if not bundle.is_complete:
        return _unverifiable(
            claim,
            ReasonCode.INCOMPLETE_SCOPE,
            (bundle_ref,),
            Details(
                missing_purchase_ids=bundle.missing_purchase_ids,
                duplicated_purchase_ids=bundle.duplicated_purchase_ids,
                unlisted_purchase_ids=bundle.unlisted_purchase_ids,
            ),
        )
    if not bundle.is_consistent(max_skew_seconds):
        return _unverifiable(
            claim,
            ReasonCode.INCONSISTENT_BUNDLE,
            (bundle_ref,),
            Details(
                foreign_purchase_ids=bundle.foreign_purchase_ids,
                skew_seconds=bundle.skew_seconds,
                max_skew_seconds=max_skew_seconds,
            ),
        )

    # A purchase that may still settle could become the second charge.
    in_flight = [
        member
        for member in relevant
        if member.export is not None and member.export.payment_state in IN_FLIGHT_PAYMENT_STATES
    ]
    if in_flight:
        refs = (bundle_ref,) + tuple(ref for member in in_flight for ref in member.refs)
        ids = tuple(sorted(member.purchase_id for member in in_flight))
        stale = any(member.captured_at < claim.created_at for member in in_flight)
        reason = ReasonCode.STALE if stale else ReasonCode.IN_FLIGHT_STATE
        return _unverifiable(claim, reason, refs, Details(in_flight_purchase_ids=ids))

    settled_ids = tuple(
        sorted(m.purchase_id for members_ in by_fingerprint.values() for m in members_)
    )
    refs = (bundle_ref,) + tuple(ref for member in relevant for ref in member.refs)
    return VerificationResult(
        claim=claim,
        outcome=Outcome.CONTRADICTED,
        reason=None,
        evidence_used=refs,
        details=Details(settled_duplicate_ids=settled_ids),
    )


# --- entry point -----------------------------------------------------------------------------


def verify(
    claim: Claim,
    evidence_items: Sequence[EvidenceItem],
    *,
    max_bundle_skew_seconds: int = MAX_BUNDLE_SKEW_SECONDS,
) -> VerificationResult:
    """Verify one claim against the given evidence. Pure; raises only on invalid input types."""
    index = _index(evidence_items)

    if claim.claim_type is ClaimType.DUPLICATE_CHARGE:
        return _duplicate_charge(claim, index, evidence_items, max_bundle_skew_seconds)

    assert claim.purchase_id is not None  # enforced by Claim for purchase-scoped claims
    candidates = index.get(claim.purchase_id)
    resolved = _resolve(claim.purchase_id, candidates) if candidates else None

    if claim.claim_type is ClaimType.CHARGED_NOT_DELIVERED:
        return _charged_not_delivered(claim, resolved)
    if claim.claim_type is ClaimType.CHARGED_BUT_DENIED:
        return _charged_but_denied(claim, resolved)
    return _unauthorized_purchase(claim, resolved)
