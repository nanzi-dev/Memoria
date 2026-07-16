from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from memoria.api.event_admin import UNIMPLEMENTED_EFFECTS, UNIMPLEMENTED_TRIGGERS
from memoria.core.character_schema import CharacterCard
from memoria.core.config import configs
from memoria.core.event_schema import EventDefinition
from memoria.core.knowledge_documents import chunk_document, extract_document
from memoria.db import repository
from scripts.seed_story_module import load_story_module, seed_story_module


MODULE_ROOT = Path(__file__).resolve().parents[1] / "examples" / "echo_archive"

CHARACTER_IDS = {
    "echo_ji_heng",
    "echo_lin_qi",
    "echo_tang_yan",
    "echo_jiang_zhao",
    "echo_wen_jing",
    "echo_cheng_shu",
    "echo_xu_zhiyao",
    "echo_shen_man",
    "echo_he_lin",
    "echo_ye_jia",
    "echo_mu_qiao",
    "echo_bai_song",
    "echo_zhong_zhiyuan",
    "echo_shao_qing",
    "echo_song_wenduo",
    "echo_gu_chengjun",
    "echo_liang_shiwen",
    "echo_han_xiuyuan",
    "echo_luo_mian",
    "echo_wei_cen",
    "echo_su_weizhen",
    "echo_gao_xu",
}

MAIN_ENDINGS = {
    "echo_end_controlled_breakthrough",
    "echo_end_after_flood",
    "echo_end_silent_testimony",
    "echo_end_failed_archive",
}

JI_OUTCOMES = {
    "echo_ji_romance",
    "echo_ji_deep_partners",
    "echo_ji_temporary_separation",
    "echo_ji_professional_trust_lost",
}

PLAYER_EXCLUSIVE_GROUPS = {
    "echo_main_choice",
    "echo_ji_choice",
    "echo_main_ending",
    "echo_ji_outcome",
}


@pytest.fixture
def isolated_echo_archive_db(tmp_path, monkeypatch):
    monkeypatch.setattr(configs, "database_url", "")
    monkeypatch.setattr(configs, "database_path", str(tmp_path / "memoria.db"))
    monkeypatch.setattr(
        configs,
        "knowledge_storage_path",
        str(tmp_path / "knowledge"),
    )
    monkeypatch.setattr(configs, "vector_db_path", str(tmp_path / "vectors"))
    repository.init_db()
    return tmp_path


def _read_json(relative_path: str):
    return json.loads((MODULE_ROOT / relative_path).read_text(encoding="utf-8"))


def _walk_conditions(condition):
    yield condition
    for sub_condition in condition.sub_conditions or []:
        yield from _walk_conditions(sub_condition)


