from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import uuid

import pytest

from memoria.core import memory_curve
from memoria.db import repository


UTC = timezone.utc


def _identity() -> dict:
    suffix = uuid.uuid4().hex
    return {
        "owner_user_id": f"owner-{suffix}",
        "character_id": f"character-{suffix}",
        "memory_type": "player_fact",
        "memory_id": f"memory-{suffix}",
    }


def test_retention_half_life_and_curve_multipliers():
    assert memory_curve.retention(1.0, 7 * 86_400, 7) == pytest.approx(0.5)
    assert memory_curve.importance_multiplier(0.5) == pytest.approx(1.0)
    assert memory_curve.importance_multiplier(1.0) == pytest.approx(4.0)
    assert memory_curve.importance_multiplier(0.0) == pytest.approx(0.25)
    assert memory_curve.initial_stability_days(0.5, "authored_event") == 14
    assert memory_curve.initial_stability_days(0.5, "player_message") == 10.5
    assert memory_curve.initial_stability_days(0.5, "legacy") == 7
    assert memory_curve.initial_stability_days(0.5, "model_inference") == 5.25
    assert memory_curve.candidate_importance(
        {"claim_id": "claim", "provenance": {}}, "player_fact"
    ) == 0.5
    assert memory_curve.candidate_importance(
        {"id": 1, "importance": 5}, "player_fact"
    ) == 0.5


@pytest.mark.parametrize(
    ("value", "clarity"),
    [
        (0.65, "clear"),
        (0.6499, "fuzzy"),
        (0.35, "fuzzy"),
        (0.3499, "fragment"),
        (0.15, "fragment"),
        (0.1499, "forgotten"),
    ],
)
def test_clarity_boundaries(value, clarity):
    assert memory_curve.clarity_for(value) == clarity


def test_reinforcement_restores_half_gap_and_caps_stability():
    strength, stability = memory_curve.reinforce(0.4, 300)
    assert strength == pytest.approx(0.7)
    assert stability == 365


def test_world_time_watermark_pause_jump_and_rollback_do_not_restore():
    identity = _identity()
    start = datetime(2026, 1, 1, tzinfo=UTC)
    repository.record_memory_curve_evidence(
        **identity,
        evidence_id="evidence-1",
        world_occurred_at=start.isoformat(),
        source_kind="legacy",
        importance=0.5,
    )

    paused = repository.advance_or_initialize_memory_curve_state(
        **identity,
        world_now=start.isoformat(),
        source_kind="legacy",
        importance=0.5,
    )
    assert paused["elapsed_decay_seconds"] == 0

    jumped = repository.advance_or_initialize_memory_curve_state(
        **identity,
        world_now=(start + timedelta(days=10)).isoformat(),
        source_kind="legacy",
        importance=0.5,
    )
    assert jumped["elapsed_decay_seconds"] == pytest.approx(10 * 86_400)
    before_rollback = memory_curve.state_retention(
        jumped, start + timedelta(days=10)
    )

    rolled_back = repository.advance_or_initialize_memory_curve_state(
        **identity,
        world_now=(start + timedelta(days=2)).isoformat(),
        source_kind="legacy",
        importance=0.5,
    )
    assert rolled_back["elapsed_decay_seconds"] == jumped["elapsed_decay_seconds"]
    assert memory_curve.state_retention(
        rolled_back, start + timedelta(days=2)
    ) == pytest.approx(before_rollback)

    forward_again = repository.advance_or_initialize_memory_curve_state(
        **identity,
        world_now=(start + timedelta(days=12)).isoformat(),
        source_kind="legacy",
        importance=0.5,
    )
    assert forward_again["elapsed_decay_seconds"] == pytest.approx(12 * 86_400)


def test_evidence_reinforcement_is_idempotent_and_character_scoped():
    identity = _identity()
    start = datetime(2026, 2, 1, tzinfo=UTC)
    repository.record_memory_curve_evidence(
        **identity,
        evidence_id="formation",
        world_occurred_at=start.isoformat(),
        source_kind="model_inference",
        importance=0.5,
    )
    later = (start + timedelta(days=7)).isoformat()
    strengthened = repository.record_memory_curve_evidence(
        **identity,
        evidence_id="new-message",
        world_occurred_at=later,
        source_kind="model_inference",
        importance=0.5,
    )
    duplicate = repository.record_memory_curve_evidence(
        **identity,
        evidence_id="new-message",
        world_occurred_at=later,
        source_kind="model_inference",
        importance=0.5,
    )
    assert strengthened["reinforcement_count"] == 1
    assert duplicate["reinforcement_count"] == 1
    assert strengthened["anchor_strength"] > 0.5
    assert strengthened["stability_days"] == pytest.approx(5.25 * 1.7)

    other = repository.get_memory_curve_state(
        identity["owner_user_id"],
        "another-character",
        identity["memory_type"],
        identity["memory_id"],
    )
    assert other is None


