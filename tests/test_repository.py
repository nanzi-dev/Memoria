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

class TestCharacterCard:
    def test_save_list_delete(self):
        import json
        cid = f"tc_{uuid.uuid4().hex[:8]}"
        card = json.dumps({"character_id":cid,"meta":{"name":"T","display_name":"T"}})
        assert repository.save_character_card_to_db(cid,card,name="T",display_name="T")
        cards = repository.list_character_cards_from_db(only_active=False)
        assert any(c["character_id"]==cid for c in cards)
        assert repository.delete_character_card_from_db(cid)
        assert repository.activate_character_card(cid)
        assert repository.delete_character_card_from_db(cid,soft_delete=False)

class TestEventDefinition:
    def test_crud(self):
        eid = f"ev_{uuid.uuid4().hex[:8]}"
        assert repository.save_event_definition(eid,"Test Evt","{}","[]",priority=5)
        evt = repository.get_event_definition(eid)
        assert evt is not None
        assert evt["priority"] == 5
        lst = repository.list_event_definitions(only_active=False)
        assert any(e["event_id"]==eid for e in lst)
        repository.increment_event_trigger_count(eid)
        repository.log_event_trigger(eid,"tc","tp","sess",'{}','[]')
        hist = repository.get_event_trigger_history(event_id=eid)
        assert len(hist) >= 1
        assert repository.delete_trigger_history(eid,"tc","tp") >= 1
        assert repository.delete_event_definition(eid)

class TestRelationship:
    def test_crud(self):
        assert repository.save_character_relationship("rA","rB","friend",50.0,"friends")
        rel = repository.get_character_relationship("rA","rB")
        assert rel is not None
        assert rel["relationship_type"] == "friend"
        rels = repository.list_character_relationships("rA")
        assert len(rels) >= 1
        repository.update_relationship_affinity("rA","rB",10.0)
        rel2 = repository.get_character_relationship("rA","rB")
        assert rel2["affinity"] == 60.0
        assert repository.delete_character_relationship("rA","rB")

class TestMultiSession:
    def test_create_and_participants(self):
        sid = str(uuid.uuid4())
        assert repository.create_multi_character_session(sid,"p1","Player",["c1","c2"],{"c1":1.2,"c2":0.8})
        parts = repository.get_session_participants(sid)
        assert len(parts) == 2
        assert repository.update_participant_frequency(sid,"c1",1.5)
        repository.append_multi_character_message(sid,"assistant","Hi","c1","Char1")
        repository.update_participant_speak_time(sid,"c1")
        hist = repository.get_multi_character_history(sid,5)
        assert len(hist) >= 1
        assert repository.add_participant_to_session(sid,"c3",0.7)
        assert repository.remove_participant_from_session(sid,"c3")

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
        assert group["is_multi_character"]

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
        m1 = repository.save_shared_memory("dA","dB","一起去探险",0.5)
        m2 = repository.save_shared_memory("dA","dB","一起去探险",0.9)
        assert m2 == m1

    def test_group_memory_dedup(self):
        g1 = repository.save_group_memory("dg1","全体集结出发",["x"],0.5)
        g2 = repository.save_group_memory("dg1","全体集结出发了",["x"],0.8)
        assert g2 == g1


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

    def test_paginated_messages_include_message_id(self):
        sid = str(uuid.uuid4())
        repository.create_session(sid, "pmC", "pmP", "Tester")
        msg_id = repository.append_short_term_message(sid, "user", "带 ID 的消息")

        messages, has_more = repository.get_messages_paginated(sid, offset=0, limit=20)

        assert has_more is False
        assert messages[0]["message_id"] == msg_id

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
