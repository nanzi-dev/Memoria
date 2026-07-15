import sqlite3
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from memoria.db import repository


@pytest.fixture
def owner_user_id():
    user_id = f"fact_owner_{uuid4().hex}"
    repository.create_user(
        user_id,
        f"fact_user_{uuid4().hex}",
        "test-hash",
    )
    return user_id


def _record(
    owner_user_id,
    fact_text,
    *,
    source_kind,
    source_ids,
    scope_type="story",
    scope_id="graytide",
    direct_support=False,
    provenance=None,
):
    from memoria.core.fact_claims import record_claim

    return record_claim(
        owner_user_id,
        scope_type,
        scope_id,
        fact_text,
        source_kind=source_kind,
        source_ids=source_ids,
        direct_support=direct_support,
        provenance=provenance,
    )


def _events(owner_user_id, claim_id):
    return repository.list_domain_events(
        owner_user_id,
        "fact_claim",
        claim_id,
    )


def _replay_fact_claim(owner_user_id, claim_id):
    events = _events(owner_user_id, claim_id)
    with repository.get_conn() as conn:
        conn.execute(
            "DELETE FROM fact_claim WHERE owner_user_id = ? AND claim_id = ?",
            (owner_user_id, claim_id),
        )
        for event in events:
            repository._project_fact_claim_event(event, conn=conn)
    return repository.list_fact_claims(
        owner_user_id,
        "story",
        "graytide",
    )[0]


def test_model_inference_is_always_candidate(owner_user_id):
    claim = _record(
        owner_user_id,
        "第十三声来自地下传动轴。",
        source_kind="model_inference",
        source_ids=["turn-1", "turn-2"],
        direct_support=True,
    )

    assert claim["status"] == "candidate"
    assert [event.event_type for event in _events(owner_user_id, claim["claim_id"])] == [
        "fact.claimed.v1",
    ]
    assert repository.list_verified_fact_claims(
        owner_user_id,
        "story",
        "graytide",
    ) == []


def test_generated_single_character_memory_is_character_candidate(
    owner_user_id,
):
    from memoria.core import memory_extractor

    record_generated_memory_claim = getattr(
        memory_extractor,
        "record_generated_memory_claim",
        None,
    )

    assert callable(record_generated_memory_claim)
    claim = record_generated_memory_claim(
        owner_user_id=owner_user_id,
        scope_type="character",
        scope_id="npc_graytide",
        fact_text="玩家偏好在清晨调查港口。",
        source_ids=["session:single-session"],
        provenance={"session_id": "single-session"},
    )

    assert claim["status"] == "candidate"
    assert claim["scope_type"] == "character"
    assert claim["scope_id"] == "npc_graytide"
    assert claim["owner_user_id"] == owner_user_id
    assert claim["source_kind"] == "model_inference"
    assert repository.list_fact_claims(
        owner_user_id,
        "character",
        "npc_graytide",
    ) == [claim]


def test_default_group_session_uses_distinct_logical_thread_for_generated_claim(
    owner_user_id,
    monkeypatch,
):
    from memoria.core import multi_character_memory

    session_id = f"graytide-group-{uuid4().hex}"
    assert repository.create_multi_character_session(
        session_id,
        owner_user_id,
        "Thread Tester",
        ["character-a", "character-b"],
    )
    session = repository.get_session(session_id)

    monkeypatch.setattr(
        multi_character_memory,
        "extract_dialogue_pulse_memories",
        lambda recent_messages, character_ids: {
            "player_facts": [],
            "shared_facts": ["调查组决定先检查东侧闸门。"],
            "secret_facts": [],
            "character_impressions": [],
        },
    )

    multi_character_memory.process_dialogue_pulse_memories(
        session_id=session_id,
        recent_messages=[{"role": "user", "content": "先检查东侧闸门。"}],
        character_ids=["character-a", "character-b"],
        player_id=owner_user_id,
    )

    assert session["group_thread_id"]
    assert session["group_thread_id"] != session_id
    claims = repository.list_fact_claims(
        owner_user_id,
        "group_thread",
        session["group_thread_id"],
    )
    assert len(claims) == 1
    assert claims[0]["fact_text"] == "调查组决定先检查东侧闸门。"
    assert claims[0]["status"] == "candidate"


def test_multi_session_persists_real_story_scope(owner_user_id):
    session_id = f"graytide-story-session-{uuid4().hex}"
    story_id = f"graytide-story-{uuid4().hex}"

    assert repository.create_multi_character_session(
        session_id,
        owner_user_id,
        "Story Tester",
        ["character-a", "character-b"],
        story_id=story_id,
    )

    assert repository.get_session(session_id)["story_id"] == story_id


def test_continued_group_session_inherits_thread_story_scope(owner_user_id):
    character_id = "character-story-continuation"
    group_thread_id = f"thread-story-{uuid4().hex}"
    story_id = f"story-continuation-{uuid4().hex}"
    first_session_id = f"story-first-{uuid4().hex}"
    second_session_id = f"story-second-{uuid4().hex}"
    assert repository.create_multi_character_session(
        first_session_id,
        owner_user_id,
        "Story Continuation Tester",
        [character_id, "character-b"],
        group_thread_id=group_thread_id,
        story_id=story_id,
    )
    story_claim = _record(
        owner_user_id,
        "灰潮港的旧泵站属于当前故事。",
        source_kind="authored_event",
        source_ids=["story-continuation-event"],
        scope_type="story",
        scope_id=story_id,
    )

    assert repository.create_multi_character_session(
        second_session_id,
        owner_user_id,
        "Story Continuation Tester",
        [character_id, "character-b"],
        group_thread_id=group_thread_id,
    )

    assert repository.get_session(second_session_id)["story_id"] == story_id
    records = repository.get_prompt_memory_fact_records(
        character_id=character_id,
        player_id=owner_user_id,
        session_id=second_session_id,
        limit=5,
    )
    assert story_claim["fact_text"] in [
        record["fact_text"] for record in records
    ]


