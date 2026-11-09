"""Generate the synthetic evidence fixtures in this directory.

All data is invented. Shapes follow `Ledger.export_audit()` at the commit pinned in
`triage/source.py`. Run from the repository root:

    python tests/fixtures/evidence/generate.py

`tests/test_triage_models.py` checks that the committed JSON matches this script's output,
so edit the script, regenerate, and commit both.
"""

import hashlib
import json
import os
import sys
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))))

from triage.source import EXPORT_AUDIT_SOURCE, PAYMENTS_LAB_COMMIT  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))

# Simulation clock (integer seconds). Tickets in the tests are created at TICKET_CREATED_AT;
# "fresh" evidence is captured after it, "stale" evidence before.
TICKET_CREATED_AT = 1_000
FRESH = 1_100
STALE = 900

GRANT = "grant-research-01"


def fingerprint(label: str) -> str:
    """A stand-in for the ledger's sha256 request fingerprint."""
    return hashlib.sha256(label.encode()).hexdigest()


FP_A = fingerprint("fp-a")
FP_B = fingerprint("fp-b")
FP_C = fingerprint("fp-c")
FP_D = fingerprint("fp-d")
FP_E = fingerprint("fp-e")
FP_F = fingerprint("fp-f")


def events(purchase_id: str, payment_state: str, delivery_state: str, start: int) -> List[Dict]:
    """The event trail the ledger would have written to reach these states."""
    trail: List[Dict[str, Any]] = [
        ("task_created", {"task_id": f"task-{purchase_id}"}),
        (
            "authorization_decision",
            {
                "approved": payment_state != "denied",
                "grant_id": GRANT,
                "policy_version": "phase1-v1",
                "fingerprint": fingerprint(purchase_id),
            },
        ),
    ]
    if payment_state == "denied":
        trail.append(("denied", {"amount": 250000, "reason": "insufficient_budget"}))
    elif payment_state == "not_required":
        trail.append(("not_required", {"amount": 0, "reason": None}))
    else:
        trail.append(("reserved", {"amount": 250000, "reason": None}))
        if payment_state != "reserved":
            trail.append(("dispatch_recorded", {}))
        if payment_state in ("settled", "failed", "unknown"):
            trail.append((payment_state, {"reason": None if payment_state == "settled" else "x"}))
    if delivery_state == "delivered":
        trail.append(("delivered", {"reason": None}))
    elif delivery_state == "failed":
        trail.append(("delivery_failed", {"reason": "provider_timeout"}))
    return [
        {
            "sequence": index,
            "purchase_id": purchase_id,
            "event_type": event_type,
            "data": data,
            "recorded_at": start + index,
        }
        for index, (event_type, data) in enumerate(trail, start=1)
    ]


def export(
    purchase_id: str,
    payment_state: str,
    delivery_state: str = "not_requested",
    *,
    grant_id: str = GRANT,
    request_fingerprint: Optional[str] = None,
    amount: int = 250000,
) -> Dict[str, Any]:
    return {
        "mode": "simulated",
        "purchase_id": purchase_id,
        "request_fingerprint": request_fingerprint or fingerprint(purchase_id),
        "grant_id": grant_id,
        "policy_version": "phase1-v1",
        "service_id": "report-standard",
        "merchant_id": "sim-merchant-research",
        "network": "simulation:local",
        "asset": "SIM-USDC",
        "recipient": "sim-merchant-research",
        "amount": 0 if payment_state == "not_required" else amount,
        "payment_state": payment_state,
        "delivery_state": delivery_state,
        "events": events(purchase_id, payment_state, delivery_state, start=100),
    }


def purchase(captured_at: int, payload: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "kind": "purchase",
        "source": EXPORT_AUDIT_SOURCE,
        "source_version": PAYMENTS_LAB_COMMIT,
        "captured_at": captured_at,
        "payload": payload,
    }


def grant(
    grant_id: str, manifest: List[str], exports: List[Dict[str, Any]], manifest_captured_at: int
) -> Dict[str, Any]:
    return {
        "kind": "grant",
        "source": EXPORT_AUDIT_SOURCE,
        "source_version": PAYMENTS_LAB_COMMIT,
        "grant_id": grant_id,
        "manifest_captured_at": manifest_captured_at,
        "manifest": manifest,
        "exports": exports,
    }


