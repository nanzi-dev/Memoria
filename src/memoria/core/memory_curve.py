"""World-time retention, reinforcement, and deterministic memory recall."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

BASE_STABILITY_DAYS = 7.0
MIN_STABILITY_DAYS = 0.5
SECONDS_PER_DAY = 86_400.0
MIN_CANDIDATE_LIMIT = 20
DEFAULT_CANDIDATE_MULTIPLIER = 3

SOURCE_MULTIPLIERS = {
    "authored_event": 2.0,
    "player_message": 1.5,
    "admin": 1.5,
    "admin_verification": 1.5,
    "legacy": 1.0,
    "model_inference": 0.75,
}

# ──────────────────────────────────────────────────────────────
# Fix 4: module-level cached config reference with lazy init
# ──────────────────────────────────────────────────────────────
_cfg_cache: Any = None
_cfg_load_attempted: bool = False


def _cfg() -> Any:
    global _cfg_cache, _cfg_load_attempted
    if _cfg_cache is None and not _cfg_load_attempted:
        _cfg_load_attempted = True
        from memoria.core.config import configs
        _cfg_cache = configs
    return _cfg_cache


def _reset_cfg_cache() -> None:
    """Reset cached config (for tests that monkeypatch)."""
    global _cfg_cache, _cfg_load_attempted
    _cfg_cache = None
    _cfg_load_attempted = False


def max_stability_days() -> float:
    return float(_cfg().memory_curve_max_stability_days)


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
    return max(MIN_STABILITY_DAYS, min(max_stability_days(), stability))


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
        min(max_stability_days(), float(stability_days) * 1.7),
    )
    return strengthened, stability


def clarity_for(retention_value: float) -> str:
    cfg = _cfg()
    value = float(retention_value)
    if value >= cfg.memory_curve_clarity_clear:
        return "clear"
    if value >= cfg.memory_curve_clarity_fuzzy:
        return "fuzzy"
    if value >= cfg.memory_curve_clarity_fragment:
        return "fragment"
    return "forgotten"


# ──────────────────────────────────────────────────────────────
# Fix 2: sampling with per-turn salt for cross-turn variation
# ──────────────────────────────────────────────────────────────
def stable_sample(recall_key: str, memory_id: str) -> float:
    digest = hashlib.sha256(
        f"{recall_key}\0{memory_id}".encode("utf-8")
    ).digest()
    return int.from_bytes(digest[:8], "big") / float(1 << 64)


def volatile_sample(recall_key: str, memory_id: str, turn_salt: str) -> float:
    """Like stable_sample but incorporates a per-turn salt.

    Same (recall_key, memory_id, turn_salt) triple produces the same result,
    but different turn_salt values yield different outcomes — giving fuzzy and
    fragment memories genuine cross-turn variation.
    """
    digest = hashlib.sha256(
        f"{recall_key}\0{memory_id}\0{turn_salt}".encode("utf-8")
    ).digest()
    return int.from_bytes(digest[:8], "big") / float(1 << 64)


def recall_probability(retention_value: float) -> float:
    cfg = _cfg()
    if retention_value >= cfg.memory_curve_clarity_clear:
        return 1.0
    if retention_value < cfg.memory_curve_clarity_fragment:
        return 0.0
    return max(0.0, min(1.0, float(retention_value)))


def prompt_memory_text(text: str, clarity: str) -> str:
    if clarity == "fuzzy":
        prefix = "[模糊记忆：请用\u201c似乎、好像、可能\u201d等不确定表达] "
        return prefix + text
    if clarity == "fragment":
        prefix = "[记忆碎片：不得主动断言其中细节，只可作为模糊联想] "
        return prefix + text
    return text


def rank_score(
    original_index: int,
    total: int,
    retention_value: float,
    importance: float,
) -> float:
    cfg = _cfg()
    w_rel = cfg.memory_curve_rank_weight_relevance
    w_ret = cfg.memory_curve_rank_weight_retention
    w_imp = cfg.memory_curve_rank_weight_importance
    if total <= 1:
        original_relevance = 1.0
    else:
        original_relevance = 1.0 - (original_index / (total - 1))
    return (
        w_rel * original_relevance
        + w_ret * float(retention_value)
        + w_imp * normalized_importance(importance)
    )


def candidate_limit(
    target_limit: int,
    multiplier: int = DEFAULT_CANDIDATE_MULTIPLIER,
) -> int:
    target = max(0, int(target_limit))
    factor = max(1, int(multiplier))
    return max(MIN_CANDIDATE_LIMIT, target * factor)


def memory_identity(record: dict, memory_type: str) -> str:
    if memory_type == "player_fact":
        provenance = record.get("provenance") or {}
        for evidence in provenance.get("evidence") or []:
            if not isinstance(evidence, dict):
                continue
            details = evidence.get("details") or {}
            if not isinstance(details, dict) or not details.get("legacy_backfill"):
                continue
            legacy_fact_id = details.get("legacy_fact_id")
            if legacy_fact_id is not None and str(legacy_fact_id).strip():
                return str(legacy_fact_id)
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
    r = retention(
        state.get("anchor_strength", 1.0),
        max(0.0, cumulative - anchor_elapsed),
        state.get("stability_days", BASE_STABILITY_DAYS),
    )
    # Permanent-memory pin: if reinforced stability is very high, pin retention.
    cfg = _cfg()
    threshold = float(cfg.memory_curve_permanent_threshold)
    if float(state.get("stability_days", 0)) >= max_stability_days() * 0.95 and r >= threshold:
        return 1.0
    return r


# ──────────────────────────────────────────────────────────────
# Context manager for independent per-type evaluation
# ──────────────────────────────────────────────────────────────
@contextmanager
def curve_eval_context(fallback_records: list[dict], limit: int | None = None):
    """Yields a mutable list; on exception, replaces it with fallback and logs."""
    container = list(fallback_records)
    try:
        yield container
    except Exception as exc:
        logger.warning("记忆曲线召回失败，回退到原始召回: %s", exc)
        container.clear()
        container.extend(fallback_records[:limit] if limit else fallback_records)


def _generate_turn_salt(recall_key: str) -> str:
    """Generate a per-turn salt from recall_key + wall-clock monotonic counter.

    Within one evaluate_records call the salt is fixed, so deterministic
    sampling is still reproducible for the same batch.  Across separate
    calls the monotonic counter changes, giving fuzzy/fragment memories
    genuine cross-turn variation.
    """
    return f"{recall_key}:{time.monotonic_ns()}"


# ──────────────────────────────────────────────────────────────
# Batch evaluate with single DB transaction
# ──────────────────────────────────────────────────────────────
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
    """Apply the curve to already-authorized, already-relevant candidates.

    Uses a single batch DB call instead of one call per record.
    """
    from memoria.db import repository

    if not records:
        return []

    total = len(records)
    world_iso = as_utc(world_now).isoformat()
    turn_salt = _generate_turn_salt(recall_key)

    # Build batch payload
    batch_items = []
    for index, original in enumerate(records):
        record = dict(original)
        memory_id = memory_identity(record, memory_type)
        importance = candidate_importance(record, memory_type)
        source_kind = candidate_source(record, memory_type)
        batch_items.append({
            "index": index,
            "record": record,
            "memory_id": memory_id,
            "importance": importance,
            "source_kind": source_kind,
        })

    # Single batch DB call
    states = repository.batch_advance_or_initialize_memory_curve_states(
        owner_user_id=owner_user_id,
        character_id=character_id,
        memory_type=memory_type,
        items=[
            {
                "memory_id": item["memory_id"],
                "world_now": world_iso,
                "source_kind": item["source_kind"],
                "importance": item["importance"],
            }
            for item in batch_items
        ],
    )

    evaluated = []
    for item in batch_items:
        record = item["record"]
        state = states[item["memory_id"]]
        retention_value = state_retention(state, world_iso)
        clarity = clarity_for(retention_value)
        probability = recall_probability(retention_value)
        sample = volatile_sample(recall_key, item["memory_id"], turn_salt)
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
            "memory_id": item["memory_id"],
            "memory_type": memory_type,
            "source_kind": item["source_kind"],
            "importance": item["importance"],
            "retention": retention_value,
            "clarity": clarity,
            "stability_days": float(state["stability_days"]),
            "elapsed_decay_seconds": cumulative,
            "reinforcement_count": int(state.get("reinforcement_count") or 0),
            "recall_probability": probability,
            "sample_value": sample,
            "sampled": sampled,
            "exclusion_reason": exclusion_reason,
            "memory_curve_rank": rank_score(
                item["index"], total, retention_value, item["importance"]
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
    """Read-only inspection: does NOT advance, reinforce, or initialize states."""
    from memoria.db import repository

    owner_user_id = kwargs["owner_user_id"]
    character_id = kwargs["character_id"]
    memory_type = kwargs["memory_type"]
    world_now = kwargs["world_now"]
    recall_key = kwargs.get("recall_key", "inspect")
    text_key = kwargs["text_key"]
    include_forgotten = kwargs.get("include_forgotten", False)

    total = len(records)
    world_iso = as_utc(world_now).isoformat()
    inspected = []
    for index, original in enumerate(records):
        record = dict(original)
        memory_id = memory_identity(record, memory_type)
        importance = candidate_importance(record, memory_type)
        source_kind = candidate_source(record, memory_type)

        state = repository.get_memory_curve_state(
            owner_user_id, character_id, memory_type, memory_id
        )
        if state is None:
            state = {
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
            "reinforcement_count": int(state.get("reinforcement_count") or 0),
            "recall_probability": probability,
            "sample_value": sample,
            "sampled": sampled,
            "exclusion_reason": exclusion_reason,
            "memory_curve_rank": rank_score(index, total, retention_value, importance),
            "memory_curve_original_text": str(record.get(text_key) or ""),
            "text": str(record.get(text_key) or ""),
        })
        inspected.append(record)

    result = inspected
    if not include_forgotten:
        result = [r for r in result if r["exclusion_reason"] != "retention_below_threshold"]
    result.sort(key=lambda item: item["memory_curve_rank"], reverse=True)
    return result


# ──────────────────────────────────────────────────────────────
# Cleanup forgotten states
# ──────────────────────────────────────────────────────────────
def cleanup_forgotten_states(owner_user_id: str | None = None) -> int:
    """Delete curve states that have been below the forgotten threshold
    for longer than `memory_curve_forgotten_cleanup_days`.

    Returns the number of deleted rows.
    """
    from memoria.db import repository
    return repository.cleanup_forgotten_memory_curve_states(
        owner_user_id=owner_user_id,
        forgotten_threshold_days=float(_cfg().memory_curve_forgotten_cleanup_days),
        clarity_fragment_threshold=float(_cfg().memory_curve_clarity_fragment),
    )