def test_prompt_memory_merges_only_applicable_verified_claims(
    owner_user_id,
    monkeypatch,
):
    from memoria.core.fact_claims import retract_claim, supersede_claim

    character_id = "npc_graytide"
    group_thread_id = "graytide-thread"
    story_id = "graytide-story"
    session_id = "graytide-session"

    verified_character = _record(
        owner_user_id,
        "玩家会在清晨检查潮位。",
        source_kind="authored_event",
        source_ids=["event-character"],
        scope_type="character",
        scope_id=character_id,
    )
    verified_group = _record(
        owner_user_id,
        "调查组已取得泵站通行证。",
        source_kind="authored_event",
        source_ids=["event-group"],
        scope_type="group_thread",
        scope_id=group_thread_id,
    )
    verified_story = _record(
        owner_user_id,
        "灰潮港的东侧闸门已经封闭。",
        source_kind="authored_event",
        source_ids=["event-story"],
        scope_type="story",
        scope_id=story_id,
    )
    candidate = _record(
        owner_user_id,
        "模型猜测港务长隐瞒了日志。",
        source_kind="model_inference",
        source_ids=["model-turn"],
        scope_type="character",
        scope_id=character_id,
    )
    retracted = _record(
        owner_user_id,
        "旧通行证仍然有效。",
        source_kind="authored_event",
        source_ids=["event-retracted"],
        scope_type="group_thread",
        scope_id=group_thread_id,
    )
    retract_claim(owner_user_id, retracted["claim_id"])
    superseded = _record(
        owner_user_id,
        "旧航道经过北侧隧道。",
        source_kind="authored_event",
        source_ids=["route-old"],
        scope_type="story",
        scope_id=story_id,
    )
    replacement = _record(
        owner_user_id,
        "新航道经过南侧隧道。",
        source_kind="authored_event",
        source_ids=["route-new"],
        scope_type="story",
        scope_id=story_id,
    )
    supersede_claim(
        owner_user_id,
        superseded["claim_id"],
        replacement["claim_id"],
    )
    _record(
        owner_user_id,
        "其他故事中的事实。",
        source_kind="authored_event",
        source_ids=["other-story"],
        scope_type="story",
        scope_id="other-story",
    )

    monkeypatch.setattr(
        repository,
        "get_session",
        lambda requested_session_id: {
            "session_id": requested_session_id,
            "player_id": owner_user_id,
            "is_multi_character": 1,
            "group_thread_id": group_thread_id,
            "story_id": story_id,
        },
    )

    records = repository.get_prompt_memory_fact_records(
        character_id=character_id,
        player_id=owner_user_id,
        session_id=session_id,
        limit=20,
    )

    texts = [record["fact_text"] for record in records]
    assert set(texts) == {
        verified_character["fact_text"],
        verified_group["fact_text"],
        verified_story["fact_text"],
        replacement["fact_text"],
    }
    assert candidate["fact_text"] not in texts
    assert retracted["fact_text"] not in texts
    assert superseded["fact_text"] not in texts


def test_prompt_memory_round_robins_recent_verified_claims_across_scopes(
    owner_user_id,
):
    character_id = "character-fair-order"
    group_thread_id = f"thread-fair-{uuid4().hex}"
    story_id = f"story-fair-{uuid4().hex}"
    session_id = f"session-fair-{uuid4().hex}"
    assert repository.create_multi_character_session(
        session_id,
        owner_user_id,
        "Fair Order Tester",
        [character_id, "character-b"],
        group_thread_id=group_thread_id,
        story_id=story_id,
    )

    character_claims = [
        _record(
            owner_user_id,
            f"角色范围事实 {index}。",
            source_kind="authored_event",
            source_ids=[f"character-event-{index}"],
            scope_type="character",
            scope_id=character_id,
        )
        for index in range(1, 6)
    ]
    group_claim = _record(
        owner_user_id,
        "群聊范围事实。",
        source_kind="authored_event",
        source_ids=["group-event"],
        scope_type="group_thread",
        scope_id=group_thread_id,
    )
    story_claim = _record(
        owner_user_id,
        "故事范围事实。",
        source_kind="authored_event",
        source_ids=["story-event"],
        scope_type="story",
        scope_id=story_id,
    )

    records = repository.get_prompt_memory_fact_records(
        character_id=character_id,
        player_id=owner_user_id,
        session_id=session_id,
        limit=5,
    )

    assert [record["fact_text"] for record in records] == [
        character_claims[4]["fact_text"],
        group_claim["fact_text"],
        story_claim["fact_text"],
        character_claims[3]["fact_text"],
        character_claims[2]["fact_text"],
    ]


def test_generated_group_candidate_reaches_prompt_only_after_verification(
    owner_user_id,
    monkeypatch,
):
    from memoria.core import multi_character_memory
    from memoria.core.fact_claims import record_admin_verification

    session_id = f"generated-prompt-{uuid4().hex}"
    fact_text = "调查组决定在退潮时检查旧泵站。"
    assert repository.create_multi_character_session(
        session_id,
        owner_user_id,
        "Verification Tester",
        ["character-a", "character-b"],
    )
    monkeypatch.setattr(
        multi_character_memory,
        "extract_dialogue_pulse_memories",
        lambda recent_messages, character_ids: {
            "player_facts": [],
            "shared_facts": [fact_text],
            "secret_facts": [],
        },
    )

    multi_character_memory.process_dialogue_pulse_memories(
        session_id=session_id,
        recent_messages=[{"role": "user", "content": "退潮时检查旧泵站。"}],
        character_ids=["character-a", "character-b"],
        player_id=owner_user_id,
    )
    thread_id = repository.get_group_thread_id(session_id)
    candidate = repository.list_fact_claims(
        owner_user_id,
        "group_thread",
        thread_id,
    )[0]

    before = multi_character_memory.integrate_multi_character_context(
        character_id="character-a",
        player_id=owner_user_id,
        session_id=session_id,
        other_character_ids=["character-b"],
    )
    record_admin_verification(
        owner_user_id,
        candidate["claim_id"],
        source_ids=["admin-verifier"],
    )
    after = multi_character_memory.integrate_multi_character_context(
        character_id="character-a",
        player_id=owner_user_id,
        session_id=session_id,
        other_character_ids=["character-b"],
    )

    assert candidate["status"] == "candidate"
    assert fact_text not in before["player_memories"]
    assert fact_text in after["player_memories"]


def test_generated_secret_claim_is_authorized_in_real_prompt_path(
    owner_user_id,
    monkeypatch,
):
    from memoria.core import multi_character_memory
    from memoria.core.fact_claims import record_admin_verification

    session_id = f"secret-prompt-{uuid4().hex}"
    secret_text = "备用密钥藏在钟楼齿轮箱内。"
    assert repository.create_multi_character_session(
        session_id,
        owner_user_id,
        "Secret Tester",
        ["character-a", "character-b"],
    )
    monkeypatch.setattr(
        multi_character_memory,
        "extract_dialogue_pulse_memories",
        lambda recent_messages, character_ids: {
            "player_facts": [],
            "shared_facts": [],
            "secret_facts": [
                {
                    "fact": secret_text,
                    "allowed_character_ids": ["character-a"],
                }
            ],
        },
    )

    multi_character_memory.process_dialogue_pulse_memories(
        session_id=session_id,
        recent_messages=[{"role": "user", "content": "只告诉甲密钥位置。"}],
        character_ids=["character-a", "character-b"],
        player_id=owner_user_id,
    )
    thread_id = repository.get_group_thread_id(session_id)
    candidate = repository.list_fact_claims(
        owner_user_id,
        "group_thread",
        thread_id,
    )[0]
    record_admin_verification(
        owner_user_id,
        candidate["claim_id"],
        source_ids=["admin-verifier"],
    )

    allowed_context = multi_character_memory.integrate_multi_character_context(
        character_id="character-a",
        player_id=owner_user_id,
        session_id=session_id,
        other_character_ids=["character-b"],
    )
    denied_context = multi_character_memory.integrate_multi_character_context(
        character_id="character-b",
        player_id=owner_user_id,
        session_id=session_id,
        other_character_ids=["character-a"],
    )

    assert secret_text in allowed_context["player_memories"]
    assert secret_text not in denied_context["player_memories"]


