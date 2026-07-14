"""
API 请求/响应模型验证
"""
import pytest, sys, uuid
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from pydantic import ValidationError

class TestDialogueAPI:
    def test_session_start_request(self):
        from memoria.api.dialogue import SessionStartRequest
        r = SessionStartRequest(character_id="c1",player_id="p1",player_name="T")
        assert r.character_id == "c1"

    def test_session_start_missing_field(self):
        from memoria.api.dialogue import SessionStartRequest
        with pytest.raises(ValidationError):
            SessionStartRequest()

    def test_turn_request(self):
        from memoria.api.dialogue import DialogueTurnRequest
        r = DialogueTurnRequest(session_id="s1",player_message="Hi")
        assert r.player_message == "Hi"

    def test_end_session_request(self):
        from memoria.api.dialogue import SessionEndRequest
        r = SessionEndRequest(session_id="s1")
        assert r.session_id == "s1"

class TestCharacterAdminAPI:
    def test_create_request(self):
        from memoria.api.character_admin import CharacterCardCreateRequest as CreateCharacterRequest
        r = CreateCharacterRequest(character_data={"character_id":"x","meta":{"name":"X","display_name":"X"}})
        assert r.character_data["character_id"] == "x"

    def test_import_request(self):
        from memoria.api.character_admin import ImportFromFileRequest as ImportCharacterRequest
        r = ImportCharacterRequest(character_id="x")
        assert r.character_id == "x"

class TestEventAdminAPI:
    def test_create_event_request(self):
        from memoria.api.event_admin import EventCreateRequest as CreateEventRequest
        r = CreateEventRequest(event_id="e1",event_name="E",
                               trigger_condition={"trigger_type":"affinity_threshold","threshold":10},
                               effects=[{"effect_type":"notify_player"}])
        assert r.event_id == "e1"

    def test_toggle_event(self):
        # Toggle uses query param, no separate model needed
        pass

    def test_deep_event_effect_fields(self):
        from memoria.api.event_admin import EventEffectDTO, ScheduleRegisterRequest
        effect = EventEffectDTO(
            effect_type="npc_proactive_dialogue",
            proactive_character_id="npc_a",
            proactive_prompt="主动推进剧情",
            next_event_id="evt_next",
        )
        assert effect.proactive_character_id == "npc_a"
        assert effect.next_event_id == "evt_next"

        req = ScheduleRegisterRequest(
            event_id="evt_schedule",
            character_id="npc_a",
            player_id="usr_a",
            schedule="*/10 * * * *",
        )
        assert req.schedule == "*/10 * * * *"

        from memoria.api.event_admin import TriggerConditionDTO
        condition = TriggerConditionDTO(trigger_type="time_based", schedule="0 9 * * 0")
        assert condition.schedule == "0 9 * * 0"

    def test_time_event_catch_up_replay_limit_defaults_and_bounds(self):
        from memoria.api.event_admin import TriggerConditionDTO

        default_condition = TriggerConditionDTO(trigger_type="time_based", schedule="0 * * * *")
        assert default_condition.catch_up_replay_limit == 1
        assert TriggerConditionDTO(
            trigger_type="time_based",
            schedule="0 * * * *",
            catch_up_replay_limit=1,
        ).catch_up_replay_limit == 1
        assert TriggerConditionDTO(
            trigger_type="time_based",
            schedule="0 * * * *",
            catch_up_replay_limit=100,
        ).catch_up_replay_limit == 100

        with pytest.raises(ValidationError):
            TriggerConditionDTO(
                trigger_type="time_based",
                schedule="0 * * * *",
                catch_up_replay_limit=0,
            )
        with pytest.raises(ValidationError):
            TriggerConditionDTO(
                trigger_type="time_based",
                schedule="0 * * * *",
                catch_up_replay_limit=101,
            )

