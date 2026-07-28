"""World-time retention, reinforcement, and deterministic memory recall."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from typing import Any


BASE_STABILITY_DAYS = 7.0
MIN_STABILITY_DAYS = 0.5
MAX_STABILITY_DAYS = 365.0
SECONDS_PER_DAY = 86_400.0

SOURCE_MULTIPLIERS = {
    "authored_event": 2.0,
    "player_message": 1.5,
    "admin": 1.5,
    "admin_verification": 1.5,
    "legacy": 1.0,
    "model_inference": 0.75,
}


def as_utc(value: datetime | str) -> datetime:
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def normalized_importance(value: Any, *, integer_scale: bool = False) -> float:
    try:
        importance = float(value)
    except (TypeError, ValueError):
        importance = 0.5
    if integer_scale or importance > 1.0:
        importance /= 10.0
    return max(0.0, min(1.0, importance))


def importance_multiplier(importance: float) -> float:
    return 2.0 ** (4.0 * (normalized_importance(importance) - 0.5))


def source_multiplier(source_kind: str | None) -> float:
    return SOURCE_MULTIPLIERS.get(str(source_kind or "legacy"), 1.0)


def initial_stability_days(importance: float, source_kind: str | None) -> float:
    stability = (
        BASE_STABILITY_DAYS
        * importance_multiplier(importance)
        * source_multiplier(source_kind)
    )
    return max(MIN_STABILITY_DAYS, min(MAX_STABILITY_DAYS, stability))


def retention(
    anchor_strength: float,
    elapsed_seconds: float,
    stability_days: float,
) -> float:
    elapsed_days = max(0.0, float(elapsed_seconds)) / SECONDS_PER_DAY
    stability = max(MIN_STABILITY_DAYS, float(stability_days))
    value = float(anchor_strength) / (1.0 + elapsed_days / stability)
    return max(0.0, min(1.0, value))


def reinforce(current_retention: float, stability_days: float) -> tuple[float, float]:
    current = max(0.0, min(1.0, float(current_retention)))
    strengthened = current + (1.0 - current) * 0.5
    stability = max(
        MIN_STABILITY_DAYS,
        min(MAX_STABILITY_DAYS, float(stability_days) * 1.7),
    )
    return strengthened, stability


def clarity_for(retention_value: float) -> str:
    value = float(retention_value)
    if value >= 0.65:
        return "clear"
    if value >= 0.35:
        return "fuzzy"
    if value >= 0.15:
        return "fragment"
    return "forgotten"


def stable_sample(recall_key: str, memory_id: str) -> float:
    digest = hashlib.sha256(
        f"{recall_key}\0{memory_id}".encode("utf-8")
    ).digest()
    return int.from_bytes(digest[:8], "big") / float(1 << 64)


def recall_probability(retention_value: float) -> float:
    if retention_value >= 0.65:
        return 1.0
    if retention_value < 0.15:
        return 0.0
    return max(0.0, min(1.0, float(retention_value)))


def prompt_memory_text(text: str, clarity: str) -> str:
    if clarity == "fuzzy":
        return f"[模糊记忆：请用“似乎、好像、可能”等不确定表达] {text}"
    if clarity == "fragment":
        return f"[记忆碎片：不得主动断言其中细节，只可作为模糊联想] {text}"
    return text


def rank_score(
    original_index: int,
    total: int,
    retention_value: float,
    importance: float,
) -> float:
    if total <= 1:
        original_relevance = 1.0
    else:
        original_relevance = 1.0 - (original_index / (total - 1))
    return (
        0.60 * original_relevance
        + 0.25 * float(retention_value)
        + 0.15 * normalized_importance(importance)
    )


def memory_identity(record: dict, memory_type: str) -> str:
    for key in ("claim_id", "id", "memory_id"):
        value = record.get(key)
        if value is not None and str(value).strip():
            return str(value)
    text = str(record.get("fact_text") or record.get("memory_text") or "")
    return hashlib.sha256(f"{memory_type}\0{text}".encode("utf-8")).hexdigest()


def candidate_source(record: dict, memory_type: str) -> str:
    if memory_type == "player_fact":
        return str(record.get("source_kind") or "legacy")
    return str(record.get("source_kind") or "model_inference")


def candidate_importance(record: dict, memory_type: str) -> float:
    provenance = record.get("provenance") or {}
    if "importance" in record:
        return normalized_importance(
            record["importance"],
            integer_scale=(memory_type == "player_fact" and "claim_id" not in record),
        )
    candidates = []
    if "importance" in provenance:
        candidates.append(normalized_importance(provenance["importance"]))
    for evidence in provenance.get("evidence") or []:
        if not isinstance(evidence, dict):
            continue
        details = evidence.get("details") or {}
        if not isinstance(details, dict) or "importance" not in details:
            continue
        candidates.append(normalized_importance(
            details["importance"],
            integer_scale=(evidence.get("source_kind") == "legacy"),
        ))
    return max(candidates, default=0.5)


def effective_elapsed_seconds(state: dict, world_now: datetime | str) -> float:
    cumulative = max(0.0, float(state.get("elapsed_decay_seconds") or 0.0))
    watermark = state.get("world_time_watermark")
    if not watermark:
        return cumulative
    delta = (as_utc(world_now) - as_utc(watermark)).total_seconds()
    return cumulative + max(0.0, delta)


def state_retention(state: dict, world_now: datetime | str) -> float:
    cumulative = effective_elapsed_seconds(state, world_now)
    anchor_elapsed = max(0.0, float(state.get("anchor_elapsed_seconds") or 0.0))
    return retention(
        state.get("anchor_strength", 1.0),
        max(0.0, cumulative - anchor_elapsed),
        state.get("stability_days", BASE_STABILITY_DAYS),
    )


def evaluate_records(
    records: list[dict],
    *,
    owner_user_id: str,
    character_id: str,
    memory_type: str,
    world_now: datetime | str,
    recall_key: str,
    text_key: str,
    limit: int | None = None,
    advance: bool = True,
) -> list[dict]:
    """Apply the curve to already-authorized, already-relevant candidates."""
    from memoria.db import repository

    evaluated = []
    total = len(records)
    world_iso = as_utc(world_now).isoformat()
    for index, original in enumerate(records):
        record = dict(original)
        memory_id = memory_identity(record, memory_type)
        importance = candidate_importance(record, memory_type)
        source_kind = candidate_source(record, memory_type)
        if advance:
            state = repository.advance_or_initialize_memory_curve_state(
                owner_user_id=owner_user_id,
                character_id=character_id,
                memory_type=memory_type,
                memory_id=memory_id,
                world_now=world_iso,
                source_kind=source_kind,
                importance=importance,
            )
        else:
            state = repository.get_memory_curve_state(
                owner_user_id, character_id, memory_type, memory_id
            )
            if state is None:
                state = {
                    "anchor_strength": 1.0,
                    "stability_days": initial_stability_days(
                        importance, source_kind
                    ),
                    "anchor_elapsed_seconds": 0.0,
                    "elapsed_decay_seconds": 0.0,
                    "world_time_watermark": world_iso,
                    "reinforcement_count": 0,
                }

        retention_value = state_retention(state, world_iso)
        clarity = clarity_for(retention_value)
        probability = recall_probability(retention_value)
        sample = stable_sample(recall_key, memory_id)
        sampled = clarity == "clear" or (
            clarity in {"fuzzy", "fragment"} and sample < probability
        )
        exclusion_reason = None
        if clarity == "forgotten":
            exclusion_reason = "retention_below_threshold"
        elif not sampled:
            exclusion_reason = "deterministic_sample_miss"

        cumulative = effective_elapsed_seconds(state, world_iso)
        record.update({
            "memory_id": memory_id,
            "memory_type": memory_type,
            "source_kind": source_kind,
            "importance": importance,
            "retention": retention_value,
            "clarity": clarity,
            "stability_days": float(state["stability_days"]),
            "elapsed_decay_seconds": cumulative,
            "reinforcement_count": int(
                state.get("reinforcement_count") or 0
            ),
            "recall_probability": probability,
            "sample_value": sample,
            "sampled": sampled,
            "exclusion_reason": exclusion_reason,
            "memory_curve_rank": rank_score(
                index, total, retention_value, importance
            ),
            "memory_curve_original_text": str(record.get(text_key) or ""),
        })
        if sampled:
            record[text_key] = prompt_memory_text(
                str(record.get(text_key) or ""), clarity
            )
        evaluated.append(record)

    included = [record for record in evaluated if record["sampled"]]
    included.sort(key=lambda item: item["memory_curve_rank"], reverse=True)
    if limit is not None:
        return included[:max(0, int(limit))]
    return included


def inspect_records(
    records: list[dict],
    **kwargs,
) -> list[dict]:
    """Read-only evaluation that includes forgotten and sample misses."""
    from memoria.db import repository

    # evaluate_records intentionally returns only recalled rows, so diagnostics
    # repeat its small loop with a sentinel limit by evaluating one row at a time.
    inspected = []
    total = len(records)
    world_now = kwargs["world_now"]
    recall_key = kwargs["recall_key"]
    owner_user_id = kwargs["owner_user_id"]
    character_id = kwargs["character_id"]
    memory_type = kwargs["memory_type"]
    text_key = kwargs["text_key"]
    world_iso = as_utc(world_now).isoformat()
    for index, original in enumerate(records):
        record = dict(original)
        memory_id = memory_identity(record, memory_type)
        importance = candidate_importance(record, memory_type)
        source_kind = candidate_source(record, memory_type)
        state = repository.get_memory_curve_state(
            owner_user_id, character_id, memory_type, memory_id
        ) or {
            "anchor_strength": 1.0,
            "stability_days": initial_stability_days(importance, source_kind),
            "anchor_elapsed_seconds": 0.0,
            "elapsed_decay_seconds": 0.0,
            "world_time_watermark": world_iso,
            "reinforcement_count": 0,
        }
        retention_value = state_retention(state, world_iso)
        clarity = clarity_for(retention_value)
        probability = recall_probability(retention_value)
        sample = stable_sample(recall_key, memory_id)
        sampled = clarity == "clear" or (
            clarity in {"fuzzy", "fragment"} and sample < probability
        )
        exclusion_reason = None
        if clarity == "forgotten":
            exclusion_reason = "retention_below_threshold"
        elif not sampled:
            exclusion_reason = "deterministic_sample_miss"
        record.update({
            "memory_id": memory_id,
            "memory_type": memory_type,
            "text": str(record.get(text_key) or ""),
            "source_kind": source_kind,
            "importance": importance,
            "retention": retention_value,
            "clarity": clarity,
            "stability_days": float(state["stability_days"]),
            "elapsed_decay_seconds": effective_elapsed_seconds(
                state, world_iso
            ),
            "reinforcement_count": int(
                state.get("reinforcement_count") or 0
            ),
            "recall_probability": probability,
            "sample_value": sample,
            "sampled": sampled,
            "exclusion_reason": exclusion_reason,
            "memory_curve_rank": rank_score(
                index, total, retention_value, importance
            ),
        })
        inspected.append(record)
    inspected.sort(key=lambda item: item["memory_curve_rank"], reverse=True)
    return inspected
