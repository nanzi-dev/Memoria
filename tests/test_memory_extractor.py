"""
记忆萃取与提示构建测试
"""
import pytest, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

class TestPromptBuilder:
    def test_build_system_prompt_structure(self):
        from memoria.core import prompt_builder, character_loader
        card = character_loader.load_character_card("npc_luo_xiaohei")
        prompt = prompt_builder.build_system_prompt(card, {"affection_level":30,"trust_level":50,"current_mood":"开心","known_player_facts":["玩家喜欢猫"]},"测试者")
        assert "罗小黑" in prompt or "小黑" in prompt
        assert "好感度" in prompt
        assert "信任度" in prompt
        assert "测试者" in prompt

    def test_build_multi_character_prompt(self):
        from memoria.core import prompt_builder, character_loader
        c1 = character_loader.load_character_card("npc_luo_xiaohei")
        c2 = character_loader.load_character_card("npc_wuxian")
        prompt = prompt_builder.build_multi_character_system_prompt(
            c1, {"affection_level":30,"trust_level":50,"current_mood":"开心","known_player_facts":[]},
            "测试者",
            other_characters=[{"character_id":"npc_wuxian","name":"巫仙","display_name":"无限","occupation":"修行者"}],
            is_opening=True
        )
        assert "小黑" in prompt or "罗小黑" in prompt
        assert "无限" in prompt or "巫仙" in prompt

    def test_build_system_prompt_affinity_indicator(self):
        from memoria.core import prompt_builder, character_loader
        card = character_loader.load_character_card("npc_luo_xiaohei")
        p_low = prompt_builder.build_system_prompt(card, {"affection_level":-50,"trust_level":10,"current_mood":"neutral","known_player_facts":[]},"T")
        p_high = prompt_builder.build_system_prompt(card, {"affection_level":80,"trust_level":90,"current_mood":"开心","known_player_facts":[]},"T")
        assert p_low != p_high

class TestMemoryExtractor:
    def test_format_messages_empty(self):
        from memoria.core.multi_character_memory import _format_messages_for_extraction as _format_messages
        assert _format_messages([]) == ""

    def test_format_messages_basic(self):
        from memoria.core.multi_character_memory import _format_messages_for_extraction as _format_messages
        msgs = [
            {"role":"user","content":"你好"},
            {"role":"assistant","content":"你好！","character_name":"小黑"},
        ]
        result = _format_messages(msgs)
        assert "你好" in result

    def test_extract_memories_empty(self):
        from memoria.core.multi_character_memory import extract_multi_character_memories as extract_memories
        result = extract_memories("sess", [], [])
        assert result == {}

