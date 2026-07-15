"""
数据库持久化层完整单元测试
"""
import pytest, sys, json, uuid
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from memoria.db import repository


class TestRuntimeState:
    def test_get_state_new_player(self):
        class Mood: default_mood = "neutral"
        rel = type("R",(),{"target_id":"player","affection_level":5,"trust_level":15})()
        class RTS:
            relationships = [rel]
            current_mood = Mood()
        class Fake:
            runtime_state_schema = RTS()
        state = repository.get_runtime_state("tCe837a1","tPe837a1",Fake())
        assert state["affection_level"] == 0  # DB default, schema not read directly
        assert state["trust_level"] == 10  # DB default
        assert state["current_mood"] == "neutral"

    def test_save_runtime_state(self):
        repository.save_runtime_state("tC2e837a1","tP2e837a1",50.0,60.0,"happy")
        class Mood: default_mood = "neutral"
        class RTS:
            relationships = []
            current_mood = Mood()
        class Fake:
            runtime_state_schema = RTS()
        s = repository.get_runtime_state("tC2e837a1","tP2e837a1",Fake())
        assert s["affection_level"] == 50.0
        assert s["current_mood"] == "happy"

class TestSession:
    def test_create_and_get(self):
        sid = str(uuid.uuid4())
        repository.create_session(sid,"tc","tp","Tester")
        s = repository.get_session(sid)
        assert s is not None
        assert s["status"] == "active"
        assert s["player_name"] == "Tester"

    def test_create_persists_locale(self):
        sid = str(uuid.uuid4())
        repository.create_session(sid, "tc-locale", "tp-locale", "Tester", "en-US")

        session = repository.get_session(sid)

        assert session["locale"] == "en-US"

    def test_end_session(self):
        sid = str(uuid.uuid4())
        repository.create_session(sid,"tc","tp","T")
        repository.end_session(sid)
        s = repository.get_session(sid)
        assert s["status"] == "ended"
        assert s["ended_at"] is not None

    def test_get_sessions_list(self):
        sid = str(uuid.uuid4())
        repository.create_session(sid,"tc3","tp3","T3")
        sessions = repository.get_sessions_by_player_and_character("tc3","tp3")
        assert any(s["session_id"]==sid for s in sessions)

class TestShortTerm:
    def test_append_and_get(self):
        # Single-char messages are appended via orchestrator, not repository directly
        pass

class TestLongTermFact:
    def test_save_and_get(self):
        repository.save_long_term_fact("fC","fP","玩家喜欢猫",7)
        facts = repository.get_long_term_facts("fC","fP",5)
        assert any("猫" in f for f in facts)

    @pytest.mark.parametrize(
        "empty_value",
        [None, "", "无", "无。", "暂无", "没有", "none", "null", "无值得记住的信息"],
    )
    def test_save_long_term_fact_skips_empty_values(self, empty_value):
        character_id = f"empty_c_{uuid.uuid4().hex[:8]}"
        player_id = f"empty_p_{uuid.uuid4().hex[:8]}"

        fact_id = repository.save_long_term_fact(character_id, player_id, empty_value)

        assert fact_id is None
        assert repository.get_long_term_facts(character_id, player_id, 5) == []

    def test_long_term_memory_saves_only_at_checkpoint(self):
        session_id = str(uuid.uuid4())
        character_id = f"checkpoint_c_{uuid.uuid4().hex[:8]}"
        player_id = f"checkpoint_p_{uuid.uuid4().hex[:8]}"
        repository.create_session(session_id, character_id, player_id, "Tester")

        for turn in range(1, 5):
            repository.append_short_term_message(session_id, "user", f"玩家消息 {turn}")
            repository.append_short_term_message(session_id, "assistant", f"角色回复 {turn}")
            fact_id = repository.save_long_term_fact_if_checkpoint(
                session_id,
                character_id,
                player_id,
                f"第 {turn} 轮候选记忆",
                interval_turns=5,
            )
            assert fact_id is None

        repository.append_short_term_message(session_id, "user", "玩家消息 5")
        repository.append_short_term_message(session_id, "assistant", "角色回复 5")
        fact_id = repository.save_long_term_fact_if_checkpoint(
            session_id,
            character_id,
            player_id,
            "玩家约定明天一起训练",
            interval_turns=5,
        )

        assert fact_id is not None
        assert repository.get_session_user_turn_count(session_id) == 5
        assert repository.get_long_term_facts(character_id, player_id, 5) == [
            "玩家约定明天一起训练"
        ]

    def test_long_term_memory_skips_empty_value_at_checkpoint(self):
        session_id = str(uuid.uuid4())
        character_id = f"empty_checkpoint_c_{uuid.uuid4().hex[:8]}"
        player_id = f"empty_checkpoint_p_{uuid.uuid4().hex[:8]}"
        repository.create_session(session_id, character_id, player_id, "Tester")

        for turn in range(5):
            repository.append_short_term_message(session_id, "user", f"玩家消息 {turn}")
            repository.append_short_term_message(session_id, "assistant", f"角色回复 {turn}")

        fact_id = repository.save_long_term_fact_if_checkpoint(
            session_id,
            character_id,
            player_id,
            "无",
            interval_turns=5,
        )

        assert fact_id is None
        assert repository.get_long_term_facts(character_id, player_id, 5) == []

    def test_get_long_term_facts_filters_created_after(self):
        character_id = f"lfc_{uuid.uuid4().hex[:8]}"
        player_id = f"lfp_{uuid.uuid4().hex[:8]}"
        repository.save_long_term_fact(character_id, player_id, "旧关系事实：师徒", 7)
        repository.save_long_term_fact(character_id, player_id, "新关系事实：情侣", 7)

        with repository.get_conn() as conn:
            conn.execute(
                "UPDATE long_term_fact SET created_at=?, last_referenced=? WHERE character_id=? AND player_id=? AND fact_text=?",
                ("2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00", character_id, player_id, "旧关系事实：师徒"),
            )
            conn.execute(
                "UPDATE long_term_fact SET created_at=?, last_referenced=? WHERE character_id=? AND player_id=? AND fact_text=?",
                ("2026-01-02T00:00:00+00:00", "2026-01-02T00:00:00+00:00", character_id, player_id, "新关系事实：情侣"),
            )

        facts = repository.get_long_term_facts(
            character_id,
            player_id,
            limit=5,
            created_after="2026-01-02T00:00:00+00:00",
        )
        assert "新关系事实：情侣" in facts
        assert "旧关系事实：师徒" not in facts

