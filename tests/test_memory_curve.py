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
    assert memory_curve.candidate_importance(
        {
            "claim_id": "authored",
            "provenance": {
                "evidence": [{
                    "source_kind": "authored_event",
                    "details": {"importance": 0.9},
                }],
            },
        },
        "player_fact",
    ) == 0.9
    assert memory_curve.candidate_importance(
        {
            "claim_id": "legacy",
            "provenance": {
                "evidence": [{
                    "source_kind": "legacy",
                    "details": {"importance": 9},
                }],
            },
        },
        "player_fact",
    ) == 0.9
    assert memory_curve.candidate_limit(0) == 20
    assert memory_curve.candidate_limit(10) == 30
    assert memory_curve.candidate_limit(20) == 60


def test_legacy_backfill_preserves_memory_identity():
    migrated = {
        "claim_id": "claim-new",
        "provenance": {
            "evidence": [{
                "source_kind": "legacy",
                "details": {
                    "legacy_backfill": True,
                    "legacy_fact_id": 42,
                },
            }],
        },
    }
    assert memory_curve.memory_identity(migrated, "player_fact") == "42"
    assert memory_curve.memory_identity(
        {"claim_id": "claim-new", "provenance": {}},
        "player_fact",
    ) == "claim-new"
    assert memory_curve.memory_identity(
        migrated,
        "character_impression",
    ) == "claim-new"


def test_memoria_memory_curve_environment_flag(monkeypatch):
    from memoria.core.config import Configs

    monkeypatch.setenv("MEMORIA_MEMORY_CURVE_ENABLED", "false")
    monkeypatch.setenv("MEMORY_CURVE_ENABLED", "true")

    assert Configs(_env_file=None).memory_curve_enabled is False
    assert Configs(
        _env_file=None,
        memory_curve_enabled=False,
    ).memory_curve_enabled is False


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
    assert stability == 510


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


def test_admin_verification_reinforces_existing_witness_state():
    from memoria.core.fact_claims import record_admin_verification
    from memoria.core.memory_extractor import record_generated_memory_claim

    suffix = uuid.uuid4().hex
    owner_user_id = f"admin-owner-{suffix}"
    character_id = f"admin-character-{suffix}"
    formed_at = datetime(2026, 2, 1, tzinfo=UTC)
    claim = record_generated_memory_claim(
        owner_user_id=owner_user_id,
        scope_type="character",
        scope_id=character_id,
        fact_text="玩家喜欢茉莉花茶",
        source_ids=["session:admin-review"],
        witness_character_ids=[character_id],
        evidence_id="message:formation",
        world_occurred_at=formed_at.isoformat(),
    )

    verified = record_admin_verification(
        owner_user_id,
        claim["claim_id"],
        source_ids=["admin:confirmation-1"],
        world_occurred_at=(formed_at + timedelta(days=7)).isoformat(),
    )
    strengthened = repository.get_memory_curve_state(
        owner_user_id,
        character_id,
        "player_fact",
        claim["claim_id"],
    )
    assert verified["status"] == "verified"
    assert strengthened["reinforcement_count"] == 1
    assert strengthened["stability_days"] == pytest.approx(5.25 * 1.7)

    record_admin_verification(
        owner_user_id,
        claim["claim_id"],
        source_ids=["admin:confirmation-1"],
        world_occurred_at=(formed_at + timedelta(days=7)).isoformat(),
    )
    duplicate = repository.get_memory_curve_state(
        owner_user_id,
        character_id,
        "player_fact",
        claim["claim_id"],
    )
    assert duplicate["reinforcement_count"] == 1


