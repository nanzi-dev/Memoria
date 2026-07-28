import hashlib
import json
import logging
from typing import Any

from memoria.core.fact_claim_policy import (
    ADMIN_VERIFICATION_SOURCE_KIND,
    CLAIM_SOURCE_KINDS,
    clean_source_ids,
    derive_fact_claim_identity,
    evaluate_verification,
    normalize_fact_text,
)
from memoria.db import repository


logger = logging.getLogger(__name__)


SCOPE_TYPES = frozenset({"character", "group_thread", "story"})
SOURCE_KINDS = CLAIM_SOURCE_KINDS


def _verification_policy(
    normalized_fact_text: str,
):
    def decide(evidence: list[dict[str, Any]]) -> dict[str, Any]:
        return evaluate_verification(normalized_fact_text, evidence)

    return decide


def _clean_identity(value: str, field_name: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"{field_name} must not be blank")
    return normalized


def _clean_source_ids(source_ids: list[str]) -> list[str]:
    return clean_source_ids(source_ids)


def record_claim(
    owner_user_id: str,
    scope_type: str,
    scope_id: str,
    fact_text: str,
    *,
    source_kind: str,
    source_ids: list[str],
    provenance: dict[str, Any] | None = None,
    direct_support: bool = False,
) -> dict:
    owner_user_id = _clean_identity(owner_user_id, "owner_user_id")
    scope_type = _clean_identity(scope_type, "scope_type")
    scope_id = _clean_identity(scope_id, "scope_id")
    source_kind = _clean_identity(source_kind, "source_kind")
    if scope_type not in SCOPE_TYPES:
        raise ValueError(f"unsupported fact claim scope_type: {scope_type}")
    if source_kind not in SOURCE_KINDS:
        raise ValueError(f"unsupported fact claim source_kind: {source_kind}")
    if not isinstance(direct_support, bool):
        raise ValueError("direct_support must be a boolean")
    if provenance is not None and not isinstance(provenance, dict):
        raise ValueError("provenance must be a JSON object")

    original_fact_text = str(fact_text or "")
    identity = derive_fact_claim_identity(
        owner_user_id,
        scope_type,
        scope_id,
        original_fact_text,
    )
    return repository._record_fact_claim(
        claim_id=identity["claim_id"],
        owner_user_id=owner_user_id,
        scope_type=scope_type,
        scope_id=scope_id,
        fact_text=original_fact_text,
        normalized_fact_text=identity["normalized_fact_text"],
        content_hash=identity["content_hash"],
        normalized_content_hash=identity["normalized_content_hash"],
        source_kind=source_kind,
        source_ids=_clean_source_ids(source_ids),
        provenance=dict(provenance or {}),
        direct_support=direct_support,
        verification_policy=_verification_policy(
            identity["normalized_fact_text"]
        ),
    )


def retract_claim(
    owner_user_id: str,
    claim_id: str,
    *,
    reason: str | None = None,
) -> dict:
    owner_user_id = _clean_identity(owner_user_id, "owner_user_id")
    claim_id = _clean_identity(claim_id, "claim_id")
    clean_reason = None if reason is None else str(reason).strip() or None
    return repository._retract_fact_claim(
        owner_user_id,
        claim_id,
        reason=clean_reason,
    )


def record_admin_verification(
    owner_user_id: str,
    claim_id: str,
    *,
    source_ids: list[str],
    provenance: dict[str, Any] | None = None,
    world_occurred_at: str | None = None,
) -> dict:
    owner_user_id = _clean_identity(owner_user_id, "owner_user_id")
    claim_id = _clean_identity(claim_id, "claim_id")
    if provenance is not None and not isinstance(provenance, dict):
        raise ValueError("provenance must be a JSON object")
    claim = repository.get_fact_claim(owner_user_id, claim_id)
    if claim is None:
        raise KeyError(f"fact claim not found: {claim_id}")
    clean_source_ids = _clean_source_ids(source_ids)
    projected = repository._record_fact_claim(
        claim_id=claim_id,
        owner_user_id=owner_user_id,
        scope_type=claim["scope_type"],
        scope_id=claim["scope_id"],
        fact_text=claim["fact_text"],
        normalized_fact_text=claim["normalized_fact_text"],
        content_hash=claim["content_hash"],
        normalized_content_hash=claim["normalized_content_hash"],
        source_kind=ADMIN_VERIFICATION_SOURCE_KIND,
        source_ids=clean_source_ids,
        provenance=dict(provenance or {}),
        direct_support=True,
        verification_policy=_verification_policy(
            claim["normalized_fact_text"]
        ),
    )
    try:
        from memoria.core import memory_curve, world_clock
        from memoria.core.config import configs

        if not configs.memory_curve_enabled:
            return projected
        states = repository.list_memory_curve_states_for_memory(
            owner_user_id,
            "player_fact",
            claim_id,
        )
        witness_ids = {
            str(state["character_id"])
            for state in states
            if str(state.get("character_id") or "").strip()
        }
        if claim["scope_type"] == "character":
            witness_ids.add(str(claim["scope_id"]))
        for evidence in (claim.get("provenance") or {}).get("evidence") or []:
            details = evidence.get("details") or {}
            witness_ids.update(
                str(character_id)
                for character_id in details.get("allowed_character_ids") or []
                if str(character_id).strip()
            )
            session_id = str(details.get("session_id") or "").strip()
            session = repository.get_session(session_id) if session_id else None
            if session and session.get("player_id") == owner_user_id:
                witness_ids.update(
                    str(participant["character_id"])
                    for participant in repository.get_session_participants(
                        session_id,
                        only_active=False,
                    )
                    if str(participant.get("character_id") or "").strip()
                )
        if not witness_ids:
            return projected
        occurred_at = world_occurred_at or world_clock.get_clock_snapshot(
            owner_user_id
        ).world_now.isoformat()
        evidence_id = "admin-verification:" + hashlib.sha256(
            json.dumps(
                clean_source_ids,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        importance = memory_curve.candidate_importance(
            projected,
            "player_fact",
        )
        for character_id in sorted(witness_ids):
            repository.record_memory_curve_evidence(
                owner_user_id=owner_user_id,
                character_id=character_id,
                memory_type="player_fact",
                memory_id=claim_id,
                evidence_id=evidence_id,
                world_occurred_at=occurred_at,
                source_kind=ADMIN_VERIFICATION_SOURCE_KIND,
                importance=importance,
            )
    except Exception as exc:
        logger.warning("管理员事实确认曲线写入失败，保留事实账本: %s", exc)
    return projected


def supersede_claim(
    owner_user_id: str,
    claim_id: str,
    superseded_by_claim_id: str,
    *,
    reason: str | None = None,
) -> dict:
    owner_user_id = _clean_identity(owner_user_id, "owner_user_id")
    claim_id = _clean_identity(claim_id, "claim_id")
    superseded_by_claim_id = _clean_identity(
        superseded_by_claim_id,
        "superseded_by_claim_id",
    )
    if claim_id == superseded_by_claim_id:
        raise ValueError("a fact claim cannot supersede itself")
    clean_reason = None if reason is None else str(reason).strip() or None
    return repository._supersede_fact_claim(
        owner_user_id,
        claim_id,
        superseded_by_claim_id,
        reason=clean_reason,
    )