class TestLLMClient:
    def test_extract_json_valid(self):
        from memoria.core.llm_client import _extract_json
        r = _extract_json('{"dialogue":"你好","action":"greet","affinity_delta":2}')
        assert r is not None
        assert r["dialogue"] == "你好"

    def test_extract_json_invalid(self):
        from memoria.core.llm_client import _extract_json
        r = _extract_json("not json at all")
        assert r is None

    def test_extract_json_with_markdown(self):
        from memoria.core.llm_client import _extract_json
        r = _extract_json('```json\n{"dialogue":"test","action":"a","affinity_delta":0}\n```')
        assert r is not None

    def test_plain_text_fallback(self):
        from memoria.core.llm_client import _plain_text_fallback
        r = _plain_text_fallback("你好，我是小黑")
        assert r["dialogue"] == "你好，我是小黑"
        assert r["_fallback_mode"] is True

    def test_plain_text_fallback_extracts_jsonish_role_fields(self):
        from memoria.core.llm_client import _plain_text_fallback
        raw = '''{
          "dialogue": "别慌。她现在的状态，更像是某种信号接收器。",
          "action": "观察",
          "affinity_delta": 0,
          "trust_delta": -1,
          "mood_after": "平静",
          "memory_worth_keeping": "南子出现类似附身的机械性社交反应。",
        }'''
        r = _plain_text_fallback(raw)
        assert r["dialogue"] == "别慌。她现在的状态，更像是某种信号接收器。"
        assert r["action"] == "观察"
        assert r["trust_delta"] == -1
        assert r["memory_worth_keeping"] == "南子出现类似附身的机械性社交反应。"
        assert r["_fallback_parser"] == "local_json"

    def test_plain_text_fallback_extracts_fields_from_broken_json(self):
        from memoria.core.llm_client import _plain_text_fallback
        raw = '''{
          "dialogue": "按住腰间的武器柄，冷静地打量南子。",
          "action": "观察",
          "affinity_delta": 1,
          "trust_delta": 2,
          "mood_after": "警觉",
          "memory_worth_keeping": "南子的状态需要持续观察。"
        '''
        r = _plain_text_fallback(raw)
        assert r["dialogue"] == "按住腰间的武器柄，冷静地打量南子。"
        assert r["action"] == "观察"
        assert r["affinity_delta"] == 1
        assert r["trust_delta"] == 2
        assert not r["dialogue"].lstrip().startswith("{")
        assert r["_fallback_parser"] == "local_fields"

    def test_plain_text_fallback_hides_provider_rejection(self):
        from memoria.core.llm_client import _plain_text_fallback
        r = _plain_text_fallback("The request was rejected because it was considered high risk")
        assert r["dialogue"] == "……"
        assert r["trust_delta"] == 0

    def test_retry_as_json(self):
        from memoria.core.llm_client import _retry_as_json
        r = _retry_as_json('{"broken json', "deepseek-chat")
        assert r is None

    def test_lazy_init(self):
        from memoria.core.llm_client import _get_client, _MAX_RETRIES
        assert _MAX_RETRIES == 3
        assert callable(_get_client)

    def test_call_role_turn_debug_emits_request_and_raw_response(self, monkeypatch):
        from types import SimpleNamespace
        from memoria.core import llm_client

        calls = []

        class FakeCompletions:
            def create(self, **kwargs):
                calls.append(kwargs)
                return SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            message=SimpleNamespace(
                                content='{"dialogue":"你好","action":"idle","affinity_delta":0}'
                            )
                        )
                    ]
                )

        fake_client = SimpleNamespace(
            chat=SimpleNamespace(completions=FakeCompletions())
        )
        debug_lines = []

        monkeypatch.setattr(llm_client, "_get_client", lambda: fake_client)
        monkeypatch.setattr(llm_client, "_retry_call", lambda fn, *args, **kwargs: fn(*args, **kwargs))

        result = llm_client.call_role_turn(
            "system prompt",
            [{"role": "user", "content": "你好"}],
            debug=True,
            debug_sink=debug_lines.append,
        )

        assert result["dialogue"] == "你好"
        assert calls[0]["messages"][0]["content"] == "system prompt"
        debug_text = "\n".join(debug_lines)
        assert "role_turn.request" in debug_text
        assert "role_turn.raw_response" in debug_text
        assert "system prompt" in debug_text
        assert "dialogue" in debug_text
        assert "你好" in debug_text

class TestConfig:
    def test_defaults(self):
        from memoria.core.config import configs
        assert configs.short_term_memory_turns >= 1
        assert configs.max_output_tokens > 0
        assert configs.vector_search_top_k >= 1

    def test_light_model_fallback(self):
        from memoria.core.config import configs
        assert configs.light_model is not None

class TestCharacterLoader:
    def test_reload_clears_cache(self):
        from memoria.core import character_loader
        card1 = character_loader.load_character_card("npc_luo_xiaohei")
        card2 = character_loader.reload_character_card("npc_luo_xiaohei")
        assert card2.character_id == "npc_luo_xiaohei"

    def test_nonexistent_character(self):
        from memoria.core import character_loader
        with pytest.raises((FileNotFoundError, RuntimeError, Exception)):
            character_loader.load_character_card("nonexistent_character_xyz")

class TestDedupHelpers:
    def test_normalize_whitespace(self):
        from memoria.db.repository import _normalize
        assert _normalize("  玩家  喜欢  猫  ") == "玩家 喜欢 猫"

    def test_normalize_case(self):
        from memoria.db.repository import _normalize
        assert _normalize("Hello World") == "hello world"

    def test_normalize_empty(self):
        from memoria.db.repository import _normalize
        assert _normalize("") == ""
        assert _normalize(None) == ""

    def test_similarity_identical(self):
        from memoria.db.repository import _text_similarity
        assert _text_similarity("玩家喜欢吃火锅", "玩家喜欢吃火锅") == 1.0

    def test_similarity_different(self):
        from memoria.db.repository import _text_similarity
        assert _text_similarity("火锅", "游泳") < 0.5

    def test_similarity_partial(self):
        from memoria.db.repository import _text_similarity
        sim = _text_similarity("玩家喜欢吃火锅", "玩家喜欢吃麻辣火锅")
        assert sim > 0.6