def test_admin_verification_reinforces_legacy_backfill_identity(monkeypatch):
    from memoria.core.fact_claims import record_admin_verification

    suffix = uuid.uuid4().hex
    owner_user_id = f"legacy-admin-owner-{suffix}"
    character_id = f"legacy-admin-character-{suffix}"
    claim_id = f"legacy-admin-claim-{suffix}"
    legacy_memory_id = "4242"
    formed_at = datetime(2026, 2, 1, tzinfo=UTC)
    claim = {
        "claim_id": claim_id,
        "owner_user_id": owner_user_id,
        "scope_type": "character",
        "scope_id": character_id,
        "fact_text": "旧事实",
        "normalized_fact_text": "旧事实",
        "content_hash": "content-hash",
        "normalized_content_hash": "normalized-hash",
        "provenance": {
            "evidence": [{
                "source_kind": "legacy",
                "details": {
                    "legacy_backfill": True,
                    "legacy_fact_id": int(legacy_memory_id),
                    "importance": 5,
                },
            }],
        },
    }
    repository.record_memory_curve_evidence(
        owner_user_id=owner_user_id,
        character_id=character_id,
        memory_type="player_fact",
        memory_id=legacy_memory_id,
        evidence_id="formation",
        world_occurred_at=formed_at.isoformat(),
        source_kind="legacy",
        importance=0.5,
    )
    monkeypatch.setattr(repository, "get_fact_claim", lambda *args: claim)
    monkeypatch.setattr(
        repository,
        "_record_fact_claim",
        lambda **kwargs: {**claim, "status": "verified"},
    )

    record_admin_verification(
        owner_user_id,
        claim_id,
        source_ids=["admin:legacy-confirmation"],
        world_occurred_at=(formed_at + timedelta(days=7)).isoformat(),
    )

    legacy_state = repository.get_memory_curve_state(
        owner_user_id,
        character_id,
        "player_fact",
        legacy_memory_id,
    )
    assert legacy_state["reinforcement_count"] == 1
    assert repository.get_memory_curve_state(
        owner_user_id,
        character_id,
        "player_fact",
        claim_id,
    ) is None


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