class TestCharacterCard:
    def test_save_list_delete(self):
        import json
        owner = f"user_{uuid.uuid4().hex[:8]}"
        cid = f"tc_{uuid.uuid4().hex[:8]}"
        card = json.dumps({"character_id":cid,"meta":{"name":"T","display_name":"T"}})
        assert repository.save_character_card_to_db(owner,cid,card,name="T",display_name="T")
        cards = repository.list_character_cards_from_db(owner, only_active=False)
        assert any(c["character_id"]==cid for c in cards)
        assert repository.delete_character_card_from_db(owner, cid)
        assert repository.activate_character_card(owner, cid)
        assert repository.delete_character_card_from_db(owner, cid, soft_delete=False)

    def test_same_character_id_is_isolated_by_owner(self):
        import json
        cid = f"tc_shared_{uuid.uuid4().hex[:8]}"
        owner_a = f"user_a_{uuid.uuid4().hex[:8]}"
        owner_b = f"user_b_{uuid.uuid4().hex[:8]}"
        card_a = json.dumps({"character_id":cid,"meta":{"name":"A","display_name":"A"}})
        card_b = json.dumps({"character_id":cid,"meta":{"name":"B","display_name":"B"}})

        assert repository.save_character_card_to_db(owner_a,cid,card_a,name="A",display_name="A")
        assert repository.save_character_card_to_db(owner_b,cid,card_b,name="B",display_name="B")
        assert repository.get_character_card_from_db(owner_a, cid)["name"] == "A"
        assert repository.get_character_card_from_db(owner_b, cid)["name"] == "B"

        assert repository.delete_character_card_from_db(owner_a, cid)
        assert not repository.is_character_card_active(owner_a, cid)
        assert repository.is_character_card_active(owner_b, cid)

    def test_soft_delete_preserves_relationship_and_hard_delete_removes_it(self):
        owner = f"user_{uuid.uuid4().hex[:8]}"
        character_id = f"tc_{uuid.uuid4().hex[:8]}"
        other_id = f"tc_{uuid.uuid4().hex[:8]}"
        for cid in (character_id, other_id):
            card = json.dumps(
                {"character_id": cid, "meta": {"name": cid, "display_name": cid}}
            )
            assert repository.save_character_card_to_db(
                owner,
                cid,
                card,
                name=cid,
                display_name=cid,
            )
        assert repository.save_character_relationship(
            owner,
            character_id,
            other_id,
            "friend",
            50.0,
            "friends",
        )

        assert repository.delete_character_card_from_db(owner, character_id)
        assert repository.get_character_relationship(owner, character_id, other_id)

        assert repository.delete_character_card_from_db(
            owner,
            character_id,
            soft_delete=False,
        )
        assert repository.get_character_relationship(owner, character_id, other_id) is None
        assert (
            repository.get_character_relationship_updated_at(
                owner,
                character_id,
                other_id,
            )
            is not None
        )

class TestEventDefinition:
    def test_crud(self):
        owner = f"user_{uuid.uuid4().hex[:8]}"
        eid = f"ev_{uuid.uuid4().hex[:8]}"
        assert repository.save_event_definition(owner,eid,"Test Evt","{}","[]",priority=5)
        evt = repository.get_event_definition(owner, eid)
        assert evt is not None
        assert evt["priority"] == 5
        lst = repository.list_event_definitions(owner, only_active=False)
        assert any(e["event_id"]==eid for e in lst)
        repository.increment_event_trigger_count(owner, eid)
        repository.log_event_trigger(eid,"tc",owner,"sess",'{}','[]')
        hist = repository.get_event_trigger_history(event_id=eid)
        assert len(hist) >= 1
        assert repository.delete_trigger_history(eid,"tc",owner) >= 1
        assert repository.delete_event_definition(owner, eid)

    def test_same_event_id_is_isolated_by_owner(self):
        owner_a = f"user_a_{uuid.uuid4().hex[:8]}"
        owner_b = f"user_b_{uuid.uuid4().hex[:8]}"
        eid = f"ev_shared_{uuid.uuid4().hex[:8]}"

        assert repository.save_event_definition(owner_a,eid,"Evt A","{}","[]",priority=1)
        assert repository.save_event_definition(owner_b,eid,"Evt B","{}","[]",priority=2)

        assert repository.get_event_definition(owner_a, eid)["event_name"] == "Evt A"
        assert repository.get_event_definition(owner_b, eid)["event_name"] == "Evt B"
        assert repository.delete_event_definition(owner_a, eid)
        assert repository.get_event_definition(owner_b, eid) is not None

    def test_definition_and_schedule_save_rolls_back_together(self):
        owner = f"user_atomic_{uuid.uuid4().hex[:8]}"
        event_id = f"ev_atomic_{uuid.uuid4().hex[:8]}"
        character_id = f"char_atomic_{uuid.uuid4().hex[:8]}"
        old_next_run = "2026-07-15T09:00:00+00:00"

        assert repository.save_event_definition(
            owner,
            event_id,
            "Old event",
            "{}",
            "[]",
            character_id=character_id,
            schedule="0 9 * * *",
        )
        assert repository.save_event_schedule_state(
            event_id=event_id,
            character_id=character_id,
            player_id=owner,
            schedule="0 9 * * *",
            next_run_at=old_next_run,
            status="active",
        )

        assert repository.save_event_definition_with_schedule(
            owner_user_id=owner,
            event_id=event_id,
            event_name="New event",
            trigger_config="{}",
            effects_config="[]",
            schedule_state={
                "event_id": "different-event",
                "character_id": character_id,
                "player_id": owner,
                "schedule": "0 10 * * *",
                "next_run_at": "2026-07-15T10:00:00+00:00",
            },
            character_id=character_id,
            schedule="0 10 * * *",
        ) is False

        definition = repository.get_event_definition(owner, event_id)
        schedule = repository.get_event_schedule(event_id, character_id, owner)
        assert definition["event_name"] == "Old event"
        assert definition["schedule"] == "0 9 * * *"
        assert schedule["schedule"] == "0 9 * * *"
        assert schedule["next_run_at"] == old_next_run

    def test_event_definition_story_id_survives_save_and_update(self):
        owner = f"user_story_{uuid.uuid4().hex[:8]}"
        event_id = f"ev_story_{uuid.uuid4().hex[:8]}"

        assert repository.save_event_definition(
            owner,
            event_id,
            "Story event",
            "{}",
            "[]",
            story_id="graytide",
        )
        assert repository.get_event_definition(owner, event_id)["story_id"] == "graytide"

        assert repository.save_event_definition_with_schedule(
            owner_user_id=owner,
            event_id=event_id,
            event_name="Story event updated",
            trigger_config="{}",
            effects_config="[]",
            schedule_state=None,
            story_id="graytide-finale",
        )
        definition = repository.get_event_definition(owner, event_id)
        assert definition["event_name"] == "Story event updated"
        assert definition["story_id"] == "graytide-finale"