def test_prompt_memory_filters_verified_group_secret_by_allowed_character(
    owner_user_id,
    monkeypatch,
):
    group_thread_id = "graytide-secret-thread"
    session_id = "graytide-secret-session"
    public_claim = _record(
        owner_user_id,
        "调查组知道东侧闸门已关闭。",
        source_kind="authored_event",
        source_ids=["public-event"],
        scope_type="group_thread",
        scope_id=group_thread_id,
    )
    secret_claim = _record(
        owner_user_id,
        "只有甲知道备用密钥藏在钟楼。",
        source_kind="authored_event",
        source_ids=["secret-event"],
        scope_type="group_thread",
        scope_id=group_thread_id,
        provenance={
            "memory_kind": "secret_fact",
            "allowed_character_ids": ["character-a"],
        },
    )
    monkeypatch.setattr(
        repository,
        "get_session",
        lambda requested_session_id: {
            "session_id": requested_session_id,
            "player_id": owner_user_id,
            "is_multi_character": 1,
            "group_thread_id": group_thread_id,
        },
    )

    allowed_records = repository.get_prompt_memory_fact_records(
        character_id="character-a",
        player_id=owner_user_id,
        session_id=session_id,
        limit=20,
    )
    denied_records = repository.get_prompt_memory_fact_records(
        character_id="character-b",
        player_id=owner_user_id,
        session_id=session_id,
        limit=20,
    )

    assert [record["fact_text"] for record in allowed_records] == [
        secret_claim["fact_text"],
        public_claim["fact_text"],
    ]
    assert [record["fact_text"] for record in denied_records] == [
        public_claim["fact_text"],
    ]


def test_prompt_memory_legacy_compatibility_stops_after_backfill_marker(
    owner_user_id,
    monkeypatch,
):
    character_id = "npc_graytide_legacy"
    session_id = "graytide-legacy-session"
    marker = "2026-07-15-long-term-fact-event-backfill"
    repository.create_session(
        session_id,
        character_id,
        owner_user_id,
        "Legacy Tester",
    )
    repository.save_long_term_fact(
        character_id,
        owner_user_id,
        "迁移前仍可读取的旧长期记忆。",
    )
    verified = _record(
        owner_user_id,
        "事件账本中的已验证记忆。",
        source_kind="authored_event",
        source_ids=["verified-ledger-event"],
        scope_type="character",
        scope_id=character_id,
    )

    original_legacy_getter = repository.get_long_term_fact_records
    legacy_calls = []

    def tracked_legacy_getter(*args, **kwargs):
        legacy_calls.append((args, kwargs))
        return original_legacy_getter(*args, **kwargs)

    monkeypatch.setattr(
        repository,
        "get_long_term_fact_records",
        tracked_legacy_getter,
    )

    with repository.get_conn() as conn:
        conn.execute(
            "DELETE FROM data_migration WHERE migration_key = ?",
            (marker,),
        )

    before_marker = repository.get_prompt_memory_fact_records(
        character_id=character_id,
        player_id=owner_user_id,
        session_id=session_id,
        limit=20,
    )

    try:
        with repository.get_conn() as conn:
            conn.execute(
                """
                INSERT INTO data_migration (migration_key, metadata, applied_at)
                VALUES (?, '{}', ?)
                """,
                (marker, datetime.now(timezone.utc).isoformat()),
            )

        after_marker = repository.get_prompt_memory_fact_records(
            character_id=character_id,
            player_id=owner_user_id,
            session_id=session_id,
            limit=20,
        )
    finally:
        with repository.get_conn() as conn:
            conn.execute(
                "DELETE FROM data_migration WHERE migration_key = ?",
                (marker,),
            )

    assert [record["fact_text"] for record in before_marker] == [
        verified["fact_text"],
        "迁移前仍可读取的旧长期记忆。",
    ]
    assert [record["fact_text"] for record in after_marker] == [
        verified["fact_text"],
    ]
    assert len(legacy_calls) == 1


def test_prompt_fallback_does_not_leak_legacy_after_backfill_marker(
    owner_user_id,
    monkeypatch,
):
    from types import SimpleNamespace

    from memoria.core import orchestrator

    character_id = "npc_graytide_marker_fallback"
    session_id = f"graytide-marker-{uuid4().hex}"
    legacy_fact = "旧系统记录：玩家掌握北闸门钥匙。"
    marker = repository.LONG_TERM_FACT_BACKFILL_MIGRATION
    card = SimpleNamespace(
        meta=SimpleNamespace(
            name="Marker Tester",
            display_name="Marker Tester",
            aliases=[],
        ),
        runtime_state_schema=SimpleNamespace(
            affection_level=0,
            trust_level=10,
            current_mood=SimpleNamespace(default_mood="neutral"),
        ),
    )
    repository.create_session(
        session_id,
        character_id,
        owner_user_id,
        "Marker Tester",
    )
    repository.save_long_term_fact(
        character_id,
        owner_user_id,
        legacy_fact,
    )

    monkeypatch.setattr(
        repository,
        "get_prompt_memory_fact_records",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("ledger unavailable")),
    )

    with repository.get_conn() as conn:
        conn.execute(
            "DELETE FROM data_migration WHERE migration_key = ?",
            (marker,),
        )

    try:
        before_state = repository.get_runtime_state(
            character_id,
            owner_user_id,
            card,
        )
        before_context = orchestrator._load_single_character_prompt_context(
            character_id,
            owner_user_id,
            card,
            session_id=session_id,
            fallback_known_player_facts=before_state["known_player_facts"],
            player_character={"display_name": "Marker Tester"},
        )

        with repository.get_conn() as conn:
            conn.execute(
                """
                INSERT INTO data_migration (migration_key, metadata, applied_at)
                VALUES (?, '{}', ?)
                """,
                (marker, datetime.now(timezone.utc).isoformat()),
            )

        after_state = repository.get_runtime_state(
            character_id,
            owner_user_id,
            card,
        )
        after_context = orchestrator._load_single_character_prompt_context(
            character_id,
            owner_user_id,
            card,
            session_id=session_id,
            fallback_known_player_facts=after_state["known_player_facts"],
            player_character={"display_name": "Marker Tester"},
        )
    finally:
        with repository.get_conn() as conn:
            conn.execute(
                "DELETE FROM data_migration WHERE migration_key = ?",
                (marker,),
            )

    assert legacy_fact in before_context["known_player_facts"]
    assert legacy_fact not in after_state["known_player_facts"]
    assert legacy_fact not in after_context["known_player_facts"]


def test_authored_event_is_verified_immediately(owner_user_id):
    claim = _record(
        owner_user_id,
        "港口警笛会在世界时间六点鸣响。",
        source_kind="authored_event",
        source_ids=["graytide_harbor_siren_schedule"],
        provenance={"event_version": 3},
    )

    assert claim["status"] == "verified"
    assert claim["verified_at"] is not None
    assert claim["source_ids"] == ["graytide_harbor_siren_schedule"]
    assert claim["provenance"]["evidence"][0]["details"] == {
        "event_version": 3,
    }
    assert [event.event_type for event in _events(owner_user_id, claim["claim_id"])] == [
        "fact.claimed.v1",
        "fact.verified.v1",
    ]


def test_admin_verification_can_verify_an_existing_candidate(owner_user_id):
    from memoria.core.fact_claims import record_admin_verification

    candidate = _record(
        owner_user_id,
        "旧港口地图保存在档案室。",
        source_kind="model_inference",
        source_ids=["model-turn-1"],
    )

    verified = record_admin_verification(
        owner_user_id,
        candidate["claim_id"],
        source_ids=["admin-user-1"],
        provenance={"reason": "人工核对原始地图"},
    )

    assert candidate["status"] == "candidate"
    assert verified["status"] == "verified"
    assert verified["source_ids"] == ["admin-user-1", "model-turn-1"]
    assert [
        event.event_type
        for event in _events(owner_user_id, candidate["claim_id"])
    ] == [
        "fact.claimed.v1",
        "fact.claimed.v1",
        "fact.verified.v1",
    ]