def test_distinct_persisted_pulses_reinforce_identical_memory(monkeypatch):
    from memoria.core import multi_character_memory

    suffix = uuid.uuid4().hex
    owner_user_id = f"pulse-owner-{suffix}"
    session_id = f"pulse-session-{suffix}"
    thread_id = f"pulse-thread-{suffix}"
    character_ids = [f"pulse-a-{suffix}", f"pulse-b-{suffix}"]
    assert repository.create_multi_character_session(
        session_id,
        owner_user_id,
        "Player",
        character_ids,
        group_thread_id=thread_id,
    )
    monkeypatch.setattr(
        multi_character_memory,
        "extract_dialogue_pulse_memories",
        lambda recent_messages, character_ids: {
            "player_facts": [],
            "shared_facts": ["众人确认夜间出发"],
            "secret_facts": [],
        },
    )
    first = [{
        "message_id": 101,
        "role": "assistant",
        "content": "同意。",
        "world_created_at": "2026-03-01T00:00:00+00:00",
    }]
    second = [{
        "message_id": 102,
        "role": "assistant",
        "content": "同意。",
        "world_created_at": "2026-03-08T00:00:00+00:00",
    }]
    multi_character_memory.process_dialogue_pulse_memories(
        session_id, first, character_ids, owner_user_id
    )
    multi_character_memory.process_dialogue_pulse_memories(
        session_id, second, character_ids, owner_user_id
    )
    claim = repository.list_fact_claims(
        owner_user_id,
        "group_thread",
        thread_id,
    )[0]
    state = repository.get_memory_curve_state(
        owner_user_id,
        character_ids[0],
        "player_fact",
        claim["claim_id"],
    )
    assert state["reinforcement_count"] == 1

    multi_character_memory.process_dialogue_pulse_memories(
        session_id, second, character_ids, owner_user_id
    )
    retry = repository.get_memory_curve_state(
        owner_user_id,
        character_ids[0],
        "player_fact",
        claim["claim_id"],
    )
    assert retry["reinforcement_count"] == 1


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
    requested_limits = []

    def load_records(**kwargs):
        requested_limits.append(kwargs["limit"])
        return records

    monkeypatch.setattr(
        multi_character_memory.repository,
        "get_prompt_memory_fact_records",
        load_records,
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
    assert requested_limits[-1] == 30

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
    assert requested_limits[-1] == 30


def test_single_context_curve_failure_restores_all_raw_records(monkeypatch):
    from types import SimpleNamespace
    from memoria.core import orchestrator

    character_id = "curve-fallback-character"
    owner_user_id = "curve-fallback-owner"
    raw_facts = [
        {"claim_id": f"fact-{index}", "fact_text": f"原始玩家事实 {index}"}
        for index in range(25)
    ]
    raw_shared = {
        "id": "shared-1",
        "character_a_id": character_id,
        "character_b_id": "other-character",
        "memory_text": "原始角色印象",
    }
    raw_group = {"id": "group-1", "memory_text": "原始群体经历"}
    requested_limits = {}

    monkeypatch.setattr(orchestrator.configs, "memory_curve_enabled", True)
    monkeypatch.setattr(
        orchestrator.repository,
        "list_character_relationships",
        lambda *args: [],
    )
    monkeypatch.setattr(
        orchestrator.repository,
        "list_character_relationship_revisions",
        lambda *args: [],
    )

    def load_shared(**kwargs):
        requested_limits["shared"] = kwargs["limit"]
        return [raw_shared]

    def load_group(*args, **kwargs):
        requested_limits["group"] = kwargs["limit"]
        return [raw_group]

    def load_facts(**kwargs):
        requested_limits["fact"] = kwargs["limit"]
        return raw_facts

    monkeypatch.setattr(
        orchestrator.repository,
        "get_character_shared_memories",
        load_shared,
    )
    monkeypatch.setattr(
        orchestrator,
        "_get_character_group_memories_for_player",
        load_group,
    )
    monkeypatch.setattr(
        orchestrator.repository,
        "get_prompt_memory_fact_records",
        load_facts,
    )
    monkeypatch.setattr(
        orchestrator.relationship_context,
        "filter_stale_relationship_memory_records",
        lambda records, *args, **kwargs: records,
    )
    calls = []

    def evaluate(records, **kwargs):
        calls.append(kwargs["memory_type"])
        if kwargs["memory_type"] == "character_impression":
            raise RuntimeError("curve down")
        text_key = kwargs["text_key"]
        result = [{**record, text_key: f"曲线:{record[text_key]}"} for record in records]
        limit = kwargs.get("limit")
        if limit is not None:
            result = result[:limit]
        return result

    monkeypatch.setattr(orchestrator.memory_curve, "evaluate_records", evaluate)
    card = SimpleNamespace(
        meta=SimpleNamespace(
            name=character_id,
            display_name=character_id,
            aliases=[],
        ),
    )

    context = orchestrator._load_single_character_prompt_context(
        character_id,
        owner_user_id,
        card,
        world_now="2026-01-01T00:00:00+00:00",
        recall_key="turn-1",
    )

    assert calls == ["player_fact", "character_impression", "group_experience"]
    # player_fact succeeded through curve, text was transformed
    assert context["known_player_facts"] == [
        f"曲线:原始玩家事实 {index}" for index in range(20)
    ]
    # character_impression failed, context manager fell back to originals
    assert "共享记忆（与other-character）：原始角色印象" in context[
        "cross_mode_memories"
    ]
    # group_experience succeeded through curve, text was transformed
    assert "群体记忆：曲线:原始群体经历" in context["cross_mode_memories"]
    assert requested_limits == {"shared": 60, "group": 60, "fact": 60}


def test_multi_context_overfetches_before_curve_ranking(monkeypatch):
    from memoria.core import multi_character_memory

    requested_limits = {}
    impressions = [
        {"id": f"impression-{index}", "memory_text": f"印象 {index}"}
        for index in range(20)
    ]
    groups = [
        {"id": f"group-{index}", "memory_text": f"经历 {index}"}
        for index in range(20)
    ]
    monkeypatch.setattr(multi_character_memory.configs, "memory_curve_enabled", True)
    monkeypatch.setattr(
        multi_character_memory,
        "load_player_memories_for_relationship_graph",
        lambda **kwargs: [],
    )

    def load_impressions(**kwargs):
        requested_limits["impressions"] = kwargs["limit"]
        return impressions

    def load_groups(**kwargs):
        requested_limits["groups"] = kwargs["limit"]
        requested_limits["group_owner"] = kwargs["owner_user_id"]
        return groups

    monkeypatch.setattr(
        multi_character_memory.repository,
        "get_character_impressions",
        load_impressions,
    )
    monkeypatch.setattr(
        multi_character_memory.repository,
        "get_session_group_memories",
        load_groups,
    )
    monkeypatch.setattr(
        multi_character_memory.relationship_context,
        "filter_stale_relationship_memory_records",
        lambda records, *args, **kwargs: records,
    )
    monkeypatch.setattr(
        multi_character_memory,
        "_relationship_updated_at_for_pair",
        lambda *args: None,
    )
    seen = {}

    def evaluate(records, **kwargs):
        seen[kwargs["memory_type"]] = (len(records), kwargs["limit"])
        return list(reversed(records))[:kwargs["limit"]]

    monkeypatch.setattr(multi_character_memory.memory_curve, "evaluate_records", evaluate)

    context = multi_character_memory.integrate_multi_character_context(
        character_id="character-a",
        player_id="owner-a",
        session_id="session-a",
        other_character_ids=["character-b"],
        character_relationships={},
        world_now="2026-01-01T00:00:00+00:00",
        recall_key="turn-1",
    )

    assert requested_limits == {
        "impressions": 20,
        "groups": 20,
        "group_owner": "owner-a",
    }
    assert seen == {
        "character_impression": (20, 3),
        "group_experience": (20, 5),
    }
    assert context["character_impressions"]["character-b"][0] == "印象 19"
    assert context["group_memories"][0] == "经历 19"


def test_feature_disabled_preserves_multi_opening_prompt(monkeypatch):
    from types import SimpleNamespace
    from memoria.core import multi_character_orchestrator as module

    character_id = "opening-character"
    card = SimpleNamespace(
        meta=SimpleNamespace(name="角色", display_name="角色"),
        action_vocabulary=SimpleNamespace(default_action="idle"),
    )
    orchestrator = module.MultiCharacterOrchestrator.__new__(
        module.MultiCharacterOrchestrator
    )
    orchestrator.player_id = "opening-owner"
    orchestrator.player_name = "Player"
    orchestrator.player_character = {"display_name": "Player"}
    orchestrator.session_id = "opening-session"
    orchestrator.character_ids = [character_id]
    orchestrator.character_cards = {character_id: card}
    orchestrator.locale = "zh-CN"
    monkeypatch.setattr(orchestrator, "_refresh_player_character", lambda: None)
    monkeypatch.setattr(orchestrator, "_load_all_relationships", lambda: {})
    monkeypatch.setattr(
        orchestrator,
        "_load_runtime_state_for_prompt",
        lambda *args, **kwargs: {
            "affection_level": 0,
            "trust_level": 0,
            "current_mood": "neutral",
            "known_player_facts": [],
        },
    )
    monkeypatch.setattr(
        orchestrator,
        "_load_memory_context",
        lambda *args, **kwargs: pytest.fail(
            "disabled opening loaded memory context"
        ),
    )
    monkeypatch.setattr(module.configs, "memory_curve_enabled", False)
    captured = {}
    monkeypatch.setattr(
        module,
        "_build_multi_character_system_prompt",
        lambda **kwargs: captured.update(kwargs) or "prompt",
    )
    monkeypatch.setattr(
        module.llm_client,
        "call_role_turn",
        lambda **kwargs: {"dialogue": "你好", "action": "idle"},
    )
    monkeypatch.setattr(
        module.repository,
        "get_last_character_interaction_world_at",
        lambda *args: None,
    )
    monkeypatch.setattr(
        module.repository,
        "append_multi_character_message",
        lambda *args, **kwargs: 1,
    )
    world_now = datetime(2026, 4, 1, tzinfo=UTC)
    clock_snapshot = SimpleNamespace(
        world_now=world_now,
        prompt_context=lambda *args, **kwargs: {},
    )

    orchestrator._generate_opening(
        character_id,
        clock_snapshot=clock_snapshot,
    )
    assert "past_summaries" not in captured


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


def test_developer_diagnostics_marks_stale_relationship_memory(monkeypatch):
    from types import SimpleNamespace
    from memoria.api import developer

    monkeypatch.setattr(
        developer.character_loader,
        "load_character_card",
        lambda character_id, owner_user_id: SimpleNamespace(
            meta=SimpleNamespace(name=character_id, display_name=character_id)
        ),
    )
    monkeypatch.setattr(developer.repository, "get_player_world_clock", lambda _: None)
    monkeypatch.setattr(
        developer.repository,
        "get_prompt_memory_fact_records",
        lambda **kwargs: [{
            "claim_id": "stale-claim",
            "fact_text": "character-1 与 other-1 是朋友",
            "source_kind": "legacy",
            "created_at": "2026-01-01T00:00:00+00:00",
        }],
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
        "list_character_relationships",
        lambda *args: [],
    )
    monkeypatch.setattr(
        developer.repository,
        "list_character_relationship_revisions",
        lambda *args: [{
            "character_id_a": "character-1",
            "character_id_b": "other-1",
            "updated_at": "2026-02-01T00:00:00+00:00",
        }],
    )
    monkeypatch.setattr(
        developer.repository,
        "get_character_relationship_updated_at",
        lambda *args: "2026-02-01T00:00:00+00:00",
    )
    monkeypatch.setattr(
        developer.repository,
        "get_memory_curve_state",
        lambda *args: None,
    )

    result = developer.memory_curve_diagnostics(
        character_id="character-1",
        session_id=None,
        recall_key="inspect-stale",
        include_forgotten=True,
        current_user_id="owner-1",
    )
    assert result["items"][0]["sampled"] is False
    assert result["items"][0]["exclusion_reason"] == (
        "stale_relationship_history"
    )


# ──────────────────────────────────────────────────────────────
# Tests for new features
# ──────────────────────────────────────────────────────────────
def test_batch_advance_or_initialize(monkeypatch):
    """Fix 1: batch upsert works in a single transaction."""
    from memoria.db import repository as repo

    uid = "batch-test-user"
    cid = "batch-test-char"
    start = datetime(2026, 1, 1, tzinfo=UTC)

    items = [
        {"memory_id": f"mem-{i}", "world_now": start.isoformat(),
         "source_kind": "legacy", "importance": 0.5}
        for i in range(10)
    ]
    states = repo.batch_advance_or_initialize_memory_curve_states(
        owner_user_id=uid, character_id=cid,
        memory_type="player_fact", items=items,
    )
    assert len(states) == 10
    for mid, state in states.items():
        assert state["anchor_strength"] == 1.0
        assert state["owner_user_id"] == uid

    # Second call should advance, not re-initialize
    future = start + timedelta(days=5)
    items2 = [
        {"memory_id": f"mem-{i}", "world_now": future.isoformat(),
         "source_kind": "legacy", "importance": 0.5}
        for i in range(10)
    ]
    states2 = repo.batch_advance_or_initialize_memory_curve_states(
        owner_user_id=uid, character_id=cid,
        memory_type="player_fact", items=items2,
    )
    assert len(states2) == 10
    for mid, state in states2.items():
        assert state["elapsed_decay_seconds"] == pytest.approx(5 * 86400)


def test_configurable_clarity_thresholds(monkeypatch):
    """Fix 8: clarity boundaries follow config values."""
    from memoria.core.config import Configs

    cfg = Configs(
        _env_file=None,
        memory_curve_clarity_clear=0.80,
        memory_curve_clarity_fuzzy=0.50,
        memory_curve_clarity_fragment=0.25,
    )
    monkeypatch.setattr(memory_curve, "_cfg", lambda: cfg)

    assert memory_curve.clarity_for(0.80) == "clear"
    assert memory_curve.clarity_for(0.79) == "fuzzy"
    assert memory_curve.clarity_for(0.50) == "fuzzy"
    assert memory_curve.clarity_for(0.49) == "fragment"
    assert memory_curve.clarity_for(0.25) == "fragment"
    assert memory_curve.clarity_for(0.24) == "forgotten"


def test_configurable_rank_weights(monkeypatch):
    """Fix 2: rank weights follow config values."""
    from memoria.core.config import Configs

    cfg = Configs(
        _env_file=None,
        memory_curve_rank_weight_relevance=0.30,
        memory_curve_rank_weight_retention=0.50,
        memory_curve_rank_weight_importance=0.20,
    )
    monkeypatch.setattr(memory_curve, "_cfg", lambda: cfg)

    # total=2, first item: relevance=1.0, retention=0.5, importance=0.5
    score = memory_curve.rank_score(0, 2, 0.5, 0.5)
    expected = 0.30 * 1.0 + 0.50 * 0.5 + 0.20 * 0.5
    assert score == pytest.approx(expected)


def test_permanent_threshold_pins_retention():
    """Fix 7: memories with very high stability are pinned to 1.0."""
    # High stability + few elapsed days → raw retention > 0.95 → pinned to 1.0
    state = {
        "anchor_strength": 1.0,
        "stability_days": 730.0 * 0.96,  # above 95% of max (730)
        "anchor_elapsed_seconds": 0.0,
        "elapsed_decay_seconds": 10 * 86400,  # only 10 days
        "world_time_watermark": "2026-01-01T00:00:00+00:00",
        "reinforcement_count": 5,
    }
    # raw retention = 1/(1+10/700.8) ≈ 0.986, above 0.95 → pinned to 1.0
    r = memory_curve.state_retention(state, "2026-01-11T00:00:00+00:00")
    assert r == 1.0

    # High stability but raw retention below threshold → NOT pinned
    state["elapsed_decay_seconds"] = 365 * 86400  # 1 year
    r2 = memory_curve.state_retention(state, "2027-01-01T00:00:00+00:00")
    assert r2 < 1.0  # raw ≈ 0.657, below 0.95

    # Low stability should NOT be pinned regardless
    state["stability_days"] = 7.0
    state["elapsed_decay_seconds"] = 1 * 86400
    r_normal = memory_curve.state_retention(state, "2026-01-02T00:00:00+00:00")
    assert r_normal < 1.0


def test_cleanup_forgotten_states():
    """Fix 5: forgotten states can be cleaned up."""
    from memoria.db import repository as repo

    uid = "cleanup-test-user"
    cid = "cleanup-test-char"

    # Create a state that's been "forgotten" for a long time
    repo.initialize_memory_curve_state(
        owner_user_id=uid, character_id=cid,
        memory_type="player_fact", memory_id="old-forgotten",
        world_occurred_at="2020-01-01T00:00:00+00:00",
        source_kind="legacy", importance=0.1,
    )
    # Manually set updated_at far in the past and high elapsed
    with repo.get_conn() as conn:
        conn.execute(
            "UPDATE memory_curve_state SET updated_at = ?, elapsed_decay_seconds = ? "
            "WHERE owner_user_id = ? AND memory_id = ?",
            ("2020-01-01T00:00:00", 1000 * 86400, uid, "old-forgotten"),
        )

    # Create a recent state that should NOT be cleaned
    repo.initialize_memory_curve_state(
        owner_user_id=uid, character_id=cid,
        memory_type="player_fact", memory_id="recent-active",
        world_occurred_at="2026-07-01T00:00:00+00:00",
        source_kind="player_message", importance=0.9,
    )

    deleted = memory_curve.cleanup_forgotten_states(owner_user_id=uid)
    assert deleted >= 1
    assert repo.get_memory_curve_state(uid, cid, "player_fact", "old-forgotten") is None
    assert repo.get_memory_curve_state(uid, cid, "player_fact", "recent-active") is not None


# ──────────────────────────────────────────────────────────────
# Fix 6: additional test coverage for blind spots
# ──────────────────────────────────────────────────────────────
def test_volatile_sample_varies_across_turns():
    """Fix 2: volatile_sample produces different results with different turn_salts."""
    key = "session-abc"
    mid = "memory-xyz"
    s1 = memory_curve.volatile_sample(key, mid, "salt-A")
    s2 = memory_curve.volatile_sample(key, mid, "salt-B")
    # Extremely unlikely to be equal with different salts
    assert s1 != s2
    # But same triple is deterministic
    assert memory_curve.volatile_sample(key, mid, "salt-A") == s1


def test_volatile_and_stable_differ():
    """stable_sample (legacy) and volatile_sample produce different distributions."""
    key = "session-abc"
    mid = "memory-xyz"
    stable = memory_curve.stable_sample(key, mid)
    volatile = memory_curve.volatile_sample(key, mid, "some-salt")
    # Not guaranteed different for every input, but for this specific input they should differ
    assert stable != volatile


def test_cleanup_cascades_reinforcement_rows():
    """Fix 5/6: deleting a curve state also deletes its reinforcement rows."""
    from memoria.db import repository as repo

    uid = "cascade-test-user"
    cid = "cascade-test-char"
    mid = "cascade-memory"

    repo.record_memory_curve_evidence(
        owner_user_id=uid, character_id=cid,
        memory_type="player_fact", memory_id=mid,
        evidence_id="ev-1", world_occurred_at="2020-01-01T00:00:00+00:00",
        source_kind="legacy", importance=0.1,
    )
    repo.record_memory_curve_evidence(
        owner_user_id=uid, character_id=cid,
        memory_type="player_fact", memory_id=mid,
        evidence_id="ev-2", world_occurred_at="2020-06-01T00:00:00+00:00",
        source_kind="legacy", importance=0.1,
    )
    # Verify reinforcement rows exist
    with repo.get_conn() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM memory_curve_reinforcement "
            "WHERE owner_user_id = ? AND memory_id = ?",
            (uid, mid),
        ).fetchone()[0]
    assert count == 2

    # Mark as old so cleanup picks it up
    with repo.get_conn() as conn:
        conn.execute(
            "UPDATE memory_curve_state SET updated_at = ?, elapsed_decay_seconds = ? "
            "WHERE owner_user_id = ? AND memory_id = ?",
            ("2020-01-01T00:00:00", 2000 * 86400, uid, mid),
        )

    deleted = memory_curve.cleanup_forgotten_states(owner_user_id=uid)
    assert deleted >= 1

    # State should be gone
    assert repo.get_memory_curve_state(uid, cid, "player_fact", mid) is None
    # Reinforcement rows should also be cleaned (cascade via FK or explicit delete)
    with repo.get_conn() as conn:
        count_after = conn.execute(
            "SELECT COUNT(*) FROM memory_curve_reinforcement "
            "WHERE owner_user_id = ? AND memory_id = ?",
            (uid, mid),
        ).fetchone()[0]
    # Note: SQLite does not enforce FK cascades by default; the cleanup function
    # must handle this explicitly. If it does, count_after == 0.
    # If FK cascades are enabled (PostgreSQL), count_after == 0 automatically.
    assert count_after == 0