class TestEventDeepIntegrationRepository:
    def test_context_schedule_template_crud(self):
        eid = f"evctx_{uuid.uuid4().hex[:8]}"
        cid = f"ctxc_{uuid.uuid4().hex[:8]}"
        pid = f"ctxp_{uuid.uuid4().hex[:8]}"
        tid = f"tpl_{uuid.uuid4().hex[:8]}"

        assert repository.save_event_context_state(
            event_id=eid,
            character_id=cid,
            player_id=pid,
            context_data='{"stage": 1}',
            progress=0.5,
            last_session_id="sess-1",
        )
        state = repository.get_event_context_state(eid, cid, pid)
        assert state is not None
        assert state["progress"] == 0.5

        states = repository.list_event_context_states(character_id=cid, player_id=pid)
        assert any(s["event_id"] == eid for s in states)

        assert repository.save_event_schedule_state(
            event_id=eid,
            character_id=cid,
            player_id=pid,
            schedule="*/5 * * * *",
            next_run_at="2026-07-10T14:30:00+00:00",
            next_due_real_at="2026-07-10T14:30:00+00:00",
        )
        due = repository.list_due_event_schedules("2026-07-10T14:31:00+00:00")
        assert any(row["event_id"] == eid for row in due)

        assert repository.save_event_template(
            template_id=tid,
            template_name="测试模板",
            category="test",
            description="desc",
            trigger_config='{"trigger_type":"keyword_match","keywords":["a"]}',
            effects_config="[]",
            metadata='{"x":1}',
        )
        template = repository.get_event_template(tid)
        assert template["template_name"] == "测试模板"
        assert any(t["template_id"] == tid for t in repository.list_event_templates(category="test"))
        assert repository.delete_event_template(tid)
        assert repository.get_event_template(tid) is None

class TestRelationship:
    def test_crud(self):
        owner = f"user_{uuid.uuid4().hex[:8]}"
        assert repository.save_character_relationship(owner,"rA","rB","friend",50.0,"friends")
        rel = repository.get_character_relationship(owner,"rA","rB")
        assert rel is not None
        assert rel["relationship_type"] == "friend"
        rels = repository.list_character_relationships(owner,"rA")
        assert len(rels) >= 1
        repository.update_relationship_affinity(owner,"rA","rB",10.0)
        rel2 = repository.get_character_relationship(owner,"rA","rB")
        assert rel2["affinity"] == 60.0
        updated_before_delete = repository.get_character_relationship_updated_at(owner, "rA", "rB")
        assert updated_before_delete is not None
        assert repository.delete_character_relationship(owner,"rA","rB")
        assert repository.get_character_relationship(owner, "rA", "rB") is None
        updated_after_delete = repository.get_character_relationship_updated_at(owner, "rA", "rB")
        assert updated_after_delete is not None
        assert updated_after_delete >= updated_before_delete

    def test_same_relationship_pair_is_isolated_by_owner(self):
        owner_a = f"user_a_{uuid.uuid4().hex[:8]}"
        owner_b = f"user_b_{uuid.uuid4().hex[:8]}"

        assert repository.save_character_relationship(owner_a,"rA","rB","friend",50.0,"A")
        assert repository.save_character_relationship(owner_b,"rA","rB","enemy",-20.0,"B")

        assert repository.get_character_relationship(owner_a,"rA","rB")["relationship_type"] == "friend"
        assert repository.get_character_relationship(owner_b,"rA","rB")["relationship_type"] == "enemy"

class TestMultiSession:
    def test_create_and_participants(self):
        sid = str(uuid.uuid4())
        for cid in ("c1", "c2"):
            card = json.dumps({"character_id": cid, "meta": {"name": cid, "display_name": cid}})
            assert repository.save_character_card_to_db("p1", cid, card, name=cid, display_name=cid)
        assert repository.create_multi_character_session(sid,"p1","Player",["c1","c2"])
        parts = repository.get_session_participants(sid)
        assert len(parts) == 2
        repository.append_multi_character_message(sid,"assistant","Hi","c1","Char1")
        repository.update_participant_speak_time(sid,"c1")
        hist = repository.get_multi_character_history(sid,5)
        assert len(hist) >= 1

    def test_multi_message_returns_stable_id_and_history_exposes_it(self):
        sid = str(uuid.uuid4())
        player_id = f"group_ids_{uuid.uuid4().hex[:8]}"
        assert repository.create_multi_character_session(
            sid,
            player_id,
            "Player",
            ["stable-c1", "stable-c2"],
            locale="en-US",
        )

        message_id = repository.append_multi_character_message(
            sid, "assistant", "Hello", "stable-c1", "One"
        )
        history = repository.get_multi_character_history(sid, 10)

        assert repository.get_session(sid)["locale"] == "en-US"
        assert isinstance(message_id, int)
        assert history[-1]["message_id"] == message_id


