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

    def test_participant_request(self):
        from memoria.api.multi_dialogue import AddParticipantRequest
        r = AddParticipantRequest(session_id="s",character_id="c",speak_frequency=1.5)
        assert r.speak_frequency == 1.5