def test_permanent_threshold_reached_via_reinforcement():
    """Fix 6: repeated reinforcement eventually triggers permanent pin."""
    from memoria.db import repository as repo

    uid = "perm-reinforce-user"
    cid = "perm-reinforce-char"
    mid = "perm-reinforce-memory"
    start = datetime(2026, 1, 1, tzinfo=UTC)

    # Initial state with high importance authored_event
    repo.record_memory_curve_evidence(
        owner_user_id=uid, character_id=cid,
        memory_type="player_fact", memory_id=mid,
        evidence_id="ev-init", world_occurred_at=start.isoformat(),
        source_kind="authored_event", importance=0.9,
    )

    # Reinforce frequently (every 3 days) to keep retention high while building stability
    for i in range(1, 20):
        t = start + timedelta(days=i * 3)
        repo.record_memory_curve_evidence(
            owner_user_id=uid, character_id=cid,
            memory_type="player_fact", memory_id=mid,
            evidence_id=f"ev-{i}", world_occurred_at=t.isoformat(),
            source_kind="authored_event", importance=0.9,
        )

    state = repo.get_memory_curve_state(uid, cid, "player_fact", mid)
    assert state["reinforcement_count"] == 19
    assert state["stability_days"] >= 730 * 0.95  # near max

    # Check that retention is pinned to 1.0 when raw retention is still >= threshold
    # At day 57 (last anchor), raw retention = 1.0, which is >= 0.95 → pinned
    r_at_anchor = memory_curve.state_retention(state, (start + timedelta(days=57)).isoformat())
    assert r_at_anchor == 1.0
    # At day 100, raw retention = 1/(1+43/730) ≈ 0.944, below 0.95 → not pinned
    # At day 60, raw retention = 1/(1+3/730) ≈ 0.996, >= 0.95 → pinned
    r_near = memory_curve.state_retention(state, (start + timedelta(days=60)).isoformat())
    assert r_near == 1.0


