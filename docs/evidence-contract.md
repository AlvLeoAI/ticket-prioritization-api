# Evidence contract

> **Status: Phase 1a.** This document describes the `triage/` package: what counts as
> evidence, how a claim is verified against it, and what the verifier may and may not say.
> It assigns no priorities, severities, SLAs or queues; those belong to
> [`priority-policy.md`](priority-policy.md), which is still a stub.

## Principle

**The ticket text is never evidence.** A ticket makes a *claim*; the only thing that can
confirm or contradict a claim is an export from the system that holds the money: the
Agentic-Payments-Lab ledger. The verifier is a pure function over `(claim, evidence)`. It
reads no text, calls no model, consults no clock, and decides nothing: a `contradicted`
outcome is a statement about evidence, not an instruction to close a ticket.

## Source, pinned

| | |
|---|---|
| Repository | `AlvLeoAI/Agentic-Payments-Lab` |
| Commit | `ddac023eaac8da578bda56cfb489c74992a74422` |
| Exporter | `agentic_payments_lab.ledger.Ledger.export_audit(purchase_id)` |
| Enums | `agentic_payments_lab.domain.PaymentState`, `DeliveryState` |

`triage/payments_lab.py` mirrors that surface as frozen Pydantic models with
`extra="forbid"`. Every key `export_audit()` emits is declared so a real export validates
unchanged; the verifier itself reads only `purchase_id`, `grant_id`, `request_fingerprint`,
`payment_state` and `delivery_state`. Payments-Lab is **not** a dependency; the pin is recorded
in `triage/source.py`.

### `AuditExport` (the `export_audit()` dict)

```
mode: "simulated"            purchase_id            request_fingerprint (sha256 hex)
grant_id                     policy_version         service_id        merchant_id
network                      asset                  recipient         amount (int, atomic)
payment_state                delivery_state         events: [AuditEvent]
```

`AuditEvent` is one row of the ledger's append-only `events` table:
`sequence, purchase_id, event_type, data, recorded_at`. Upstream omits receipt payloads,
resource content and raw requests from the export, so they never reach this repository.

### States

| `PaymentState` | Terminal? | Meaning for the verifier |
|---|---|---|
| `denied` | yes | authorization refused; nothing charged |
| `reserved` | **no** | budget held, not yet dispatched |
| `executing` | **no** | dispatched, outcome not yet known |
| `unknown` | **no** | outcome lost; needs reconciliation |
| `settled` | yes | charged |
| `failed` | yes | payment failed; nothing charged |
| `not_required` | yes | zero-amount purchase; nothing charged |

`reserved`, `executing` and `unknown` are *in flight*: the ledger can still change them, so
evidence showing them may already be out of date. The ledger's `resolve()` refuses to change a
purchase once it is terminal.

`DeliveryState` is `not_requested`, `failed` or `delivered`.

## Evidence envelopes

All timestamps are the **simulation clock, integer seconds**, the same clock a ticket's
`created_at` uses. Both envelopes carry `source` (which exporter) and `source_version` (which
revision of it; fixtures use the pinned commit SHA).

### `PurchaseEvidence`

One `export_audit()` result for one purchase.

```
kind: "purchase"   source   source_version   captured_at   payload: AuditExport
```

### `GrantEvidence`

Every purchase under one grant.

```
kind: "grant"   source   source_version   grant_id   manifest_captured_at
manifest: [purchase_id, ...]   exports: [PurchaseEvidence, ...]
```

- **Complete** iff every manifest `purchase_id` has exactly one export and no export is
  outside the manifest. Missing, duplicated and unlisted ids are each reported.
- **Consistent** iff `max(captured_at) − min(captured_at)` across the exports is at most
  `MAX_BUNDLE_SKEW_SECONDS` **and** every export's `payload.grant_id` equals the bundle's
  `grant_id`.
- `MAX_BUNDLE_SKEW_SECONDS` (default 300, `triage/config.py`) is a **placeholder, not
  policy**. `verify()` accepts an override.

### Known gap: no atomic grant export

Payments-Lab exports one purchase at a time. There is no ledger call that returns "all
purchases of grant G as of time T", so a `GrantEvidence` bundle is *assembled*: the manifest
is read, then each export is captured separately. Between those reads a purchase can change
state or a new one can appear. That is why completeness and consistency are checked here
rather than assumed, and why a duplicate-charge claim can only be contradicted by a bundle
that passes both checks. An atomic grant export is future work in the Payments-Lab repository.

