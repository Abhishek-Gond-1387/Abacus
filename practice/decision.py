"""Compatibility import for the outcome policy now owned by `abacus.verifier`."""

from abacus.verifier import ClaimContract, EvidenceRecord, EvidenceStatus, decide

__all__ = ["ClaimContract", "EvidenceRecord", "EvidenceStatus", "decide"]