def test_echo_archive_static_content_contract():
    module = load_story_module(MODULE_ROOT)
    manifest = module["manifest"]
    player = module["player_character"]
    character_ids = {card.character_id for _, card, _ in module["cards"]}

    assert manifest["module_id"] == "echo_archive"
    assert manifest["title"] == "回声档案"
    assert manifest["player_relationship_token"] == "@player"
    assert player["display_name"] == "许观澜"
    assert player["gender"] == "男"
    assert player["occupation"] == "临岚市公安局特聘犯罪心理顾问"
    assert character_ids == CHARACTER_IDS
    assert len(module["cards"]) == 22
    assert all(
        CharacterCard.model_validate(raw).meta.game_module == "echo_archive"
        for _, _, raw in module["cards"]
    )

    groups = manifest["groups"]
    assert len(groups) == 7
    assert [group["session_id"] for group in groups] == [
        f"echo_v{volume}_session" for volume in range(1, 8)
    ]
    assert [group["thread_id"] for group in groups] == [
        f"echo_v{volume}_thread" for volume in range(1, 8)
    ]
    assert all(set(group["character_ids"]) <= character_ids for group in groups)

    relationships = module["relationships"]
    assert len(relationships) == 72
    valid_nodes = character_ids | {"@player"}
    pairs = set()
    player_edges = []
    for relationship in relationships:
        left = relationship["character_id_a"]
        right = relationship["character_id_b"]
        assert {left, right} <= valid_nodes
        assert left != right
        assert -100 <= relationship["affinity"] <= 100
        pair = tuple(sorted((left, right)))
        assert pair not in pairs
        pairs.add(pair)
        if "@player" in pair:
            player_edges.append(pair)
    assert len(player_edges) == 22
    assert {next(node for node in pair if node != "@player") for pair in player_edges} == (
        character_ids
    )

    knowledge_bases = manifest["knowledge_bases"]
    assert len(knowledge_bases) == 13
    assert len({base["key"] for base in knowledge_bases}) == 13
    assert all(base["name"].startswith("[回声档案]") for base in knowledge_bases)
    assert all(len(base["documents"]) == 2 for base in knowledge_bases)
    assert sum(len(base["documents"]) for base in knowledge_bases) == 26

    document_names = set()
    for knowledge_base in knowledge_bases:
        for binding in knowledge_base["bindings"]:
            assert binding["target_type"] in {
                "global",
                "character",
                "group_thread",
            }
            if binding["target_type"] == "character":
                assert binding["target_id"] in character_ids
            if binding["target_type"] == "group_thread":
                assert binding["target_id"] in {
                    group["thread_id"] for group in groups
                }
        for relative_path in knowledge_base["documents"]:
            path = MODULE_ROOT / relative_path
            assert path.is_file()
            extracted = extract_document(path.name, path.read_bytes())
            assert chunk_document(extracted, document_title=path.name)
            assert path.name not in document_names
            document_names.add(path.name)
    assert len(document_names) == 26

    evaluations = _read_json("retrieval_eval.json")
    assert len(evaluations) == 35
    assert [item["id"] for item in evaluations] == [
        f"echo_eval_{index:02d}" for index in range(1, 36)
    ]
    for evaluation in evaluations:
        assert evaluation["expected_facts"]
        assert set(evaluation["expected_documents"]) <= document_names


def test_echo_archive_has_84_runnable_referenced_events():
    module = load_story_module(MODULE_ROOT)
    events = module["events"]
    event_ids = {event.event_id for event in events}

    assert len(events) == 84
    assert len(event_ids) == 84
    assert all(event.is_active for event in events)
    assert MAIN_ENDINGS <= event_ids
    assert JI_OUTCOMES <= event_ids

    for event in events:
        assert event.event_id.startswith(
            ("echo_v", "echo_choice_", "echo_end_", "echo_ji_", "echo_meta_")
        )
        if event.character_id:
            assert event.character_id in CHARACTER_IDS
        for condition in _walk_conditions(event.trigger_condition):
            assert condition.trigger_type not in UNIMPLEMENTED_TRIGGERS
            if condition.event_id:
                assert condition.event_id in event_ids
        for effect in event.effects:
            assert effect.effect_type not in UNIMPLEMENTED_EFFECTS
            if effect.next_event_id:
                assert effect.next_event_id in event_ids
            if effect.target_character_id:
                assert effect.target_character_id in CHARACTER_IDS
            if effect.proactive_character_id:
                assert effect.proactive_character_id in CHARACTER_IDS
            for branch in effect.branch_conditions or []:
                assert branch["event_id"] in event_ids