@pytest.mark.parametrize("source_kind", ["player_message", "knowledge_chunk"])
def test_direct_low_risk_support_is_deterministically_verified(
    owner_user_id,
    source_kind,
):
    claim = _record(
        owner_user_id,
        "废弃泵站的地下入口积有冷凝液。",
        source_kind=source_kind,
        source_ids=[f"{source_kind}-1"],
        direct_support=True,
    )

    assert claim["status"] == "verified"
    assert repository.list_verified_fact_claims(
        owner_user_id,
        "story",
        "graytide",
    ) == [claim]


def test_high_risk_claim_requires_two_distinct_source_ids(owner_user_id):
    claim = _record(
        owner_user_id,
        "塞拉斯本人签署并批准了秘密订单。",
        source_kind="knowledge_chunk",
        source_ids=["chunk-1", "chunk-1"],
        direct_support=True,
    )

    assert claim["status"] == "candidate"
    assert claim["source_ids"] == ["chunk-1"]


def test_high_risk_threshold_counts_only_direct_support(owner_user_id):
    fact_text = "塞拉斯本人是克劳工业的明确代理。"
    _record(
        owner_user_id,
        fact_text,
        source_kind="knowledge_chunk",
        source_ids=["chunk-indirect"],
        direct_support=False,
    )

    claim = _record(
        owner_user_id,
        fact_text,
        source_kind="knowledge_chunk",
        source_ids=["chunk-direct"],
        direct_support=True,
    )

    assert claim["source_ids"] == ["chunk-direct", "chunk-indirect"]
    assert claim["status"] == "candidate"


def test_direct_knowledge_can_verify_after_initial_model_inference(owner_user_id):
    fact_text = "潮汐泵站的控制室位于地下二层。"
    first = _record(
        owner_user_id,
        fact_text,
        source_kind="model_inference",
        source_ids=["model-turn-1"],
        direct_support=True,
    )
    second = _record(
        owner_user_id,
        fact_text,
        source_kind="knowledge_chunk",
        source_ids=["chunk-direct-1"],
        direct_support=True,
    )

    assert first["status"] == "candidate"
    assert second["status"] == "verified"


def test_direct_model_inference_does_not_verify_after_indirect_knowledge(
    owner_user_id,
):
    fact_text = "潮汐泵站的备用钥匙藏在西侧阀门后。"
    _record(
        owner_user_id,
        fact_text,
        source_kind="knowledge_chunk",
        source_ids=["chunk-indirect-1"],
        direct_support=False,
    )
    claim = _record(
        owner_user_id,
        fact_text,
        source_kind="model_inference",
        source_ids=["model-turn-2"],
        direct_support=True,
    )

    assert claim["status"] == "candidate"


def test_same_source_can_upgrade_from_indirect_to_direct(owner_user_id):
    fact_text = "港口仓库的备用电源仍可使用。"
    first = _record(
        owner_user_id,
        fact_text,
        source_kind="knowledge_chunk",
        source_ids=["chunk-1"],
        direct_support=False,
    )
    second = _record(
        owner_user_id,
        fact_text,
        source_kind="knowledge_chunk",
        source_ids=["chunk-1"],
        direct_support=True,
    )

    assert first["status"] == "candidate"
    assert second["status"] == "verified"
    assert [
        event.event_type
        for event in _events(owner_user_id, first["claim_id"])
    ] == [
        "fact.claimed.v1",
        "fact.claimed.v1",
        "fact.verified.v1",
    ]


@pytest.mark.parametrize(
    "fact_text",
    [
        "Silas killed the harbor master.",
        "Silas murdered the harbor master.",
        "Silas was responsible for the harbor master's death.",
        "塞拉斯杀害了港务长。",
        "塞拉斯谋杀了港务长。",
        "塞拉斯参与了港口爆炸案的作案。",
    ],
)
def test_high_risk_authored_event_requires_two_distinct_sources(
    owner_user_id,
    fact_text,
):
    first = _record(
        owner_user_id,
        fact_text,
        source_kind="authored_event",
        source_ids=["authored-event-1"],
    )
    second = _record(
        owner_user_id,
        fact_text,
        source_kind="authored_event",
        source_ids=["authored-event-2"],
    )

    assert first["status"] == "candidate"
    assert second["status"] == "verified"


def test_new_source_merges_and_verifies_high_risk_claim_once(owner_user_id):
    first = _record(
        owner_user_id,
        "塞拉斯本人签署并批准了秘密订单。",
        source_kind="knowledge_chunk",
        source_ids=["chunk-1"],
        direct_support=True,
    )
    second = _record(
        owner_user_id,
        "  塞拉斯本人签署并批准了秘密订单！ ",
        source_kind="knowledge_chunk",
        source_ids=["chunk-2"],
        direct_support=True,
    )
    third = _record(
        owner_user_id,
        "塞拉斯本人签署并批准了秘密订单",
        source_kind="knowledge_chunk",
        source_ids=["chunk-2"],
        direct_support=True,
    )

    assert second["claim_id"] == first["claim_id"]
    assert third["claim_id"] == first["claim_id"]
    assert second["fact_text"] == "塞拉斯本人签署并批准了秘密订单。"
    assert second["source_ids"] == ["chunk-1", "chunk-2"]
    assert second["status"] == "verified"
    assert [event.event_type for event in _events(owner_user_id, first["claim_id"])] == [
        "fact.claimed.v1",
        "fact.claimed.v1",
        "fact.verified.v1",
    ]


def test_claimed_events_are_authoritative_and_replay_candidate_evidence(
    owner_user_id,
):
    fact_text = "港口旧钟楼仍保留机械发条。"
    first = _record(
        owner_user_id,
        fact_text,
        source_kind="knowledge_chunk",
        source_ids=["chunk-indirect"],
        direct_support=False,
        provenance={"page": 4},
    )
    original = _record(
        owner_user_id,
        fact_text,
        source_kind="model_inference",
        source_ids=["model-turn"],
        direct_support=True,
        provenance={"turn": 8},
    )
    events = _events(owner_user_id, first["claim_id"])

    assert [event.event_type for event in events] == [
        "fact.claimed.v1",
        "fact.claimed.v1",
    ]
    for event in events:
        assert {
            "owner_user_id",
            "claim_id",
            "scope_type",
            "scope_id",
            "fact_text",
            "normalized_fact_text",
            "content_hash",
            "normalized_content_hash",
            "source_kind",
            "source_ids",
            "direct_support",
            "provenance",
        } <= set(event.payload)

    replayed = _replay_fact_claim(owner_user_id, first["claim_id"])

    assert original["status"] == "candidate"
    assert replayed == original


def test_claimed_and_verified_events_replay_verified_projection(owner_user_id):
    fact_text = "塞拉斯杀害了港务长。"
    first = _record(
        owner_user_id,
        fact_text,
        source_kind="knowledge_chunk",
        source_ids=["chunk-1"],
        direct_support=True,
        provenance={"page": 11},
    )
    original = _record(
        owner_user_id,
        fact_text,
        source_kind="authored_event",
        source_ids=["authored-2"],
        provenance={"event_version": 2},
    )
    events = _events(owner_user_id, first["claim_id"])
    verified_event = events[-1]

    assert [event.event_type for event in events] == [
        "fact.claimed.v1",
        "fact.claimed.v1",
        "fact.verified.v1",
    ]
    assert verified_event.payload["reason"] == "deterministic_policy"
    assert list(
        verified_event.payload["verification_snapshot"]["source_ids"]
    ) == [
        "authored-2",
        "chunk-1",
    ]
    assert len(
        verified_event.payload["verification_snapshot"]["evidence"]
    ) == 2

    replayed = _replay_fact_claim(owner_user_id, first["claim_id"])

    assert original["status"] == "verified"
    assert replayed == original