def test_concurrent_duplicate_evidence_reinforces_once():
    identity = _identity()
    start = datetime(2026, 3, 1, tzinfo=UTC)
    repository.record_memory_curve_evidence(
        **identity,
        evidence_id="formation",
        world_occurred_at=start.isoformat(),
        source_kind="legacy",
        importance=0.5,
    )
    kwargs = {
        **identity,
        "evidence_id": "concurrent-evidence",
        "world_occurred_at": (start + timedelta(days=3)).isoformat(),
        "source_kind": "legacy",
        "importance": 0.5,
    }
    with ThreadPoolExecutor(max_workers=4) as pool:
        states = list(pool.map(
            lambda _: repository.record_memory_curve_evidence(**kwargs),
            range(4),
        ))
    assert {state["reinforcement_count"] for state in states} == {1}


def test_deterministic_sampling_and_fuzzy_prompt():
    memory_id = "weak-memory"
    assert memory_curve.stable_sample("turn-1", memory_id) == (
        memory_curve.stable_sample("turn-1", memory_id)
    )
    samples = {
        memory_curve.stable_sample(f"turn-{index}", memory_id)
        for index in range(20)
    }
    assert len(samples) > 1
    assert "不确定表达" in memory_curve.prompt_memory_text("细节", "fuzzy")
    assert "不得主动断言" in memory_curve.prompt_memory_text("细节", "fragment")


def test_legacy_candidate_initializes_at_full_strength_on_first_recall():
    identity = _identity()
    records = [{"id": identity["memory_id"], "fact_text": "玩家喜欢茶", "importance": 5}]
    recalled = memory_curve.evaluate_records(
        records,
        owner_user_id=identity["owner_user_id"],
        character_id=identity["character_id"],
        memory_type="player_fact",
        world_now="2026-04-01T00:00:00+00:00",
        recall_key="turn-1",
        text_key="fact_text",
    )
    assert recalled[0]["retention"] == 1.0
    assert recalled[0]["clarity"] == "clear"


def test_feature_disabled_and_curve_failure_preserve_existing_recall(monkeypatch):
    from memoria.core import multi_character_memory

    records = [{"claim_id": "claim-1", "fact_text": "玩家喜欢茶"}]
    monkeypatch.setattr(
        multi_character_memory.repository,
        "get_prompt_memory_fact_records",
        lambda **kwargs: records,
    )
    monkeypatch.setattr(
        multi_character_memory.relationship_context,
        "filter_stale_relationship_memory_records",
        lambda candidate_records, *args, **kwargs: candidate_records,
    )
    monkeypatch.setattr(
        multi_character_memory.memory_curve,
        "evaluate_records",
        lambda *args, **kwargs: pytest.fail("disabled curve was evaluated"),
    )
    monkeypatch.setattr(
        multi_character_memory.configs, "memory_curve_enabled", False
    )
    assert multi_character_memory.load_player_memories_for_relationship_graph(
        "character-1", "owner-1", [], world_now="2026-01-01T00:00:00+00:00"
    ) == ["玩家喜欢茶"]

    monkeypatch.setattr(
        multi_character_memory.configs, "memory_curve_enabled", True
    )
    monkeypatch.setattr(
        multi_character_memory.memory_curve,
        "evaluate_records",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("curve down")),
    )
    assert multi_character_memory.load_player_memories_for_relationship_graph(
        "character-1", "owner-1", [], world_now="2026-01-01T00:00:00+00:00"
    ) == ["玩家喜欢茶"]


def test_developer_diagnostics_does_not_advance_curve(monkeypatch):
    from memoria.api import developer

    monkeypatch.setattr(
        developer.character_loader,
        "load_character_card",
        lambda character_id, owner_user_id: object(),
    )
    monkeypatch.setattr(developer.repository, "get_player_world_clock", lambda _: None)
    monkeypatch.setattr(
        developer.repository,
        "get_prompt_memory_fact_records",
        lambda **kwargs: [{"claim_id": "claim-1", "fact_text": "玩家喜欢茶", "source_kind": "legacy"}],
    )
    monkeypatch.setattr(
        developer.repository,
        "get_observer_character_impressions",
        lambda **kwargs: [],
    )
    monkeypatch.setattr(
        developer.repository,
        "get_character_group_memories",
        lambda **kwargs: [],
    )
    monkeypatch.setattr(
        developer.repository,
        "get_memory_curve_state",
        lambda *args: None,
    )
    monkeypatch.setattr(
        developer.repository,
        "advance_or_initialize_memory_curve_state",
        lambda **kwargs: pytest.fail("diagnostics advanced curve state"),
    )

    result = developer.memory_curve_diagnostics(
        character_id="character-1",
        session_id=None,
        recall_key="inspect-1",
        include_forgotten=True,
        current_user_id="owner-1",
    )
    assert result["items"][0]["text"] == "玩家喜欢茶"
    assert result["items"][0]["retention"] == 1.0