class TestSpeechSettings:
    def test_defaults_and_updates_persist(self):
        user_id = f"speech_user_{uuid.uuid4().hex[:8]}"
        repository.create_user(user_id, f"speech_{uuid.uuid4().hex[:8]}", "hash")

        initial = repository.get_user_by_id(user_id)
        repository.update_user_speech_settings(
            user_id,
            tts_auto_play=True,
            stt_auto_send=True,
        )
        updated = repository.get_user_by_id(user_id)

        assert initial["tts_auto_play"] == 0
        assert initial["stt_auto_send"] == 0
        assert updated["tts_auto_play"] == 1
        assert updated["stt_auto_send"] == 1

    def test_disabled_character_stays_in_group_but_is_not_active_participant(self):
        sid = str(uuid.uuid4())
        active_id = f"ga_{uuid.uuid4().hex[:8]}"
        disabled_id = f"gd_{uuid.uuid4().hex[:8]}"
        active_card = json.dumps({"character_id": active_id, "meta": {"name": "A", "display_name": "A"}})
        disabled_card = json.dumps({"character_id": disabled_id, "meta": {"name": "D", "display_name": "D"}})

        assert repository.save_character_card_to_db("p1", active_id, active_card, name="A", display_name="A")
        assert repository.save_character_card_to_db("p1", disabled_id, disabled_card, name="D", display_name="D")
        assert repository.create_multi_character_session(sid, "p1", "Player", [active_id, disabled_id])
        assert repository.delete_character_card_from_db("p1", disabled_id, soft_delete=True)

        visible_parts = repository.get_session_participants(sid, only_active=False)
        active_parts = repository.get_session_participants(sid, only_active=True)

        assert {p["character_id"] for p in visible_parts} == {active_id, disabled_id}
        assert [p["character_id"] for p in active_parts] == [active_id]
        disabled_part = next(p for p in visible_parts if p["character_id"] == disabled_id)
        assert not disabled_part["is_active"]

    def test_group_name_visible_in_player_sessions(self):
        sid = str(uuid.uuid4())
        player_id = f"pg_{uuid.uuid4().hex[:8]}"
        assert repository.create_multi_character_session(
            sid,
            player_id,
            "Player",
            ["gc1", "gc2"],
            group_name="旅团作战室",
        )
        sessions = repository.get_all_player_sessions(player_id)
        group = next(s for s in sessions if s["session_id"] == sid)
        assert group["group_name"] == "旅团作战室"
        assert group["group_thread_id"]
        assert group["group_thread_id"] != sid
        assert group["group_thread_id"].startswith("group-thread-")
        assert group["group_thread_id"] == repository.get_group_thread_id(sid)
        assert group["is_multi_character"]

    def test_character_group_memories_are_isolated_by_owner(self):
        character_id = f"gmiso_{uuid.uuid4().hex[:8]}"
        other_id = f"gmiso_other_{uuid.uuid4().hex[:8]}"
        player_a = f"gma_{uuid.uuid4().hex[:8]}"
        player_b = f"gmb_{uuid.uuid4().hex[:8]}"
        sid_a = str(uuid.uuid4())
        sid_b = str(uuid.uuid4())

        assert repository.create_multi_character_session(
            sid_a,
            player_a,
            "Player A",
            [character_id, other_id],
            group_name="A 的群聊",
        )
        assert repository.create_multi_character_session(
            sid_b,
            player_b,
            "Player B",
            [character_id, other_id],
            group_name="B 的群聊",
        )
        repository.save_group_memory(
            sid_a,
            "A 用户的群体记忆",
            participants=[character_id, other_id],
        )
        repository.save_group_memory(
            sid_b,
            "B 用户的群体记忆",
            participants=[character_id, other_id],
        )

        results = repository.get_character_group_memories(
            character_id,
            owner_user_id=player_a,
            limit=10,
        )
        memory_text = "\n".join(row["memory_text"] for row in results)

        assert "A 用户的群体记忆" in memory_text
        assert "B 用户的群体记忆" not in memory_text

    def test_multi_character_session_defaults_to_distinct_logical_thread_id(self):
        sid = str(uuid.uuid4())
        player_id = f"gtd_{uuid.uuid4().hex[:8]}"

        assert repository.create_multi_character_session(
            sid,
            player_id,
            "Player",
            ["gc1", "gc2"],
            group_name="默认线程群聊",
        )

        session = repository.get_session(sid)
        thread_id = session["group_thread_id"]
        assert thread_id
        assert thread_id != sid
        assert thread_id.startswith("group-thread-")
        assert repository.get_group_thread_id(sid) == thread_id

    def test_multi_character_thread_history_spans_sessions(self):
        thread_id = str(uuid.uuid4())
        first_sid = str(uuid.uuid4())
        second_sid = str(uuid.uuid4())
        player_id = f"gth_{uuid.uuid4().hex[:8]}"

        assert repository.create_multi_character_session(
            first_sid,
            player_id,
            "Player",
            ["gc1", "gc2"],
            group_name="连续群聊",
            group_thread_id=thread_id,
        )
        assert repository.create_multi_character_session(
            second_sid,
            player_id,
            "Player",
            ["gc1", "gc2"],
            group_name="连续群聊",
            group_thread_id=thread_id,
        )

        repository.append_multi_character_message(first_sid, "user", "第一段消息")
        repository.append_multi_character_message(second_sid, "assistant", "第二段消息", "gc1", "角色一")

        sessions = repository.get_multi_character_thread_sessions(first_sid)
        assert [s["session_id"] for s in sessions] == [first_sid, second_sid]

        history = repository.get_multi_character_thread_history(first_sid, limit_messages=None)
        assert [m["content"] for m in history] == ["第一段消息", "第二段消息"]
        assert [m["session_id"] for m in history] == [first_sid, second_sid]

    def test_multi_character_thread_history_paginates_from_latest_messages(self):
        thread_id = str(uuid.uuid4())
        first_sid = str(uuid.uuid4())
        second_sid = str(uuid.uuid4())
        player_id = f"gthp_{uuid.uuid4().hex[:8]}"

        assert repository.create_multi_character_session(
            first_sid,
            player_id,
            "Player",
            ["gc1", "gc2"],
            group_name="分页群聊",
            group_thread_id=thread_id,
        )
        assert repository.create_multi_character_session(
            second_sid,
            player_id,
            "Player",
            ["gc1", "gc2"],
            group_name="分页群聊",
            group_thread_id=thread_id,
        )

        for index in range(3):
            repository.append_multi_character_message(first_sid, "user", f"旧消息-{index}")
        for index in range(3):
            repository.append_multi_character_message(
                second_sid,
                "assistant",
                f"新消息-{index}",
                "gc1",
                "角色一",
            )

        latest, has_more = repository.get_multi_character_thread_history_paginated(
            second_sid,
            offset=0,
            limit=2,
        )
        older, older_has_more = repository.get_multi_character_thread_history_paginated(
            second_sid,
            offset=2,
            limit=4,
        )

        assert [m["content"] for m in latest] == ["新消息-1", "新消息-2"]
        assert has_more is True
        assert [m["content"] for m in older] == ["旧消息-0", "旧消息-1", "旧消息-2", "新消息-0"]
        assert older_has_more is False

    def test_multi_character_thread_history_keeps_same_name_threads_isolated(self):
        first_sid = str(uuid.uuid4())
        second_sid = str(uuid.uuid4())
        other_player_sid = str(uuid.uuid4())
        player_id = f"gtn_{uuid.uuid4().hex[:8]}"

        assert repository.create_multi_character_session(
            first_sid,
            player_id,
            "Player",
            ["gc1", "gc2"],
            group_name="同名群聊",
            group_thread_id=str(uuid.uuid4()),
        )
        assert repository.create_multi_character_session(
            second_sid,
            player_id,
            "Player",
            ["gc1", "gc2"],
            group_name=" 同名群聊 ",
            group_thread_id=str(uuid.uuid4()),
        )
        assert repository.create_multi_character_session(
            other_player_sid,
            f"other_{uuid.uuid4().hex[:8]}",
            "Other",
            ["gc1", "gc2"],
            group_name="同名群聊",
            group_thread_id=str(uuid.uuid4()),
        )

        repository.append_multi_character_message(first_sid, "user", "同名第一段")
        repository.append_multi_character_message(second_sid, "assistant", "同名第二段", "gc1", "角色一")
        repository.append_multi_character_message(other_player_sid, "user", "其他玩家消息")

        sessions = repository.get_multi_character_thread_sessions(first_sid)
        assert [s["session_id"] for s in sessions] == [first_sid]

        history = repository.get_multi_character_thread_history(first_sid, limit_messages=None)
        assert [m["content"] for m in history] == ["同名第一段"]

    def test_multi_character_thread_incremental_history_is_stable_across_sessions(self):
        thread_id = str(uuid.uuid4())
        first_sid = str(uuid.uuid4())
        second_sid = str(uuid.uuid4())
        player_id = f"gti_{uuid.uuid4().hex[:8]}"

        for session_id in (first_sid, second_sid):
            assert repository.create_multi_character_session(
                session_id,
                player_id,
                "Player",
                ["gc1", "gc2"],
                group_name="增量群聊",
                group_thread_id=thread_id,
            )

        first_id = repository.append_multi_character_message(
            first_sid,
            "user",
            "第一条",
            world_created_at="2026-01-01T08:00:00+00:00",
            trigger_source="player",
        )
        second_id = repository.append_multi_character_message(
            first_sid,
            "assistant",
            "第二条",
            "gc1",
            "角色一",
            reply_to_message_id=first_id,
            intent="answer",
            topic="计划",
            trigger_source="player",
            world_created_at="2026-01-01T08:01:00+00:00",
        )
        third_id = repository.append_multi_character_message(
            second_sid,
            "assistant",
            "第三条",
            "gc2",
            "角色二",
            reply_to_message_id=second_id,
            reply_to_character_id="gc1",
            intent="challenge",
            topic="计划",
            trigger_source="npc_follow_up",
            world_created_at="2026-01-01T08:02:00+00:00",
        )

        first_page, has_more, latest_id = repository.get_multi_character_thread_history_after(
            first_sid,
            after_message_id=0,
            limit=2,
        )
        second_page, second_has_more, second_latest_id = repository.get_multi_character_thread_history_after(
            first_sid,
            after_message_id=second_id,
            limit=2,
        )
        repeated, repeated_has_more, repeated_latest_id = repository.get_multi_character_thread_history_after(
            first_sid,
            after_message_id=second_id,
            limit=2,
        )
        empty, empty_has_more, empty_latest_id = repository.get_multi_character_thread_history_after(
            first_sid,
            after_message_id=third_id,
            limit=2,
        )

        assert [message["message_id"] for message in first_page] == [first_id, second_id]
        assert has_more is True
        assert latest_id == third_id
        assert second_page == repeated
        assert second_has_more is repeated_has_more is False
        assert second_latest_id == repeated_latest_id == third_id
        assert second_page[0] == {
            **second_page[0],
            "message_id": third_id,
            "session_id": second_sid,
            "reply_to_message_id": second_id,
            "reply_to_character_id": "gc1",
            "intent": "challenge",
            "topic": "计划",
            "trigger_source": "npc_follow_up",
            "world_created_at": "2026-01-01T08:02:00+00:00",
        }
        assert empty == []
        assert empty_has_more is False
        assert empty_latest_id == third_id

    def test_update_multi_character_message_preserves_single_row_and_speak_count(self):
        suffix = uuid.uuid4().hex[:8]
        session_id = f"update-group-{suffix}"
        player_id = f"update-player-{suffix}"
        character_id = f"update-character-{suffix}"
        other_character_id = f"update-other-{suffix}"
        for candidate_id in (character_id, other_character_id):
            card = json.dumps({
                "character_id": candidate_id,
                "meta": {"name": candidate_id, "display_name": candidate_id},
            })
            assert repository.save_character_card_to_db(
                player_id,
                candidate_id,
                card,
                name=candidate_id,
                display_name=candidate_id,
            )
        assert repository.create_multi_character_session(
            session_id,
            player_id,
            "Player",
            [character_id, other_character_id],
        )
        player_message_id = repository.append_multi_character_message(
            session_id,
            "user",
            "原问题",
        )
        message_id = repository.append_multi_character_message(
            session_id,
            "assistant",
            "原回复",
            character_id,
            "角色一",
            reply_to_message_id=player_message_id,
            intent="answer",
        )

        assert repository.update_multi_character_message(
            message_id,
            session_id,
            content="事件改写后的回复",
            character_id=character_id,
            character_name="角色一",
            world_created_at="2026-01-01T08:00:00+00:00",
            knowledge_sources=[{"document_id": "doc-1"}],
            reply_to_message_id=player_message_id,
            reply_to_character_id=None,
            intent="reveal",
            topic="计划",
            trigger_source="player",
        )

        history = repository.get_multi_character_history(
            session_id,
            limit_messages=None,
        )
        participants = repository.get_session_participants(session_id)
        assert [message["content"] for message in history] == [
            "原问题",
            "事件改写后的回复",
        ]
        assert history[-1]["message_id"] == message_id
        assert history[-1]["intent"] == "reveal"
        assert history[-1]["knowledge_sources"] == [{"document_id": "doc-1"}]
        assert next(
            participant["message_count"]
            for participant in participants
            if participant["character_id"] == character_id
        ) == 1

    def test_group_message_notifications_aggregate_and_mark_only_owned_thread(self):
        player_id = f"gun_{uuid.uuid4().hex[:8]}"
        other_player_id = f"gun_other_{uuid.uuid4().hex[:8]}"
        thread_id = str(uuid.uuid4())
        other_thread_id = str(uuid.uuid4())
        session_id = str(uuid.uuid4())

        repository.upsert_group_message_notification(
            player_id,
            thread_id,
            session_id,
            2,
            group_name="行动组",
        )
        repository.upsert_group_message_notification(
            player_id,
            thread_id,
            session_id,
            3,
            group_name="行动组",
        )
        repository.upsert_group_message_notification(
            player_id,
            other_thread_id,
            session_id,
            4,
        )
        repository.upsert_group_message_notification(
            other_player_id,
            thread_id,
            session_id,
            6,
        )

        player_unread = repository.list_player_event_inbox(player_id)
        thread_notification = next(
            row for row in player_unread if row["group_thread_id"] == thread_id
        )
        assert thread_notification["unread_count"] == 5
        assert thread_notification["content"] == "群聊中有 5 条新消息"

        assert repository.mark_group_thread_notifications_read(player_id, thread_id) == 1
        remaining = repository.list_player_event_inbox(player_id)
        assert [row["group_thread_id"] for row in remaining] == [other_thread_id]
        other_player_unread = repository.list_player_event_inbox(other_player_id)
        assert other_player_unread[0]["unread_count"] == 6

    def test_multi_character_thread_history_filters_created_after(self):
        sid = str(uuid.uuid4())
        player_id = f"gcf_{uuid.uuid4().hex[:8]}"
        assert repository.create_multi_character_session(
            sid,
            player_id,
            "Player",
            ["gc1", "gc2"],
            group_name="关系变更群聊",
        )
        repository.append_multi_character_message(sid, "user", "旧关系历史")
        repository.append_multi_character_message(sid, "assistant", "新关系历史", "gc1", "角色一")

        with repository.get_conn() as conn:
            conn.execute(
                "UPDATE short_term_message SET created_at=? WHERE session_id=? AND content=?",
                ("2026-01-01T00:00:00+00:00", sid, "旧关系历史"),
            )
            conn.execute(
                "UPDATE short_term_message SET created_at=? WHERE session_id=? AND content=?",
                ("2026-01-02T00:00:00+00:00", sid, "新关系历史"),
            )

        history = repository.get_multi_character_thread_history(
            sid,
            limit_messages=None,
            created_after="2026-01-02T00:00:00+00:00",
        )
        assert [m["content"] for m in history] == ["新关系历史"]

    def test_multi_character_history_filters_created_after(self):
        sid = str(uuid.uuid4())
        player_id = f"gch_{uuid.uuid4().hex[:8]}"
        assert repository.create_multi_character_session(
            sid,
            player_id,
            "Player",
            ["gc1", "gc2"],
            group_name="当前会话过滤",
        )
        repository.append_multi_character_message(sid, "user", "旧当前会话历史")
        repository.append_multi_character_message(sid, "assistant", "新当前会话历史", "gc1", "角色一")

        with repository.get_conn() as conn:
            conn.execute(
                "UPDATE short_term_message SET created_at=? WHERE session_id=? AND content=?",
                ("2026-01-01T00:00:00+00:00", sid, "旧当前会话历史"),
            )
            conn.execute(
                "UPDATE short_term_message SET created_at=? WHERE session_id=? AND content=?",
                ("2026-01-02T00:00:00+00:00", sid, "新当前会话历史"),
            )

        history = repository.get_multi_character_history(
            sid,
            limit_messages=None,
            created_after="2026-01-02T00:00:00+00:00",
        )
        assert [m["content"] for m in history] == ["新当前会话历史"]

    def test_player_group_name_exists_matches_trimmed_names(self):
        sid = str(uuid.uuid4())
        player_id = f"pgn_{uuid.uuid4().hex[:8]}"
        assert repository.create_multi_character_session(
            sid,
            player_id,
            "Player",
            ["gc1", "gc2"],
            group_name="旅团作战室",
        )
        assert repository.player_group_name_exists(player_id, " 旅团作战室 ")
        assert not repository.player_group_name_exists(player_id, "另一个群聊")

    def test_single_character_history_excludes_group_messages(self):
        character_id = f"mixc_{uuid.uuid4().hex[:8]}"
        player_id = f"mixp_{uuid.uuid4().hex[:8]}"
        single_sid = str(uuid.uuid4())
        group_sid = str(uuid.uuid4())

        repository.create_session(single_sid, character_id, player_id, "Player")
        repository.append_short_term_message(single_sid, "user", "单聊消息")
        assert repository.create_multi_character_session(
            group_sid,
            player_id,
            "Player",
            [character_id, f"mixc2_{uuid.uuid4().hex[:8]}"],
            group_name="不会混入单聊的群",
        )
        repository.append_multi_character_message(group_sid, "user", "群聊消息")

        messages, _ = repository.get_messages_by_player_and_character(character_id, player_id, limit=20)
        contents = [m["content"] for m in messages]
        assert "单聊消息" in contents
        assert "群聊消息" not in contents