def test_same_scope_and_normalized_content_is_idempotent(owner_user_id):
    first = _record(
        owner_user_id,
        "ＡＴＬＡＳ  heard the bell.",
        source_kind="player_message",
        source_ids=["message-1"],
        direct_support=True,
    )
    second = _record(
        owner_user_id,
        "atlas heard the bell!",
        source_kind="player_message",
        source_ids=["message-1"],
        direct_support=True,
    )

    claims = repository.list_fact_claims(
        owner_user_id,
        "story",
        "graytide",
    )
    assert second["claim_id"] == first["claim_id"]
    assert len(claims) == 1
    assert claims[0]["fact_text"] == "ＡＴＬＡＳ  heard the bell."
    assert len(_events(owner_user_id, first["claim_id"])) == 2


def test_normalization_preserves_the_original_fact_text(owner_user_id):
    claim = _record(
        owner_user_id,
        "  原始事实保留首尾空白。  ",
        source_kind="legacy",
        source_ids=["legacy-1"],
    )

    assert claim["fact_text"] == "  原始事实保留首尾空白。  "
    assert claim["normalized_fact_text"] == "原始事实保留首尾空白"


def test_retract_removes_claim_from_verified_projection(owner_user_id):
    from memoria.core.fact_claims import retract_claim

    claim = _record(
        owner_user_id,
        "零号货单的收货点是废弃潮汐泵站。",
        source_kind="knowledge_chunk",
        source_ids=["chunk-manifest"],
        direct_support=True,
    )

    retracted = retract_claim(
        owner_user_id,
        claim["claim_id"],
        reason="原始清单已被撤销",
    )
    repeated = retract_claim(
        owner_user_id,
        claim["claim_id"],
        reason="重复请求",
    )

    assert retracted["status"] == "retracted"
    assert repeated == retracted
    assert retracted["retracted_at"] is not None
    assert repository.list_verified_fact_claims(
        owner_user_id,
        "story",
        "graytide",
    ) == []
    assert [event.event_type for event in _events(owner_user_id, claim["claim_id"])] == [
        "fact.claimed.v1",
        "fact.verified.v1",
        "fact.retracted.v1",
    ]


def test_supersede_links_claims_and_removes_old_verified_projection(
    owner_user_id,
):
    from memoria.core.fact_claims import supersede_claim

    old_claim = _record(
        owner_user_id,
        "旧版泵站路线经过北侧隧道。",
        source_kind="authored_event",
        source_ids=["route-v1"],
    )
    replacement = _record(
        owner_user_id,
        "新版泵站路线经过南侧隧道。",
        source_kind="authored_event",
        source_ids=["route-v2"],
    )

    superseded = supersede_claim(
        owner_user_id,
        old_claim["claim_id"],
        replacement["claim_id"],
        reason="路线图已修订",
    )
    repeated = supersede_claim(
        owner_user_id,
        old_claim["claim_id"],
        replacement["claim_id"],
        reason="重复请求",
    )
    claims = repository.list_fact_claims(
        owner_user_id,
        "story",
        "graytide",
    )
    projected_replacement = next(
        claim
        for claim in claims
        if claim["claim_id"] == replacement["claim_id"]
    )

    assert repeated == superseded
    assert superseded["status"] == "superseded"
    assert superseded["superseded_by_claim_id"] == replacement["claim_id"]
    assert projected_replacement["supersedes_claim_id"] == old_claim["claim_id"]
    assert repository.list_verified_fact_claims(
        owner_user_id,
        "story",
        "graytide",
    ) == [projected_replacement]
    assert [event.event_type for event in _events(
        owner_user_id,
        old_claim["claim_id"],
    )] == [
        "fact.claimed.v1",
        "fact.verified.v1",
        "fact.superseded.v1",
    ]


def test_retracted_claim_cannot_be_superseded_or_accept_evidence(owner_user_id):
    from memoria.core.fact_claims import retract_claim, supersede_claim

    claim = _record(
        owner_user_id,
        "旧港口地图标注了东侧入口。",
        source_kind="authored_event",
        source_ids=["map-v1"],
    )
    replacement = _record(
        owner_user_id,
        "新港口地图标注了西侧入口。",
        source_kind="authored_event",
        source_ids=["map-v2"],
    )
    terminal = retract_claim(owner_user_id, claim["claim_id"])
    events_before = _events(owner_user_id, claim["claim_id"])

    with pytest.raises(ValueError, match="terminal"):
        supersede_claim(
            owner_user_id,
            claim["claim_id"],
            replacement["claim_id"],
        )
    with pytest.raises(ValueError, match="terminal"):
        _record(
            owner_user_id,
            claim["fact_text"],
            source_kind="knowledge_chunk",
            source_ids=["late-evidence"],
            direct_support=True,
        )

    projected = next(
        item
        for item in repository.list_fact_claims(
            owner_user_id,
            "story",
            "graytide",
        )
        if item["claim_id"] == claim["claim_id"]
    )
    assert projected == terminal
    assert _events(owner_user_id, claim["claim_id"]) == events_before


def test_superseded_claim_cannot_be_retracted_or_change_replacement(
    owner_user_id,
):
    from memoria.core.fact_claims import retract_claim, supersede_claim

    original = _record(
        owner_user_id,
        "旧路线经过一号闸门。",
        source_kind="authored_event",
        source_ids=["route-1"],
    )
    replacement = _record(
        owner_user_id,
        "新路线经过二号闸门。",
        source_kind="authored_event",
        source_ids=["route-2"],
    )
    other_replacement = _record(
        owner_user_id,
        "备用路线经过三号闸门。",
        source_kind="authored_event",
        source_ids=["route-3"],
    )
    terminal = supersede_claim(
        owner_user_id,
        original["claim_id"],
        replacement["claim_id"],
    )

    assert supersede_claim(
        owner_user_id,
        original["claim_id"],
        replacement["claim_id"],
    ) == terminal
    with pytest.raises(ValueError, match="terminal"):
        retract_claim(owner_user_id, original["claim_id"])
    with pytest.raises(ValueError, match="replacement"):
        supersede_claim(
            owner_user_id,
            original["claim_id"],
            other_replacement["claim_id"],
        )

    claims = {
        item["claim_id"]: item
        for item in repository.list_fact_claims(
            owner_user_id,
            "story",
            "graytide",
        )
    }
    assert claims[original["claim_id"]] == terminal
    assert claims[replacement["claim_id"]]["supersedes_claim_id"] == (
        original["claim_id"]
    )
    assert claims[other_replacement["claim_id"]]["supersedes_claim_id"] is None


def test_linked_replacement_cannot_be_retracted(owner_user_id):
    from memoria.core.fact_claims import retract_claim, supersede_claim

    original = _record(
        owner_user_id,
        "旧航道经过北侧浮标。",
        source_kind="authored_event",
        source_ids=["channel-v1"],
    )
    replacement = _record(
        owner_user_id,
        "新航道经过南侧浮标。",
        source_kind="authored_event",
        source_ids=["channel-v2"],
    )
    supersede_claim(
        owner_user_id,
        original["claim_id"],
        replacement["claim_id"],
    )
    events_before = _events(owner_user_id, replacement["claim_id"])

    with pytest.raises(ValueError, match="replacement"):
        retract_claim(owner_user_id, replacement["claim_id"])

    assert repository.get_fact_claim(
        owner_user_id,
        replacement["claim_id"],
    )["status"] == "verified"
    assert _events(owner_user_id, replacement["claim_id"]) == events_before


