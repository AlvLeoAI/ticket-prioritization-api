"""Claims: the structured statement a ticket makes, as the verifier receives it.

A claim carries identifiers and a timestamp, never ticket text. Extracting a claim from text
is a later phase's job; this phase takes claims as given.
"""

from enum import Enum
from typing import Optional

from pydantic import model_validator

from triage.payments_lab import Frozen, Identifier, Timestamp


class ClaimType(str, Enum):
    CHARGED_NOT_DELIVERED = "charged_not_delivered"
    DUPLICATE_CHARGE = "duplicate_charge"
    UNAUTHORIZED_PURCHASE = "unauthorized_purchase"
    CHARGED_BUT_DENIED = "charged_but_denied"


# These claims are about one purchase and cannot be verified from a grant id alone.
PURCHASE_SCOPED_CLAIMS = frozenset(
    {
        ClaimType.CHARGED_NOT_DELIVERED,
        ClaimType.UNAUTHORIZED_PURCHASE,
        ClaimType.CHARGED_BUT_DENIED,
    }
)


class Claim(Frozen):
    claim_type: ClaimType
    purchase_id: Optional[Identifier] = None
    grant_id: Optional[Identifier] = None
    # When the ticket was created, on the same simulation clock as evidence `captured_at`.
    created_at: Timestamp

    @model_validator(mode="after")
    def _has_a_subject(self):
        if self.purchase_id is None and self.grant_id is None:
            raise ValueError("a claim needs a purchase_id, a grant_id, or both")
        if self.claim_type in PURCHASE_SCOPED_CLAIMS and self.purchase_id is None:
            raise ValueError(f"{self.claim_type.value} is about one purchase: purchase_id required")
        return self