class TestDedup:
    def test_long_term_dedup(self):
        i1 = repository.save_long_term_fact("dC","dP","测试记忆去重功能",5)
        i2 = repository.save_long_term_fact("dC","dP","测试记忆去重功能",8)
        assert i2 == i1

    def test_session_summary_dedup(self):
        repository.save_session_summary("ds1","dC","dP","v1",5)
        repository.save_session_summary("ds1","dC","dP","v2",10)
        s = repository.get_session_summary("ds1")
        assert s["summary_text"] == "v2"

    def test_shared_memory_dedup(self):
        m1 = repository.save_shared_memory("user_dedup","dA","dB","一起去探险",importance=0.5)
        m2 = repository.save_shared_memory("user_dedup","dA","dB","一起去探险",importance=0.9)
        assert m2 == m1

    def test_group_memory_dedup(self):
        g1 = repository.save_group_memory("dg1","全体集结出发",["x"],0.5)
        g2 = repository.save_group_memory("dg1","全体集结出发了",["x"],0.8)
        assert g2 == g1


class TestGroupDialoguePulseCommit:
    def test_commit_maps_temporary_ids_and_updates_all_state(self):
        suffix = uuid.uuid4().hex[:8]
        session_id = f"atomic-group-session-{suffix}"
        thread_id = f"atomic-group-thread-{suffix}"
        player_id = f"atomic-group-player-{suffix}"
        assert repository.create_multi_character_session(
            session_id,
            player_id,
            "Player",
            ["c1", "c2"],
            group_name="行动组",
            group_thread_id=thread_id,
        )
        repository.save_group_dialogue_state(thread_id, player_id)
        assert repository.claim_group_dialogue_state(
            thread_id,
            lease_owner="worker-1",
            lease_expires_at="2026-01-02T12:10:00+00:00",
            real_now_iso="2026-01-02T12:00:00+00:00",
        )

        committed = repository.commit_group_dialogue_pulse(
            thread_id,
            session_id,
            player_id,
            [
                {
                    "message_id": -1,
                    "character_id": "c1",
                    "character_name": "甲",
                    "dialogue": "先侦查。",
                    "current_affinity": 3,
                    "current_trust": 12,
                    "current_mood": "警觉",
                },
                {
                    "message_id": -2,
                    "character_id": "c2",
                    "character_name": "乙",
                    "dialogue": "我补充路线。",
                    "reply_to_message_id": -1,
                    "reply_to_character_id": "c1",
                    "current_affinity": 4,
                    "current_trust": 13,
                    "current_mood": "专注",
                },
            ],
            lease_owner="worker-1",
            real_now_iso="2026-01-02T12:00:00+00:00",
            world_now_iso="2026-01-02T20:00:00+00:00",
            autonomous_message_count=2,
            daily_message_date="2026-01-02",
            current_topic="侦查",
            topic_source="goal",
            last_reply_to_message_id=-1,
            last_reply_to_character_id="c1",
            last_speaker_id="c2",
            waiting_for_player=False,
            unresolved_hooks=[{"message_id": -2, "character_id": "c2"}],
            group_name="行动组",
        )

        assert committed[0]["message_id"] > 0
        assert committed[1]["message_id"] > committed[0]["message_id"]
        assert committed[1]["reply_to_message_id"] == committed[0]["message_id"]
        state = repository.get_group_dialogue_state(thread_id)
        assert state["lease_owner"] is None
        assert state["last_reply_to_message_id"] == committed[0]["message_id"]
        assert state["unresolved_hooks"][0]["message_id"] == committed[1]["message_id"]
        assert state["daily_message_count"] == 2
        participants = {
            row["character_id"]: row
            for row in repository.get_session_participants(session_id, only_active=False)
        }
        assert participants["c1"]["message_count"] == 1
        assert participants["c2"]["message_count"] == 1
        inbox = repository.list_player_event_inbox(player_id)
        assert len(inbox) == 1
        assert inbox[0]["unread_count"] == 2

    def test_commit_suppresses_duplicate_responses(self):
        suffix = uuid.uuid4().hex[:8]
        session_id = f"dedup-group-session-{suffix}"
        thread_id = f"dedup-group-thread-{suffix}"
        player_id = f"dedup-group-player-{suffix}"
        assert repository.create_multi_character_session(
            session_id,
            player_id,
            "Player",
            ["c1", "c2"],
            group_thread_id=thread_id,
        )
        repository.save_group_dialogue_state(thread_id, player_id)
        assert repository.claim_group_dialogue_state(
            thread_id,
            lease_owner="worker-dedup",
            lease_expires_at="2026-01-02T12:10:00+00:00",
            real_now_iso="2026-01-02T12:00:00+00:00",
        )

        committed = repository.commit_group_dialogue_pulse(
            thread_id,
            session_id,
            player_id,
            [
                {
                    "message_id": -1,
                    "character_id": "c1",
                    "character_name": "甲",
                    "dialogue": "我们先去北门侦查。",
                },
                {
                    "message_id": -2,
                    "character_id": "c1",
                    "character_name": "甲",
                    "dialogue": "我们先去北门侦查！",
                    "reply_to_message_id": -1,
                },
            ],
            lease_owner="worker-dedup",
            real_now_iso="2026-01-02T12:00:00+00:00",
            world_now_iso="2026-01-02T20:00:00+00:00",
            autonomous_message_count=2,
            daily_message_date="2026-01-02",
            current_topic="侦查",
            topic_source="goal",
            last_reply_to_message_id=-2,
            last_reply_to_character_id="c1",
            last_speaker_id="c1",
            waiting_for_player=False,
            unresolved_hooks=[],
        )

        history = repository.get_multi_character_history(
            session_id,
            limit_messages=None,
        )
        state = repository.get_group_dialogue_state(thread_id)
        participants = repository.get_session_participants(
            session_id,
            only_active=False,
        )
        inbox = repository.list_player_event_inbox(player_id)

        assert len(committed) == 1
        assert [message["content"] for message in history] == ["我们先去北门侦查。"]
        assert state["daily_message_count"] == 1
        assert state["waiting_for_player"] is True
        assert sum(row["message_count"] for row in participants) == 1
        assert inbox[0]["unread_count"] == 1

    def test_notification_failure_rolls_back_entire_pulse(self, monkeypatch):
        suffix = uuid.uuid4().hex[:8]
        session_id = f"rollback-group-session-{suffix}"
        thread_id = f"rollback-group-thread-{suffix}"
        player_id = f"rollback-group-player-{suffix}"
        assert repository.create_multi_character_session(
            session_id,
            player_id,
            "Player",
            ["c1", "c2"],
            group_thread_id=thread_id,
        )
        repository.save_group_dialogue_state(thread_id, player_id)
        assert repository.claim_group_dialogue_state(
            thread_id,
            lease_owner="worker-rollback",
            lease_expires_at="2026-01-02T12:10:00+00:00",
            real_now_iso="2026-01-02T12:00:00+00:00",
        )
        monkeypatch.setattr(
            repository,
            "_upsert_group_message_notification_in_transaction",
            lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("inbox failed")),
        )

        with pytest.raises(RuntimeError, match="inbox failed"):
            repository.commit_group_dialogue_pulse(
                thread_id,
                session_id,
                player_id,
                [{
                    "message_id": -1,
                    "character_id": "c1",
                    "character_name": "甲",
                    "dialogue": "准备。",
                    "current_affinity": 9,
                    "current_trust": 18,
                    "current_mood": "警觉",
                }],
                lease_owner="worker-rollback",
                real_now_iso="2026-01-02T12:00:00+00:00",
                world_now_iso="2026-01-02T20:00:00+00:00",
                autonomous_message_count=1,
                daily_message_date="2026-01-02",
                current_topic="准备",
                topic_source="goal",
                last_reply_to_message_id=None,
                last_reply_to_character_id=None,
                last_speaker_id="c1",
                waiting_for_player=False,
                unresolved_hooks=[],
            )

        assert repository.get_multi_character_history(
            session_id,
            limit_messages=None,
        ) == []
        state = repository.get_group_dialogue_state(thread_id)
        assert state["lease_owner"] == "worker-rollback"
        assert state["daily_message_count"] == 0
        participants = repository.get_session_participants(session_id, only_active=False)
        assert all(row["message_count"] == 0 for row in participants)
        assert repository.list_player_event_inbox(player_id) == []
        with repository.get_conn() as conn:
            relationship = conn.execute(
                """
                SELECT 1 FROM relationship_state
                WHERE player_id = ? AND character_id = 'c1'
                """,
                (player_id,),
            ).fetchone()
        assert relationship is None


