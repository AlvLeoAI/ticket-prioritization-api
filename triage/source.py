"""Where the evidence shape comes from, pinned to one upstream commit.

`triage/payments_lab.py` mirrors `Ledger.export_audit()` and the `PaymentState` /
`DeliveryState` enums from this exact revision. If the upstream shape changes, bump the SHA
here, update the mirror, and regenerate the fixtures.
"""

PAYMENTS_LAB_REPOSITORY = "AlvLeoAI/Agentic-Payments-Lab"
PAYMENTS_LAB_COMMIT = "ddac023eaac8da578bda56cfb489c74992a74422"
PAYMENTS_LAB_EXPORTER = "agentic_payments_lab.ledger.Ledger.export_audit"

# Value fixtures use for `source` on evidence envelopes.
EXPORT_AUDIT_SOURCE = "agentic-payments-lab/ledger.export_audit"
