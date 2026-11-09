"""Evidence envelopes: what the verifier accepts as evidence.

Ticket text is never evidence. The only evidence is an export from Payments-Lab wrapped in an
envelope that says where it came from and when (simulation clock, integer seconds) it was
captured.
"""

from typing import Annotated, Any, Dict, Literal, Tuple, Union

from pydantic import Field, TypeAdapter, model_validator

from triage.payments_lab import AuditExport, Frozen, Identifier, Timestamp


class PurchaseEvidence(Frozen):
    """One `export_audit()` result for one purchase, with capture metadata."""

    kind: Literal["purchase"] = "purchase"
    source: Annotated[str, Field(min_length=1)]
    source_version: Annotated[str, Field(min_length=1)]
    captured_at: Timestamp
    payload: AuditExport

    @property
    def purchase_id(self) -> str:
        return self.payload.purchase_id


class GrantEvidence(Frozen):
    """Every purchase under one grant, assembled from per-purchase exports.

    Payments-Lab has no atomic grant export, so the bundle is a manifest (the purchase ids the
    ledger listed for the grant at `manifest_captured_at`) plus one export per listed purchase,
    each captured separately. Completeness and consistency are therefore properties the
    verifier must check, not guarantees of the source.
    """

    kind: Literal["grant"] = "grant"
    source: Annotated[str, Field(min_length=1)]
    source_version: Annotated[str, Field(min_length=1)]
    grant_id: Identifier
    manifest_captured_at: Timestamp
    manifest: Tuple[Identifier, ...]
    exports: Tuple[PurchaseEvidence, ...]

    @model_validator(mode="after")
    def _manifest_has_no_duplicates(self):
        if len(set(self.manifest)) != len(self.manifest):
            raise ValueError("manifest lists a purchase_id more than once")
        return self

    @property
    def missing_purchase_ids(self) -> Tuple[str, ...]:
        """Manifest entries with no export."""
        exported = {export.purchase_id for export in self.exports}
        return tuple(pid for pid in self.manifest if pid not in exported)

    @property
    def duplicated_purchase_ids(self) -> Tuple[str, ...]:
        """Manifest entries with more than one export."""
        counts: Dict[str, int] = {}
        for export in self.exports:
            counts[export.purchase_id] = counts.get(export.purchase_id, 0) + 1
        return tuple(pid for pid in self.manifest if counts.get(pid, 0) > 1)

    @property
    def unlisted_purchase_ids(self) -> Tuple[str, ...]:
        """Exports for purchases the manifest does not list."""
        listed = set(self.manifest)
        seen: Dict[str, None] = {}
        for export in self.exports:
            if export.purchase_id not in listed:
                seen.setdefault(export.purchase_id, None)
        return tuple(seen)

    @property
    def foreign_purchase_ids(self) -> Tuple[str, ...]:
        """Exports whose payload belongs to a different grant."""
        return tuple(
            export.purchase_id
            for export in self.exports
            if export.payload.grant_id != self.grant_id
        )

    @property
    def is_complete(self) -> bool:
        """Every manifest purchase_id has exactly one export, and nothing else is present."""
        return not (
            self.missing_purchase_ids or self.duplicated_purchase_ids or self.unlisted_purchase_ids
        )

    @property
    def skew_seconds(self) -> int:
        """Spread of the exports' `captured_at` values (0 for an empty bundle)."""
        if not self.exports:
            return 0
        times = [export.captured_at for export in self.exports]
        return max(times) - min(times)

    def is_consistent(self, max_skew_seconds: int) -> bool:
        return not self.foreign_purchase_ids and self.skew_seconds <= max_skew_seconds


EvidenceItem = Union[PurchaseEvidence, GrantEvidence]

_evidence_adapter: TypeAdapter = TypeAdapter(
    Annotated[EvidenceItem, Field(discriminator="kind")]
)


def parse_evidence(data: Dict[str, Any]) -> EvidenceItem:
    """Build an envelope from a dict (e.g. a loaded JSON fixture), picking the type by `kind`."""
    return _evidence_adapter.validate_python(data)