def test_echo_archive_choice_and_outcome_graph_is_complete():
    events = {
        event.event_id: event
        for event in (
            EventDefinition.model_validate(raw) for raw in _read_json("events.json")
        )
    }
    phrase_contract = {
        "echo_choice_protect_witness": "保全证人",
        "echo_choice_publish_raw": "公开原始档案",
        "echo_choice_submit_tiered": "提交分级证据",
        "echo_choice_seal_master": "封存主档",
        "echo_choice_trust_ji": "我相信季衡",
        "echo_choice_procedural_exit": "按程序撤离",
        "echo_choice_stay_scene": "继续留在现场",
        "echo_choice_act_alone": "单独行动",
    }
    for event_id, phrase in phrase_contract.items():
        assert phrase in (events[event_id].trigger_condition.keywords or [])

    decision_window_dependencies = {
        condition.event_id
        for condition in _walk_conditions(
            events["echo_meta_decision_window"].trigger_condition
        )
        if condition.event_id
    }
    assert "echo_v7_transition" in decision_window_dependencies

    ji_choices = {
        event_id: event
        for event_id, event in events.items()
        if event.exclusive_group == "echo_ji_choice"
    }
    assert len(ji_choices) == 4
    for event in ji_choices.values():
        referenced = {
            condition.event_id
            for condition in _walk_conditions(event.trigger_condition)
            if condition.event_id
        }
        assert "echo_meta_decision_window" in referenced

    expected_dependencies = {
        "echo_end_controlled_breakthrough": "echo_choice_submit_tiered",
        "echo_end_after_flood": "echo_choice_publish_raw",
        "echo_end_silent_testimony": "echo_choice_protect_witness",
        "echo_end_failed_archive": "echo_choice_seal_master",
        "echo_ji_romance": "echo_choice_trust_ji",
        "echo_ji_deep_partners": "echo_choice_procedural_exit",
        "echo_ji_temporary_separation": "echo_choice_stay_scene",
        "echo_ji_professional_trust_lost": "echo_choice_act_alone",
    }
    for event_id, prerequisite in expected_dependencies.items():
        referenced = {
            condition.event_id
            for condition in _walk_conditions(events[event_id].trigger_condition)
            if condition.event_id
        }
        assert prerequisite in referenced
        assert "echo_meta_decision_window" in referenced

    main_exclusive_groups = {
        events[event_id].exclusive_group for event_id in MAIN_ENDINGS
    }
    ji_exclusive_groups = {
        events[event_id].exclusive_group for event_id in JI_OUTCOMES
    }
    assert main_exclusive_groups == {"echo_main_ending"}
    assert ji_exclusive_groups == {"echo_ji_outcome"}


def test_echo_archive_choice_and_ending_groups_are_player_scoped():
    events = _read_json("events.json")
    grouped_events = {
        group: [
            event
            for event in events
            if event.get("exclusive_group") == group
        ]
        for group in PLAYER_EXCLUSIVE_GROUPS
    }

    assert {group: len(members) for group, members in grouped_events.items()} == {
        "echo_main_choice": 4,
        "echo_ji_choice": 4,
        "echo_main_ending": 4,
        "echo_ji_outcome": 4,
    }
    for members in grouped_events.values():
        assert all(event.get("exclusive_scope") == "player" for event in members)


def test_echo_archive_revelations_remain_distinct_turn_scoped_events():
    events = _read_json("events.json")

    for volume in range(1, 7):
        group = f"echo_v{volume}_revelation"
        members = [
            event
            for event in events
            if event.get("exclusive_group") == group
        ]

        assert {event["event_id"] for event in members} == {
            f"echo_v{volume}_turning_point",
            f"echo_v{volume}_contradiction",
        }
        assert all(
            event.get("exclusive_scope", "turn") == "turn"
            for event in members
        )


def test_echo_archive_v1_to_v6_resolutions_require_both_revelations():
    events = {event["event_id"]: event for event in _read_json("events.json")}

    for volume in range(1, 7):
        turning_point = events[f"echo_v{volume}_turning_point"]
        resolution = events[f"echo_v{volume}_resolution"]
        prerequisites = {
            condition["event_id"]
            for condition in resolution["trigger_condition"]["sub_conditions"]
            if condition["trigger_type"] == "event_history"
        }

        assert {
            f"echo_v{volume}_turning_point",
            f"echo_v{volume}_contradiction",
        } <= prerequisites
        assert turning_point["trigger_condition"]["trigger_type"] == "keyword_match"
        assert turning_point["trigger_condition"]["match_mode"] == "all"
        assert len(turning_point["trigger_condition"]["keywords"]) == 2


def test_echo_archive_readme_reports_the_complete_module_inventory():
    module_files = [
        path
        for path in MODULE_ROOT.rglob("*")
        if path.is_file() and path.name != "PLAYTHROUGH_REPORT.md"
    ]
    readme = (MODULE_ROOT / "README.md").read_text(encoding="utf-8")
    json_line = next(
        line for line in readme.splitlines() if line.startswith("- 27 个 JSON 文件")
    )
    markdown_line = next(
        line
        for line in readme.splitlines()
        if line.startswith("- 29 个 Markdown 文件")
    )

    assert len(module_files) == 56
    assert sum(path.suffix == ".json" for path in module_files) == 27
    assert sum(path.suffix == ".md" for path in module_files) == 29
    assert "56 个可播种内容文件" in readme
    assert "27 个 JSON 文件" in json_line
    assert "`events.json`" in json_line
    assert "29 个 Markdown 文件" in markdown_line
    assert "`攻略.md`" in markdown_line