# ═══════════════════════════════════════════════
# 新增测试 — 代码审查修复验证
# ═══════════════════════════════════════════════

class TestMessageId:
    """P2-10: append_short_term_message 返回消息 ID"""

    def test_append_returns_message_id(self):
        sid = str(uuid.uuid4())
        repository.create_session(sid, "miC", "miP", "Tester")
        msg_id = repository.append_short_term_message(sid, "user", "你好")
        assert isinstance(msg_id, int)
        assert msg_id > 0

    def test_message_id_increases(self):
        sid = str(uuid.uuid4())
        repository.create_session(sid, "mi2C", "mi2P", "Tester")
        id1 = repository.append_short_term_message(sid, "user", "你好")
        id2 = repository.append_short_term_message(sid, "assistant", "你好呀")
        assert id2 > id1


class TestSummaryStatus:
    """P0-2: session_summary 包含 summary_status 字段"""

    def test_save_with_status(self):
        sid = str(uuid.uuid4())
        repository.save_session_summary(sid, "ssC", "ssP", "测试摘要", 10, summary_status="generating")
        s = repository.get_session_summary(sid)
        assert s is not None
        assert s.get("summary_status") == "generating"

    def test_default_status_is_completed(self):
        sid = str(uuid.uuid4())
        repository.save_session_summary(sid, "dsC", "dsP", "默认状态", 5)
        s = repository.get_session_summary(sid)
        assert s is not None
        assert s.get("summary_status") == "completed"

    def test_status_transition(self):
        sid = str(uuid.uuid4())
        repository.save_session_summary(sid, "stC", "stP", "", 3, summary_status="generating")
        repository.save_session_summary(sid, "stC", "stP", "最终摘要", 3, summary_status="completed")
        s = repository.get_session_summary(sid)
        assert s is not None
        assert s.get("summary_status") == "completed"
        assert "最终摘要" in s["summary_text"]