def build_all() -> Dict[str, Dict[str, Any]]:
    fixtures: Dict[str, Dict[str, Any]] = {}

    # One purchase per payment/delivery state, captured after the ticket was created.
    fixtures["purchase_settled_delivered"] = purchase(FRESH, export("p-01", "settled", "delivered"))
    fixtures["purchase_settled_delivery_failed"] = purchase(
        FRESH, export("p-02", "settled", "failed")
    )
    fixtures["purchase_settled_not_requested"] = purchase(FRESH, export("p-03", "settled"))
    fixtures["purchase_reserved"] = purchase(FRESH, export("p-04", "reserved"))
    fixtures["purchase_executing"] = purchase(FRESH, export("p-05", "executing"))
    fixtures["purchase_unknown"] = purchase(FRESH, export("p-06", "unknown"))
    fixtures["purchase_denied"] = purchase(FRESH, export("p-07", "denied"))
    fixtures["purchase_not_required"] = purchase(FRESH, export("p-08", "not_required", "delivered"))
    fixtures["purchase_failed"] = purchase(FRESH, export("p-09", "failed"))

    # Staleness: captured before the ticket, once in flight and once terminal.
    fixtures["purchase_stale_in_flight"] = purchase(STALE, export("p-10", "executing"))
    fixtures["purchase_stale_terminal"] = purchase(STALE, export("p-11", "settled", "delivered"))

    # Same purchase, same capture time, different states: a conflict nobody may pick from.
    fixtures["conflict_executing"] = purchase(FRESH, export("p-12", "executing"))
    fixtures["conflict_settled"] = purchase(FRESH, export("p-12", "settled", "delivered"))

    # Same purchase captured twice: the newer capture wins.
    fixtures["supersede_older"] = purchase(1_050, export("p-13", "executing"))
    fixtures["supersede_newer"] = purchase(1_200, export("p-13", "settled", "delivered"))

    # Two settled purchases under one grant with one fingerprint: a duplicate charge, visible
    # from purchase-scope evidence alone.
    dup_1 = export("p-14", "settled", "delivered", request_fingerprint=FP_A)
    dup_2 = export("p-15", "settled", "delivered", request_fingerprint=FP_A)
    other = export("p-16", "settled", "delivered", request_fingerprint=FP_B)
    fixtures["duplicate_first"] = purchase(FRESH, dup_1)
    fixtures["duplicate_second"] = purchase(FRESH, dup_2)
    fixtures["grant_complete_with_duplicates"] = grant(
        GRANT,
        ["p-14", "p-15", "p-16"],
        [purchase(FRESH, dup_1), purchase(FRESH + 20, dup_2), purchase(FRESH + 40, other)],
        manifest_captured_at=FRESH,
    )

    # A complete, consistent bundle with at most one settled purchase per fingerprint: the
    # only evidence that can contradict a duplicate-charge claim.
    fixtures["grant_complete_single"] = grant(
        "grant-single",
        ["p-20", "p-21", "p-22"],
        [
            purchase(FRESH, export("p-20", "settled", "delivered", grant_id="grant-single",
                                   request_fingerprint=FP_C)),
            purchase(FRESH + 10, export("p-21", "failed", grant_id="grant-single",
                                        request_fingerprint=FP_C)),
            purchase(FRESH + 20, export("p-22", "settled", "delivered", grant_id="grant-single",
                                        request_fingerprint=FP_D)),
        ],
        manifest_captured_at=FRESH,
    )

    # Incomplete bundles: a manifest entry with no export, and an export the manifest omits.
    fixtures["grant_incomplete_missing"] = grant(
        "grant-missing",
        ["p-30", "p-31", "p-32"],
        [
            purchase(FRESH, export("p-30", "settled", "delivered", grant_id="grant-missing")),
            purchase(FRESH, export("p-31", "failed", grant_id="grant-missing")),
        ],
        manifest_captured_at=FRESH,
    )
    fixtures["grant_incomplete_unlisted"] = grant(
        "grant-unlisted",
        ["p-40"],
        [
            purchase(FRESH, export("p-40", "settled", "delivered", grant_id="grant-unlisted")),
            purchase(FRESH, export("p-41", "settled", "delivered", grant_id="grant-unlisted")),
        ],
        manifest_captured_at=FRESH,
    )

    # Inconsistent bundles: captures too far apart, and an export from another grant.
    fixtures["grant_skewed"] = grant(
        "grant-skewed",
        ["p-50", "p-51"],
        [
            purchase(FRESH, export("p-50", "settled", "delivered", grant_id="grant-skewed",
                                   request_fingerprint=FP_E)),
            purchase(FRESH + 400, export("p-51", "failed", grant_id="grant-skewed",
                                         request_fingerprint=FP_E)),
        ],
        manifest_captured_at=FRESH,
    )
    fixtures["grant_foreign_export"] = grant(
        "grant-foreign",
        ["p-60", "p-61"],
        [
            purchase(FRESH, export("p-60", "settled", "delivered", grant_id="grant-foreign")),
            purchase(FRESH, export("p-61", "settled", "delivered", grant_id="grant-other")),
        ],
        manifest_captured_at=FRESH,
    )

    # A complete, consistent bundle where a second purchase with the same fingerprint is
    # still executing: it cannot contradict a duplicate claim yet. Fresh and stale variants.
    for name, captured in (("grant_with_in_flight", FRESH), ("grant_stale_in_flight", STALE)):
        fixtures[name] = grant(
            "grant-inflight",
            ["p-70", "p-71"],
            [
                purchase(captured, export("p-70", "settled", "delivered", grant_id="grant-inflight",
                                          request_fingerprint=FP_F)),
                purchase(captured, export("p-71", "executing", grant_id="grant-inflight",
                                          request_fingerprint=FP_F)),
            ],
            manifest_captured_at=captured,
        )

    return fixtures


def main() -> None:
    for name, data in build_all().items():
        with open(os.path.join(HERE, f"{name}.json"), "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2)
            handle.write("\n")


if __name__ == "__main__":
    main()