def test_batch_advance_partial_items():
    """Fix 6: batch handles a mix of new and existing states correctly."""
    from memoria.db import repository as repo

    uid = "batch-partial-user"
    cid = "batch-partial-char"
    start = datetime(2026, 1, 1, tzinfo=UTC)

    # Pre-initialize one state
    repo.initialize_memory_curve_state(
        owner_user_id=uid, character_id=cid,
        memory_type="player_fact", memory_id="existing-mem",
        world_occurred_at=start.isoformat(),
        source_kind="legacy", importance=0.5,
    )

    # Batch with mix of existing and new
    future = start + timedelta(days=5)
    items = [
        {"memory_id": "existing-mem", "world_now": future.isoformat(),
         "source_kind": "legacy", "importance": 0.5},
        {"memory_id": "brand-new-mem", "world_now": future.isoformat(),
         "source_kind": "player_message", "importance": 0.8},
    ]
    states = repo.batch_advance_or_initialize_memory_curve_states(
        owner_user_id=uid, character_id=cid,
        memory_type="player_fact", items=items,
    )
    assert len(states) == 2
    # Existing should have advanced
    assert states["existing-mem"]["elapsed_decay_seconds"] == pytest.approx(5 * 86400)
    # New should be initialized
    assert states["brand-new-mem"]["anchor_strength"] == 1.0
    assert states["brand-new-mem"]["elapsed_decay_seconds"] == 0.0


def test_config_cache_reset_for_tests(monkeypatch):
    """Fix 4: _reset_cfg_cache allows monkeypatching to take effect."""
    from memoria.core.config import Configs

    # Direct call uses cached config
    r1 = memory_curve.clarity_for(0.5)

    # Monkeypatch and reset cache
    cfg = Configs(
        _env_file=None,
        memory_curve_clarity_clear=0.90,
        memory_curve_clarity_fuzzy=0.70,
        memory_curve_clarity_fragment=0.50,
    )
    memory_curve._reset_cfg_cache()
    monkeypatch.setattr(memory_curve, "_cfg", lambda: cfg)

    r2 = memory_curve.clarity_for(0.5)
    assert r1 == "fuzzy"  # default thresholds
    assert r2 == "fragment"  # shifted thresholds

    # Restore
    memory_curve._reset_cfg_cache()