def test_terminal_replacement_cannot_receive_superseded_link(owner_user_id):
    from memoria.core.fact_claims import retract_claim, supersede_claim

    original = _record(
        owner_user_id,
        "候选旧事实。",
        source_kind="legacy",
        source_ids=["legacy-old"],
    )
    replacement = _record(
        owner_user_id,
        "候选替代事实。",
        source_kind="legacy",
        source_ids=["legacy-new"],
    )
    retracted_replacement = retract_claim(
        owner_user_id,
        replacement["claim_id"],
    )

    with pytest.raises(ValueError, match="replacement.*terminal"):
        supersede_claim(
            owner_user_id,
            original["claim_id"],
            replacement["claim_id"],
        )

    projected = {
        item["claim_id"]: item
        for item in repository.list_fact_claims(
            owner_user_id,
            "story",
            "graytide",
        )
    }
    assert projected[original["claim_id"]]["status"] == "candidate"
    assert projected[replacement["claim_id"]] == retracted_replacement


def test_replaying_older_event_does_not_reduce_ledger_version(owner_user_id):
    claim = _record(
        owner_user_id,
        "旧事件不能覆盖新投影。",
        source_kind="authored_event",
        source_ids=["event-1"],
    )
    events = _events(owner_user_id, claim["claim_id"])

    with repository.get_conn() as conn:
        repository._project_fact_claim_event(events[0], conn=conn)

    projected = repository.list_fact_claims(
        owner_user_id,
        "story",
        "graytide",
    )[0]
    assert projected == claim
    assert projected["ledger_version"] == events[-1].aggregate_version


def test_postgres_advisory_lock_precedes_fact_claim_read(monkeypatch):
    statements = []

    class Cursor:
        def fetchone(self):
            return None

    class FakeConnection:
        def execute(self, sql, params=None):
            statements.append((" ".join(sql.split()), params))
            return Cursor()

    monkeypatch.setattr(repository, "_is_postgres_enabled", lambda: True)
    conn = FakeConnection()

    repository._lock_fact_claim_for_write(conn, "fact-claim-1")
    repository._get_fact_claim_in_transaction(
        conn,
        "owner-1",
        "fact-claim-1",
    )

    assert statements[0] == (
        "SELECT pg_advisory_xact_lock(hashtextextended(?, 0))",
        ("fact-claim-1",),
    )
    assert statements[1][0].startswith("SELECT * FROM fact_claim")


def test_projector_rejects_stale_projection_write(owner_user_id):
    from memoria.core.domain_events import StoredDomainEvent

    claim = _record(
        owner_user_id,
        "并发写入必须使用预期版本。",
        source_kind="legacy",
        source_ids=["legacy-1"],
    )
    claimed_event = _events(owner_user_id, claim["claim_id"])[0]
    stale_event = StoredDomainEvent(
        **{
            **claimed_event.model_dump(),
            "event_id": uuid4().hex,
            "sequence": claimed_event.sequence + 100,
            "aggregate_version": claimed_event.aggregate_version + 2,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "payload": {
                **claimed_event.model_dump()["payload"],
                "source_kind": "knowledge_chunk",
                "source_ids": ["chunk-late"],
                "direct_support": True,
                "provenance": {"page": 9},
            },
        }
    )

    with pytest.raises(repository.FactClaimConcurrencyError, match="version"):
        repository._project_fact_claim_event(stale_event)

    assert repository.list_fact_claims(
        owner_user_id,
        "story",
        "graytide",
    ) == [claim]


def test_projector_rejects_model_only_verification_event(owner_user_id):
    from memoria.core.domain_events import StoredDomainEvent

    claim = _record(
        owner_user_id,
        "模型推断不能自行成为已核验事实。",
        source_kind="model_inference",
        source_ids=["model-turn-1"],
    )
    evidence = claim["provenance"]["evidence"]
    forged_event = StoredDomainEvent(
        owner_user_id=owner_user_id,
        aggregate_type="fact_claim",
        aggregate_id=claim["claim_id"],
        event_type="fact.verified.v1",
        event_id=uuid4().hex,
        payload={
            "owner_user_id": owner_user_id,
            "claim_id": claim["claim_id"],
            "reason": "forged",
            "verification_snapshot": {
                "verified": True,
                "high_risk": False,
                "required_sources": 1,
                "qualifying_source_ids": ["model-turn-1"],
                "source_ids": ["model-turn-1"],
                "evidence": evidence,
            },
        },
        sequence=1000,
        aggregate_version=claim["ledger_version"] + 1,
        recorded_at=datetime.now(timezone.utc).isoformat(),
    )

    with pytest.raises(ValueError, match="verification"):
        repository._project_fact_claim_event(forged_event)

    assert repository.list_fact_claims(
        owner_user_id,
        "story",
        "graytide",
    ) == [claim]


@pytest.mark.parametrize(
    ("field_name", "forged_value"),
    [
        ("verified", False),
        ("high_risk", True),
        ("required_sources", 2),
        ("qualifying_source_ids", []),
    ],
)
def test_projector_replay_rejects_forged_verification_decision(
    owner_user_id,
    field_name,
    forged_value,
):
    from memoria.core.domain_events import StoredDomainEvent

    claim = _record(
        owner_user_id,
        "东侧仓库保留一台手摇泵。",
        source_kind="authored_event",
        source_ids=["warehouse-pump-1"],
    )
    claimed_event, verified_event = _events(
        owner_user_id,
        claim["claim_id"],
    )
    event_values = verified_event.model_dump()
    snapshot = dict(event_values["payload"]["verification_snapshot"])
    snapshot[field_name] = forged_value
    event_values["event_id"] = uuid4().hex
    event_values["payload"] = {
        **event_values["payload"],
        "verification_snapshot": snapshot,
    }
    forged_event = StoredDomainEvent(**event_values)

    with repository.get_conn() as conn:
        conn.execute(
            "DELETE FROM fact_claim WHERE owner_user_id = ? AND claim_id = ?",
            (owner_user_id, claim["claim_id"]),
        )
        repository._project_fact_claim_event(claimed_event, conn=conn)
        with pytest.raises(ValueError, match="decision"):
            repository._project_fact_claim_event(forged_event, conn=conn)

    replayed = repository.get_fact_claim(
        owner_user_id,
        claim["claim_id"],
    )
    assert replayed["status"] == "candidate"
    assert replayed["ledger_version"] == claimed_event.aggregate_version