def test_echo_archive_disclosure_costs_match_the_ending_graph():
    disclosure_costs = (
        MODULE_ROOT / "knowledge" / "v7_disclosure_costs.md"
    ).read_text(encoding="utf-8")

    assert "“沉默证词”通常来自保全证人" in disclosure_costs
    assert "“失效档案”通常来自封存主档" in disclosure_costs


def test_echo_archive_events_match_the_canonical_case_files():
    events = {item["event_id"]: item for item in _read_json("events.json")}
    expected_facts = {
        "echo_v1_clue_audio": ("十四秒", "L-417"),
        "echo_v2_clue_intake": ("周栩", "夜间演练"),
        "echo_v3_clue_isolation": ("十四时零八分", "十四时十九分"),
        "echo_v4_clue_promotion": ("前五天", "融资窗口"),
        "echo_v5_clue_recusal": ("七案回避页", "骑缝"),
        "echo_v6_clue_broker": ("宋闻铎盘", "高叙"),
        "echo_v7_archive_map": ("支持原记录", "撤回状态"),
    }
    for event_id, facts in expected_facts.items():
        serialized = json.dumps(events[event_id], ensure_ascii=False)
        assert all(fact in serialized for fact in facts)

    serialized_events = json.dumps(list(events.values()), ensure_ascii=False)
    assert "镇静用药" not in serialized_events
    assert "替换过七秒" not in serialized_events
    assert "数据经纪人的路由表" not in serialized_events


def test_echo_archive_documented_success_and_failure_routes_reference_real_events():
    event_ids = {item["event_id"] for item in _read_json("events.json")}
    walkthrough = (MODULE_ROOT / "WALKTHROUGH.md").read_text(encoding="utf-8")

    successful_route = [
        "echo_v1_resolution",
        "echo_v2_resolution",
        "echo_v3_resolution",
        "echo_v4_resolution",
        "echo_v5_resolution",
        "echo_v6_resolution",
        "echo_v7_archive_map",
        "echo_choice_submit_tiered",
        "echo_choice_trust_ji",
        "echo_end_controlled_breakthrough",
        "echo_ji_romance",
    ]
    failure_route = [
        "echo_v1_resolution",
        "echo_v2_resolution",
        "echo_v3_resolution",
        "echo_v4_resolution",
        "echo_v5_resolution",
        "echo_v6_resolution",
        "echo_v7_archive_map",
        "echo_choice_seal_master",
        "echo_choice_act_alone",
        "echo_end_failed_archive",
        "echo_ji_professional_trust_lost",
    ]
    assert set(successful_route + failure_route) <= event_ids
    for event_id in successful_route + failure_route:
        assert event_id in walkthrough


def test_echo_archive_walkthrough_documents_actual_event_timing():
    walkthrough = (MODULE_ROOT / "WALKTHROUGH.md").read_text(encoding="utf-8")
    guide = (MODULE_ROOT / "攻略.md").read_text(encoding="utf-8")
    volume_six = walkthrough.split("## 第6卷", 1)[1].split("## 第7卷", 1)[0]
    success_route = walkthrough.split("## 一条成功路线", 1)[1].split(
        "## 一条失败路线", 1
    )[0]
    failure_route = walkthrough.split("## 一条失败路线", 1)[1]

    assert "按程序撤离" not in volume_six
    assert (
        "第1至第6卷的 `echo_vN_resolution` 同时要求 "
        "`echo_vN_turning_point` 和 `echo_vN_contradiction`"
    ) in walkthrough
    assert (
        "`match_mode: all` 要求两个关键词出现在同一条玩家消息中"
    ) in walkthrough
    assert (
        "`EVENT_HISTORY` 只读取检测前已经提交的历史批次"
    ) in walkthrough
    assert "普通依赖不会在同一批次级联" in walkthrough
    assert "除非使用显式 `TRIGGER_EVENT` 链接" in walkthrough
    assert "两个前置事件都已提交后，至少再推进一轮" in walkthrough
    assert (
        "季衡选择只会在 `echo_v7_transition` 完成且 "
        "`echo_meta_decision_window` 已提交后解锁"
    ) in walkthrough

    assert success_route.index("echo_v7_transition") < success_route.index(
        "echo_meta_decision_window"
    )
    assert success_route.index("echo_meta_decision_window") < success_route.index(
        "echo_choice_trust_ji"
    )
    assert failure_route.index("echo_v7_transition") < failure_route.index(
        "echo_meta_decision_window"
    )
    assert failure_route.index("echo_meta_decision_window") < failure_route.index(
        "echo_choice_act_alone"
    )

    assert "转折事件的两个关键词必须放在同一条玩家消息中" in guide
    assert "案件结论同时要求转折事件和矛盾核验已提交" in guide
    assert "普通 `EVENT_HISTORY` 依赖不会在同一批次级联" in guide
    assert (
        "季衡选择需等待 `echo_v7_transition` 和 "
        "`echo_meta_decision_window` 均已提交"
    ) in guide