## Claims (input)

A `Claim` is already structured when it reaches the verifier; extracting it from ticket text
is a later phase. It carries identifiers and the ticket's `created_at`, and rejects any other
field.

| `claim_type` | Needs | Meaning |
|---|---|---|
| `charged_not_delivered` | `purchase_id` | "I paid and got nothing" |
| `duplicate_charge` | `purchase_id` and/or `grant_id` | "I was charged twice" |
| `unauthorized_purchase` | `purchase_id` | "I never approved this" |
| `charged_but_denied` | `purchase_id` | "It said denied but I was charged" |

## Verification result (output)

```
VerificationResult
  claim            the input
  outcome          confirmed | contradicted | unverifiable
  reason           reason code (required when unverifiable; otherwise usually null)
  evidence_used    [EvidenceRef]  which envelopes the outcome rests on
  details          the facts behind it (states, ids, skew, conflicts)
```

### Reason codes

| Code | When |
|---|---|
| `purchase_not_found` | no export for the claimed purchase, or it exists under a different grant than the claim names |
| `sources_conflict` | two exports for one purchase have the same `captured_at` and different states; nothing is picked |
| `stale` | the purchase is in flight and the evidence was captured before the ticket was created |
| `in_flight_state` | the purchase is `reserved`, `executing` or `unknown` (or, for duplicates, a sibling is) |
| `incomplete_scope` | a duplicate claim cannot be contradicted: no grant bundle, or the bundle is incomplete |
| `inconsistent_bundle` | the grant bundle exceeds the skew limit or contains another grant's export |
| `requires_human_review` | always set on `unauthorized_purchase` |

### Resolving several exports for one purchase

Exports are indexed by `purchase_id` whether supplied on their own or inside a bundle. The
newest `captured_at` wins. Several exports with the same newest `captured_at` corroborate each
other if their states agree and are all listed in `evidence_used`; if their states differ the
result is `sources_conflict`. Nothing is ever picked silently.

### Order of the common checks

For a purchase-scoped claim: not found → conflict → claimed grant mismatch → stale → in
flight. A stale, in-flight export is reported as `stale` rather than `in_flight_state` because
re-pulling the evidence may resolve it. Terminal states never go stale: the ledger cannot
change them.

### Rules

**`charged_not_delivered`**

| Evidence | Outcome |
|---|---|
| `settled` + `failed` or `not_requested` | confirmed |
| `settled` + `delivered` | contradicted |
| `denied`, `failed`, `not_required` | contradicted (nothing was charged) |

**`duplicate_charge`** — group purchases by `(grant_id, request_fingerprint)`; with a
`purchase_id` the group is that purchase's, otherwise every group in the grant.

| Evidence | Outcome |
|---|---|
| ≥ 2 `settled` purchases in a group (any envelopes) | confirmed, `settled_duplicate_ids` |
| complete, consistent bundle, ≤ 1 settled per group, no in-flight sibling | contradicted |
| no bundle for the grant | unverifiable, `incomplete_scope` |
| bundle incomplete | unverifiable, `incomplete_scope` |
| bundle skewed or holds another grant's export | unverifiable, `inconsistent_bundle` |
| a sibling in the group is in flight | unverifiable, `in_flight_state` (or `stale`) |
| a sibling has conflicting exports | unverifiable, `sources_conflict` |

**`unauthorized_purchase`** — never contradicted. Evidence can show the purchase exists, not
whether the operator meant it.

| Evidence | Outcome |
|---|---|
| purchase found | confirmed, `requires_human_review`, `details.settled` true/false |
| purchase found, sources conflict | confirmed, `requires_human_review`, `details.settled` null |
| not found | unverifiable, `purchase_not_found` |

**`charged_but_denied`**

| Evidence | Outcome |
|---|---|
| `denied`, `not_required`, `failed` | contradicted (nothing was charged) |
| `settled` | confirmed |
| `unknown`, `reserved`, `executing` | unverifiable, `in_flight_state` |

## Fixtures

`tests/fixtures/evidence/*.json` are synthetic, generated by `generate.py` in that directory,
and cover every row above plus the missing-purchase, incomplete-manifest, excessive-skew,
conflicting-duplicate and terminal-vs-non-terminal-stale cases. A test checks the committed
JSON against the generator's output. No fixture contains real identifiers, money or text.