def test_projector_replay_rejects_list_shaped_verification_snapshot(
    owner_user_id,
):
    from memoria.core.domain_events import StoredDomainEvent

    claim = _record(
        owner_user_id,
        "西侧仓库的手摇泵仍可使用。",
        source_kind="authored_event",
        source_ids=["warehouse-pump-snapshot-1"],
    )
    claimed_event, verified_event = _events(
        owner_user_id,
        claim["claim_id"],
    )
    event_values = verified_event.model_dump()
    valid_snapshot = event_values["payload"]["verification_snapshot"]
    event_values["event_id"] = uuid4().hex
    event_values["payload"] = {
        **event_values["payload"],
        "verification_snapshot": [
            [key, value]
            for key, value in valid_snapshot.items()
        ],
    }
    forged_event = StoredDomainEvent(**event_values)

    with repository.get_conn() as conn:
        conn.execute(
            "DELETE FROM fact_claim WHERE owner_user_id = ? AND claim_id = ?",
            (owner_user_id, claim["claim_id"]),
        )
        repository._project_fact_claim_event(claimed_event, conn=conn)
        with pytest.raises(
            ValueError,
            match="verification_snapshot.*object",
        ):
            repository._project_fact_claim_event(forged_event, conn=conn)

    replayed = repository.get_fact_claim(
        owner_user_id,
        claim["claim_id"],
    )
    assert replayed["status"] == "candidate"
    assert replayed["ledger_version"] == claimed_event.aggregate_version


def test_projector_replay_rejects_list_shaped_verification_evidence(
    owner_user_id,
):
    from memoria.core.domain_events import StoredDomainEvent

    claim = _record(
        owner_user_id,
        "东侧仓库的手摇泵仍可使用。",
        source_kind="authored_event",
        source_ids=["warehouse-pump-evidence-1"],
    )
    claimed_event, verified_event = _events(
        owner_user_id,
        claim["claim_id"],
    )
    event_values = verified_event.model_dump()
    snapshot = dict(event_values["payload"]["verification_snapshot"])
    valid_evidence = snapshot["evidence"][0]
    snapshot["evidence"] = [
        [[key, value] for key, value in valid_evidence.items()]
    ]
    event_values["event_id"] = uuid4().hex
    event_values["payload"] = {
        **event_values["payload"],
        "verification_snapshot": snapshot,
    }
    forged_event = StoredDomainEvent(**event_values)

    with repository.get_conn() as conn:
        conn.execute(
            "DELETE FROM fact_claim WHERE owner_user_id = ? AND claim_id = ?",
            (owner_user_id, claim["claim_id"]),
        )
        repository._project_fact_claim_event(claimed_event, conn=conn)
        with pytest.raises(ValueError, match="evidence.*object"):
            repository._project_fact_claim_event(forged_event, conn=conn)

    replayed = repository.get_fact_claim(
        owner_user_id,
        claim["claim_id"],
    )
    assert replayed["status"] == "candidate"
    assert replayed["ledger_version"] == claimed_event.aggregate_version


def test_projector_rejects_retraction_of_linked_replacement(owner_user_id):
    from memoria.core.domain_events import StoredDomainEvent
    from memoria.core.fact_claims import supersede_claim

    original = _record(
        owner_user_id,
        "旧补给线经过东侧仓库。",
        source_kind="authored_event",
        source_ids=["supply-v1"],
    )
    replacement = _record(
        owner_user_id,
        "新补给线经过西侧仓库。",
        source_kind="authored_event",
        source_ids=["supply-v2"],
    )
    supersede_claim(
        owner_user_id,
        original["claim_id"],
        replacement["claim_id"],
    )
    linked_replacement = repository.get_fact_claim(
        owner_user_id,
        replacement["claim_id"],
    )
    forged_event = StoredDomainEvent(
        owner_user_id=owner_user_id,
        aggregate_type="fact_claim",
        aggregate_id=replacement["claim_id"],
        event_type="fact.retracted.v1",
        event_id=uuid4().hex,
        payload={
            "owner_user_id": owner_user_id,
            "claim_id": replacement["claim_id"],
            "reason": "forged replay",
        },
        sequence=1000,
        aggregate_version=linked_replacement["ledger_version"] + 1,
        recorded_at=datetime.now(timezone.utc).isoformat(),
    )

    with pytest.raises(
        repository.FactClaimConcurrencyError,
        match="replacement",
    ):
        repository._project_fact_claim_event(forged_event)

    assert repository.get_fact_claim(
        owner_user_id,
        replacement["claim_id"],
    ) == linked_replacement


def test_projector_replay_rejects_cross_scope_supersession(owner_user_id):
    from memoria.core.domain_events import StoredDomainEvent

    original = _record(
        owner_user_id,
        "旧航线经过东侧浮标。",
        source_kind="legacy",
        source_ids=["route-v1"],
        scope_id="graytide-east",
    )
    replacement = _record(
        owner_user_id,
        "新航线经过西侧浮标。",
        source_kind="legacy",
        source_ids=["route-v2"],
        scope_id="graytide-west",
    )
    forged_event = StoredDomainEvent(
        owner_user_id=owner_user_id,
        aggregate_type="fact_claim",
        aggregate_id=original["claim_id"],
        event_type="fact.superseded.v1",
        event_id=uuid4().hex,
        payload={
            "owner_user_id": owner_user_id,
            "claim_id": original["claim_id"],
            "superseded_by_claim_id": replacement["claim_id"],
            "replacement_ledger_version": replacement["ledger_version"],
            "reason": "forged replay",
        },
        sequence=1000,
        aggregate_version=original["ledger_version"] + 1,
        recorded_at=datetime.now(timezone.utc).isoformat(),
    )

    with pytest.raises(ValueError, match="scope"):
        repository._project_fact_claim_event(forged_event)

    assert repository.get_fact_claim(
        owner_user_id,
        original["claim_id"],
    ) == original
    assert repository.get_fact_claim(
        owner_user_id,
        replacement["claim_id"],
    ) == replacement


@pytest.mark.parametrize(
    "invalid_source_ids",
    [
        [],
        ["source-1", 2],
    ],
)
def test_projector_rejects_invalid_claimed_event_source_ids(
    owner_user_id,
    invalid_source_ids,
):
    from memoria.core.domain_events import StoredDomainEvent

    claim_id = f"fact-invalid-{uuid4().hex}"
    event = StoredDomainEvent(
        owner_user_id=owner_user_id,
        aggregate_type="fact_claim",
        aggregate_id=claim_id,
        event_type="fact.claimed.v1",
        event_id=uuid4().hex,
        payload={
            "owner_user_id": owner_user_id,
            "claim_id": claim_id,
            "scope_type": "story",
            "scope_id": "graytide",
            "fact_text": "无效来源不能进入投影。",
            "normalized_fact_text": "无效来源不能进入投影",
            "content_hash": "content-hash",
            "normalized_content_hash": "normalized-content-hash",
            "source_kind": "legacy",
            "source_ids": invalid_source_ids,
            "direct_support": False,
            "provenance": {},
        },
        sequence=1000,
        aggregate_version=1,
        recorded_at=datetime.now(timezone.utc).isoformat(),
    )

    with pytest.raises(ValueError, match="source_ids"):
        repository._project_fact_claim_event(event)

    assert repository.list_fact_claims(
        owner_user_id,
        "story",
        "graytide",
    ) == []