class TestRelationshipAPI:
    def test_create_relationship(self):
        from memoria.api.relationship import RelationshipCreateRequest as CreateRelationshipRequest
        r = CreateRelationshipRequest(character_id_a="a",character_id_b="b",
                                       relationship_type="friend",affinity=50.0)
        assert r.relationship_type == "friend"

    def test_update_relationship(self):
        from memoria.api.relationship import RelationshipUpdateRequest as UpdateRelationshipRequest
        r = UpdateRelationshipRequest(relationship_type="enemy",affinity=-30.0)
        assert r.relationship_type == "enemy"

class TestMultiDialogueAPI:
    def test_start_multi_request(self):
        from memoria.api.multi_dialogue import StartMultiSessionRequest
        r = StartMultiSessionRequest(player_id="p",player_name="P",
                                      character_ids=["a","b"])
        assert len(r.character_ids) == 2

    def test_turn_request(self):
        from memoria.api.multi_dialogue import MultiDialogueTurnRequest as MultiTurnRequest
        r = MultiTurnRequest(session_id="s",player_message="Hi")
        assert r.player_message == "Hi"

    def test_session_info_preserves_group_thread_fields(self):
        from memoria.api.dialogue import SessionInfo

        session = SessionInfo(
            session_id="session-1",
            character_id="c1",
            player_id="player-1",
            player_name="Player",
            status="active",
            group_name="小队",
            group_thread_id="thread-1",
            is_multi_character=True,
            last_message="最新剧情",
            last_message_at="2026-01-01T00:00:00+00:00",
            latest_message_id=42,
            message_count=8,
            unread_count=3,
        )

        assert session.model_dump()["group_thread_id"] == "thread-1"
        assert session.model_dump()["latest_message_id"] == 42
        assert session.model_dump()["unread_count"] == 3

class TestCodeReviewFixesAPI:
    """P0-2/P2-10: 新增 API 模型验证"""

    def test_dialogue_turn_response_with_message_ids(self):
        from memoria.api.dialogue import DialogueTurnResponse
        r = DialogueTurnResponse(
            dialogue="你好",
            action="smile",
            affinity_delta=1,
            current_affinity=50,
            current_trust=30,
            current_mood="neutral",
            user_message_id=101,
            assistant_message_id=102
        )
        assert r.current_trust == 30
        assert r.user_message_id == 101
        assert r.assistant_message_id == 102

    def test_dialogue_turn_response_message_ids_optional(self):
        from memoria.api.dialogue import DialogueTurnResponse
        r = DialogueTurnResponse(
            dialogue="你好",
            action="smile",
            affinity_delta=1,
            current_affinity=50,
            current_trust=30,
            current_mood="neutral"
        )
        assert r.user_message_id is None
        assert r.assistant_message_id is None

    def test_session_start_response_with_message_id(self):
        from memoria.api.dialogue import SessionStartResponse
        r = SessionStartResponse(
            session_id="test-sid",
            opening_line="欢迎",
            action="wave",
            current_affinity=20,
            current_trust=15,
            world_created_at="2026-07-14T08:30:00+00:00",
            assistant_message_id=99
        )
        assert r.current_trust == 15
        assert r.world_created_at == "2026-07-14T08:30:00+00:00"
        assert r.assistant_message_id == 99

    def test_history_message_with_message_id(self):
        from memoria.api.dialogue import HistoryMessage
        m = HistoryMessage(role="user", content="你好", message_id=42)
        assert m.message_id == 42

    def test_session_recovery_response(self):
        from memoria.api.dialogue import SessionRecoveryResponse, HistoryMessage
        r = SessionRecoveryResponse(
            found=True,
            session_id="sid-1",
            character_id="char-1",
            character={"character_id": "char-1", "display_name": "测试角色"},
            messages=[
                HistoryMessage(role="assistant", content="欢迎回来", message_id=1)
            ]
        )
        assert r.found is True
        assert r.session_id == "sid-1"
        assert r.character["display_name"] == "测试角色"
        assert len(r.messages) == 1

    def test_session_recovery_not_found(self):
        from memoria.api.dialogue import SessionRecoveryResponse
        r = SessionRecoveryResponse(found=False)
        assert r.found is False
        assert r.session_id is None
        assert r.messages == []