def test_echo_archive_seeds_all_runtime_assets_idempotently(
    isolated_echo_archive_db,
):
    module = load_story_module(MODULE_ROOT)

    first = seed_story_module(
        MODULE_ROOT,
        password="EchoPass1",
        skip_knowledge_index=True,
    )
    second = seed_story_module(
        MODULE_ROOT,
        skip_knowledge_index=True,
    )

    assert first["module_id"] == "echo_archive"
    assert first["player_character"] == "许观澜"
    assert first["characters"] == 22
    assert first["relationships"] == 72
    assert first["events"] == 84
    assert first["active_events"] == 84
    assert first["knowledge_bases"] == 13
    assert first["knowledge_documents"] == 26
    assert second["created_user"] is False
    assert second["group_session_ids"] == first["group_session_ids"]
    assert second["group_thread_ids"] == first["group_thread_ids"]

    owner_user_id = first["user_id"]
    cards = repository.list_character_cards_from_db(owner_user_id)
    assert len(cards) == 22
    assert {card["character_id"] for card in cards} == CHARACTER_IDS
    assert {card["source"] for card in cards} == {"echo_archive-demo"}
    assert len(repository.list_all_character_relationships(owner_user_id)) == 72

    events = repository.list_event_definitions(
        owner_user_id,
        only_active=False,
    )
    assert len(events) == 84
    assert all(event["is_active"] for event in events)

    manifest_groups = module["manifest"]["groups"]
    assert first["group_session_ids"] == [
        group["session_id"] for group in manifest_groups
    ]
    assert first["group_thread_ids"] == [
        group["thread_id"] for group in manifest_groups
    ]
    for group in manifest_groups:
        session = repository.get_latest_group_thread_session(
            group["thread_id"]
        )
        assert session["session_id"] == group["session_id"]
        assert session["player_id"] == owner_user_id
        assert [
            participant["character_id"]
            for participant in repository.get_session_participants(
                session["session_id"]
            )
        ] == group["character_ids"]

    definitions_by_name = {
        definition["name"]: definition
        for definition in module["manifest"]["knowledge_bases"]
    }
    knowledge_bases = repository.list_knowledge_bases(owner_user_id)
    assert len(knowledge_bases) == 13
    assert {base["name"] for base in knowledge_bases} == set(
        definitions_by_name
    )
    document_count = 0
    for knowledge_base in knowledge_bases:
        documents = repository.list_knowledge_documents(
            owner_user_id,
            knowledge_base["knowledge_base_id"],
        )
        document_count += len(documents)
        assert len(documents) == 2
        assert {
            document["source_type"] for document in documents
        } == {"echo_archive-demo"}

        expected_bindings = {
            (binding["target_type"], binding.get("target_id") or "")
            for binding in definitions_by_name[
                knowledge_base["name"]
            ]["bindings"]
        }
        actual_bindings = {
            (binding["target_type"], binding.get("target_id") or "")
            for binding in repository.list_knowledge_bindings(
                owner_user_id,
                knowledge_base["knowledge_base_id"],
            )
        }
        assert actual_bindings == expected_bindings
    assert document_count == 26