class TestLatestActiveSession:
    """P2-11: get_latest_active_session 断线恢复查询"""

    def test_returns_none_when_no_active(self):
        result = repository.get_latest_active_session(player_id="noone")
        assert result is None

    def test_returns_active_session(self):
        sid = str(uuid.uuid4())
        repository.create_session(sid, "lsC", "lsP", "Tester")
        result = repository.get_latest_active_session(player_id="lsP")
        assert result is not None
        assert result["session_id"] == sid
        assert result["status"] == "active"

    def test_ended_session_not_returned(self):
        sid = str(uuid.uuid4())
        repository.create_session(sid, "esC", "esP", "Tester")
        repository.end_session(sid)
        result = repository.get_latest_active_session(player_id="esP")
        assert result is None

    def test_character_filter(self):
        sid1 = str(uuid.uuid4())
        sid2 = str(uuid.uuid4())
        repository.create_session(sid1, "cfA", "cfP", "Tester")
        repository.create_session(sid2, "cfB", "cfP", "Tester")
        result = repository.get_latest_active_session(player_id="cfP", character_id="cfA")
        assert result is not None
        assert result["character_id"] == "cfA"


class TestSessionListFields:
    def test_player_sessions_include_display_fields_and_last_message_time(self):
        cid = f"sl_{uuid.uuid4().hex[:8]}"
        sid = str(uuid.uuid4())
        card = json.dumps({"character_id": cid, "meta": {"name": "列表角色", "display_name": "列表"}})
        assert repository.save_character_card_to_db(
            "slP",
            cid,
            card,
            name="列表角色",
            display_name="列表",
            avatar_url="https://example.test/avatar.png",
        )
        repository.create_session(sid, cid, "slP", "Tester")
        repository.append_short_term_message(sid, "assistant", "最后一句")

        sessions = repository.get_all_player_sessions("slP")
        session = next(s for s in sessions if s["session_id"] == sid)

        assert session["name"] == "列表角色"
        assert session["display_name"] == "列表"
        assert session["avatar_url"] == "https://example.test/avatar.png"
        assert session["last_message"] == "最后一句"
        assert session["last_message_at"] is not None

    def test_single_player_session_preview_uses_latest_character_message_across_sessions(self):
        cid = f"slc_{uuid.uuid4().hex[:8]}"
        player_id = f"slp_{uuid.uuid4().hex[:8]}"
        old_sid = str(uuid.uuid4())
        empty_sid = str(uuid.uuid4())

        repository.create_session(old_sid, cid, player_id, "Tester")
        repository.append_short_term_message(old_sid, "user", "旧会话用户消息")
        repository.append_short_term_message(old_sid, "assistant", "旧会话最后一句")
        repository.create_session(empty_sid, cid, player_id, "Tester")

        sessions = repository.get_all_player_sessions(player_id)
        empty_session = next(s for s in sessions if s["session_id"] == empty_sid)

        assert empty_session["last_message"] == "旧会话最后一句"
        assert empty_session["last_message_at"] is not None
        assert empty_session["message_count"] == 2

    def test_group_session_list_aggregates_logical_thread_and_unread_count(self):
        player_id = f"slg_{uuid.uuid4().hex[:8]}"
        thread_id = str(uuid.uuid4())
        first_sid = str(uuid.uuid4())
        second_sid = str(uuid.uuid4())

        for session_id in (first_sid, second_sid):
            assert repository.create_multi_character_session(
                session_id,
                player_id,
                "Tester",
                ["slg-c1", "slg-c2"],
                group_name="逻辑线程",
                group_thread_id=thread_id,
            )
        repository.end_session(first_sid)
        first_message_id = repository.append_multi_character_message(
            first_sid,
            "user",
            "线程旧消息",
        )
        latest_message_id = repository.append_multi_character_message(
            second_sid,
            "assistant",
            "线程最新消息",
            "slg-c1",
            "角色一",
        )
        repository.upsert_group_message_notification(
            player_id,
            thread_id,
            second_sid,
            3,
            group_name="逻辑线程",
        )

        sessions = repository.get_all_player_sessions(player_id)
        groups = [session for session in sessions if session["is_multi_character"]]

        assert len(groups) == 1
        assert groups[0]["session_id"] == second_sid
        assert groups[0]["group_thread_id"] == thread_id
        assert groups[0]["latest_message_id"] == latest_message_id
        assert groups[0]["latest_message_id"] > first_message_id
        assert groups[0]["last_message"] == "线程最新消息"
        assert groups[0]["message_count"] == 2
        assert groups[0]["unread_count"] == 3

    def test_paginated_messages_include_message_id(self):
        sid = str(uuid.uuid4())
        repository.create_session(sid, "pmC", "pmP", "Tester")
        msg_id = repository.append_short_term_message(sid, "user", "带 ID 的消息")

        messages, has_more = repository.get_messages_paginated(sid, offset=0, limit=20)

        assert has_more is False
        assert messages[0]["message_id"] == msg_id

    def test_paginated_messages_include_relationship_state(self):
        sid = str(uuid.uuid4())
        repository.create_session(sid, "pmStateC", "pmStateP", "Tester")
        repository.append_short_term_message(
            sid,
            "assistant",
            "关系变化",
            action="smile",
            affinity_delta=1.5,
            trust_delta=2.0,
            current_affinity=11.5,
            current_trust=22.0,
            current_mood="happy",
            event_notification="信任提升",
        )

        messages, has_more = repository.get_messages_paginated(sid, offset=0, limit=20)

        assert has_more is False
        assert messages[0]["action"] == "smile"
        assert messages[0]["affinity_delta"] == 1.5
        assert messages[0]["trust_delta"] == 2.0
        assert messages[0]["current_affinity"] == 11.5
        assert messages[0]["current_trust"] == 22.0
        assert messages[0]["current_mood"] == "happy"
        assert messages[0]["event_notification"] == "信任提升"

    def test_cross_session_history_pages_from_latest_messages(self):
        cid = f"hist_{uuid.uuid4().hex[:8]}"
        player_id = f"player_{uuid.uuid4().hex[:8]}"
        sid1 = str(uuid.uuid4())
        sid2 = str(uuid.uuid4())
        repository.create_session(sid1, cid, player_id, "Tester")
        repository.append_short_term_message(sid1, "user", "old-1")
        repository.append_short_term_message(sid1, "assistant", "old-2")
        repository.create_session(sid2, cid, player_id, "Tester")
        repository.append_short_term_message(sid2, "user", "new-1")
        repository.append_short_term_message(sid2, "assistant", "new-2")

        latest, has_more = repository.get_messages_by_player_and_character(cid, player_id, offset=0, limit=2)
        older, older_has_more = repository.get_messages_by_player_and_character(cid, player_id, offset=2, limit=2)

        assert [m["content"] for m in latest] == ["new-1", "new-2"]
        assert has_more is True
        assert [m["content"] for m in older] == ["old-1", "old-2"]
        assert older_has_more is False
