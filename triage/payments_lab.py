"""Mirror of the Agentic-Payments-Lab audit export, pinned to `source.PAYMENTS_LAB_COMMIT`.

Only the audit-export surface is mirrored: the dict returned by `Ledger.export_audit()` and
the two state enums it uses. Every key the export emits is declared, because the models forbid
extra fields and must accept a real export unchanged; the verifier itself reads only
`purchase_id`, `grant_id`, `request_fingerprint`, `payment_state` and `delivery_state`.

Payments-Lab is not a dependency. Types follow its `domain.py`: integers for money and time,
never floats.
"""

from enum import Enum
from typing import Annotated, Any, Dict, Literal, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field

# Payments-Lab keeps integers safely below SQLite's signed 64-bit ceiling.
MAX_ATOMIC = 9_000_000_000_000_000
Atomic = Annotated[int, Field(strict=True, ge=0, le=MAX_ATOMIC)]
# Simulation clock, integer seconds.
Timestamp = Annotated[int, Field(strict=True, ge=0, le=MAX_ATOMIC)]
Identifier = Annotated[str, Field(min_length=1, max_length=100, pattern=r"^[a-zA-Z0-9_-]+$")]
Sha256Hex = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class PaymentState(str, Enum):
    """`agentic_payments_lab.domain.PaymentState` at the pinned commit."""

    DENIED = "denied"
    RESERVED = "reserved"
    EXECUTING = "executing"
    UNKNOWN = "unknown"
    SETTLED = "settled"
    FAILED = "failed"
    NOT_REQUIRED = "not_required"


class DeliveryState(str, Enum):
    """`agentic_payments_lab.domain.DeliveryState` at the pinned commit."""

    NOT_REQUESTED = "not_requested"
    FAILED = "failed"
    DELIVERED = "delivered"


# The ledger's `resolve()` refuses to change a purchase once it is in one of these states.
TERMINAL_PAYMENT_STATES = frozenset(
    {PaymentState.SETTLED, PaymentState.FAILED, PaymentState.DENIED, PaymentState.NOT_REQUIRED}
)
# A purchase in one of these states can still change; evidence showing it may be out of date.
IN_FLIGHT_PAYMENT_STATES = frozenset(
    {PaymentState.RESERVED, PaymentState.EXECUTING, PaymentState.UNKNOWN}
)


class AuditEvent(Frozen):
    """One row of the ledger's append-only `events` table, as `export_audit` emits it."""

    sequence: Annotated[int, Field(strict=True, ge=1)]
    purchase_id: Optional[Identifier]
    event_type: Annotated[str, Field(min_length=1)]
    data: Dict[str, Any]
    recorded_at: Timestamp


class AuditExport(Frozen):
    """The dict returned by `Ledger.export_audit(purchase_id)`.

    Upstream deliberately omits receipt payloads, resource content and raw requests, so none
    of those appear here either.
    """

    mode: Literal["simulated"]
    purchase_id: Identifier
    request_fingerprint: Sha256Hex
    grant_id: Identifier
    policy_version: Annotated[str, Field(min_length=1)]
    service_id: Identifier
    merchant_id: Identifier
    network: Annotated[str, Field(min_length=1)]
    asset: Annotated[str, Field(min_length=1)]
    recipient: Identifier
    amount: Atomic
    payment_state: PaymentState
    delivery_state: DeliveryState
    events: Tuple[AuditEvent, ...]

    @property
    def is_payment_terminal(self) -> bool:
        return self.payment_state in TERMINAL_PAYMENT_STATES

    @property
    def is_settled(self) -> bool:
        return self.payment_state is PaymentState.SETTLED