@pytest.mark.parametrize(
    ("field_name", "forged_value"),
    [
        ("normalized_fact_text", "伪造的规范化文本"),
        ("content_hash", "0" * 64),
        ("normalized_content_hash", "1" * 64),
        ("claim_id", "fact_forged_claim_id"),
    ],
)
def test_projector_replay_rejects_forged_fact_identity(
    owner_user_id,
    field_name,
    forged_value,
):
    from memoria.core.domain_events import StoredDomainEvent

    claim = _record(
        owner_user_id,
        "投影必须独立验证事实身份。",
        source_kind="legacy",
        source_ids=["legacy-identity-1"],
    )
    claimed_event = _events(owner_user_id, claim["claim_id"])[0]
    event_values = claimed_event.model_dump()
    payload = dict(event_values["payload"])
    if field_name == "claim_id":
        event_values["aggregate_id"] = forged_value
        payload["claim_id"] = forged_value
    else:
        payload[field_name] = forged_value
    event_values["payload"] = payload
    event_values["event_id"] = uuid4().hex
    forged_event = StoredDomainEvent(**event_values)

    with repository.get_conn() as conn:
        conn.execute(
            "DELETE FROM fact_claim WHERE owner_user_id = ? AND claim_id = ?",
            (owner_user_id, claim["claim_id"]),
        )
        with pytest.raises(ValueError, match=field_name):
            repository._project_fact_claim_event(forged_event, conn=conn)

    assert repository.list_fact_claims(
        owner_user_id,
        "story",
        "graytide",
    ) == []


def test_postgres_initial_projection_conflict_reloads_concurrent_row(monkeypatch):
    from memoria.core.domain_events import StoredDomainEvent
    from memoria.core.fact_claim_policy import derive_fact_claim_identity

    identity = derive_fact_claim_identity(
        "owner-1",
        "story",
        "graytide",
        "并发创建。",
    )

    event = StoredDomainEvent(
        owner_user_id="owner-1",
        aggregate_type="fact_claim",
        aggregate_id=identity["claim_id"],
        event_type="fact.claimed.v1",
        event_id="claimed-event-1",
        payload={
            "owner_user_id": "owner-1",
            "scope_type": "story",
            "scope_id": "graytide",
            "fact_text": "并发创建。",
            **identity,
            "source_kind": "legacy",
            "source_ids": ["legacy-1"],
            "direct_support": False,
            "provenance": {},
        },
        sequence=1,
        aggregate_version=1,
        recorded_at="2026-07-15T00:00:00+00:00",
    )
    concurrent_row = {
        "owner_user_id": "owner-1",
        "scope_type": "story",
        "scope_id": "graytide",
        "fact_text": "并发创建。",
        **identity,
        "status": "candidate",
        "source_kind": "legacy",
        "provenance": '{"evidence":[]}',
        "source_ids": '["legacy-1"]',
        "supersedes_claim_id": None,
        "superseded_by_claim_id": None,
        "ledger_version": 1,
        "created_at": event.recorded_at,
        "updated_at": event.recorded_at,
        "verified_at": None,
        "retracted_at": None,
    }
    statements = []
    select_count = 0

    class Cursor:
        def __init__(self, *, row=None, rowcount=-1):
            self._row = row
            self.rowcount = rowcount

        def fetchone(self):
            return self._row

    class FakeConnection:
        def execute(self, sql, params=None):
            nonlocal select_count
            normalized_sql = " ".join(sql.split())
            statements.append((normalized_sql, params))
            if normalized_sql.startswith("SELECT * FROM fact_claim"):
                select_count += 1
                return Cursor(
                    row=None if select_count == 1 else concurrent_row,
                )
            if normalized_sql.startswith("INSERT INTO fact_claim"):
                return Cursor(rowcount=0)
            return Cursor()

    monkeypatch.setattr(repository, "_is_postgres_enabled", lambda: True)

    projected = repository._project_fact_claim_event(
        event,
        conn=FakeConnection(),
    )

    assert projected["claim_id"] == event.aggregate_id
    assert select_count == 2
    insert_sql = next(
        sql for sql, _params in statements
        if sql.startswith("INSERT INTO fact_claim")
    )
    assert "ON CONFLICT DO NOTHING" in insert_sql


def test_claim_lists_are_tenant_safe_and_deterministically_sorted(owner_user_id):
    other_user_id = f"fact_other_{uuid4().hex}"
    repository.create_user(
        other_user_id,
        f"fact_other_user_{uuid4().hex}",
        "test-hash",
    )
    later = _record(
        owner_user_id,
        "第二条普通事实。",
        source_kind="player_message",
        source_ids=["message-2"],
        direct_support=True,
    )
    earlier = _record(
        owner_user_id,
        "第一条普通事实。",
        source_kind="player_message",
        source_ids=["message-1"],
        direct_support=True,
    )
    _record(
        other_user_id,
        "另一租户的事实。",
        source_kind="authored_event",
        source_ids=["event-other"],
    )

    claims = repository.list_fact_claims(
        owner_user_id,
        "story",
        "graytide",
    )

    assert {claim["claim_id"] for claim in claims} == {
        earlier["claim_id"],
        later["claim_id"],
    }
    assert claims == sorted(
        claims,
        key=lambda claim: (
            claim["created_at"],
            claim["claim_id"],
        ),
    )
    assert all(isinstance(claim["provenance"], dict) for claim in claims)
    assert all(isinstance(claim["source_ids"], list) for claim in claims)


def test_invalid_scope_and_source_are_rejected_before_persistence(owner_user_id):
    with pytest.raises(ValueError):
        _record(
            owner_user_id,
            "事实。",
            scope_type="session",
            source_kind="player_message",
            source_ids=["message-1"],
        )
    with pytest.raises(ValueError):
        _record(
            owner_user_id,
            "事实。",
            source_kind="admin",
            source_ids=["admin-1"],
        )

    assert repository.list_domain_events(owner_user_id) == []


@pytest.mark.parametrize(
    "invalid_source_ids",
    [
        "message-1",
        ("message-1",),
        None,
        1,
        True,
        ["message-1", 2],
        ["message-1", False],
        [""],
        ["   "],
        [],
    ],
)
def test_source_ids_must_be_a_non_empty_list_of_non_empty_strings(
    owner_user_id,
    invalid_source_ids,
):
    with pytest.raises(ValueError, match="source_ids"):
        _record(
            owner_user_id,
            "输入证据必须严格校验。",
            source_kind="player_message",
            source_ids=invalid_source_ids,
            direct_support=True,
        )

    assert repository.list_domain_events(owner_user_id) == []


def test_ledger_and_projection_rollback_together_on_projector_failure(
    owner_user_id,
):
    with repository.get_conn() as conn:
        conn.execute(
            """
            CREATE TRIGGER fail_fact_claim_projection
            BEFORE INSERT ON fact_claim
            BEGIN
                SELECT RAISE(ABORT, 'projector failure');
            END
            """
        )
    try:
        with pytest.raises(sqlite3.IntegrityError, match="projector failure"):
            _record(
                owner_user_id,
                "这个投影必须失败。",
                source_kind="authored_event",
                source_ids=["event-failure"],
            )
    finally:
        with repository.get_conn() as conn:
            conn.execute("DROP TRIGGER fail_fact_claim_projection")

    assert repository.list_fact_claims(
        owner_user_id,
        "story",
        "graytide",
    ) == []
    assert repository.list_domain_events(owner_user_id) == []


def test_fact_claim_schema_is_additive_and_postgres_compatible(monkeypatch):
    with repository.get_conn() as conn:
        tables = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }

    assert {"users", "domain_event", "fact_claim"} <= tables
    assert "CHECK (scope_type IN ('character', 'group_thread', 'story'))" in (
        repository.SCHEMA
    )

    monkeypatch.setattr(
        repository.configs,
        "database_url",
        "postgresql://user:pass@localhost/memoria",
    )
    postgres_schema = repository._schema_for_current_db()

    assert "ledger_version BIGINT NOT NULL" in postgres_schema
    assert "AUTOINCREMENT" not in postgres_schema
