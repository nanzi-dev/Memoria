"""
关系图谱上下文工具。

这里不定义固定关系类型枚举。图谱里的 relationship_type 和 description
由用户维护，prompt 只负责如实呈现，并把旧关系事实从记忆上下文中隔离出来。
"""

from __future__ import annotations

import re


RELATIONSHIP_CONTEXT_MARKERS = (
    "关系", "之间", "互相", "彼此", "对方", "你们", "他们", "她们",
    "二人", "两人", "称呼", "叫", "承诺", "身份", "定位", "已经是",
    "不再是", "只是", "算是", "成为", "变成",
)

# 这些是“关系事实”常见自然语言词，不是系统支持的关系类型清单。
RELATIONSHIP_CLAIM_TERMS = (
    "师徒", "师父", "师傅", "徒弟", "导师", "老师", "学生", "师生",
    "情侣", "恋人", "爱人", "夫妻", "伴侣", "朋友", "好友", "挚友",
    "敌人", "仇人", "死敌", "宿敌", "对手", "家人", "亲人", "父子",
    "父女", "母子", "母女", "兄弟", "姐妹", "兄妹", "姐弟", "队友",
    "伙伴", "同伴", "盟友", "同事", "陌生人", "陌生", "中立",
    "暧昧", "亲密", "疏远", "背叛", "守护者", "契约", "搭档",
)

# “喜欢/讨厌”也可能描述普通爱好，例如“喜欢猫”，不能单独判定为角色关系事实。
WEAK_RELATIONSHIP_CLAIM_TERMS = (
    "喜欢", "讨厌",
)

# 兼容旧数据里常见的英文 canonical 类型。它只用于判定“当前图谱关系”
# 的自然语言等价说法，不作为可选关系类型枚举，也不改写 prompt 展示。
LEGACY_RELATIONSHIP_TYPE_SYNONYMS = {
    "friend": ("朋友", "好友", "挚友", "友人"),
    "enemy": ("敌人", "仇人", "死敌", "敌对", "敌手"),
    "rival": ("宿敌", "对手", "竞争者"),
    "family": ("家人", "亲人", "父子", "父女", "母子", "母女", "兄弟", "姐妹", "兄妹", "姐弟"),
    "mentor": ("师徒", "师父", "师傅", "徒弟", "导师", "老师", "学生", "师生"),
    "teacher": ("老师", "学生", "师生"),
    "student": ("学生", "老师", "师生"),
    "master": ("师父", "师傅", "徒弟", "师徒"),
    "apprentice": ("徒弟", "师父", "师傅", "师徒"),
    "lover": ("恋人", "情侣", "爱人", "夫妻", "伴侣", "亲密", "暧昧"),
    "love": ("恋人", "情侣", "爱人", "夫妻", "伴侣", "亲密", "暧昧"),
    "partner": ("伙伴", "同伴", "队友", "盟友", "伴侣"),
    "companion": ("伙伴", "同伴", "队友", "盟友"),
    "ally": ("盟友", "伙伴", "同伴", "队友"),
    "colleague": ("同事", "同僚"),
    "stranger": ("陌生人", "陌生", "中立", "不熟"),
    "neutral": ("中立", "陌生", "不熟"),
}

_RELATIONSHIP_CLAIM_PATTERN = re.compile(
    r"(是|不是|成为|变成|算是|不再是|已经是|仍是|只是|当作|视为).{0,24}"
    r"(关系|身份|师|友|侣|敌|仇|对手|家人|亲人|同伴|伙伴|盟友|守护|契约|搭档)"
)
_GENERIC_RELATIONSHIP_CLAIM_PATTERN = re.compile(
    r"(是|不是|成为|变成|算是|不再是|已经是|仍是|只是|当作|视为).{1,24}"
    r"([。！？!?；;\n]|$)"
)
PAIR_REFERENCE_MARKERS = (
    "我", "我们", "咱们", "你", "你们", "他", "她", "他们", "她们",
    "二人", "两人", "彼此", "互相", "对方",
)
EXPLICIT_RELATIONSHIP_MARKERS = (
    "关系", "身份", "定位", "称呼", "承诺",
)


def normalize_aliases(values: list[str] | None) -> list[str]:
    aliases = []
    seen = set()
    for value in values or []:
        alias = str(value or "").strip()
        if not alias:
            continue
        lowered = alias.lower()
        if lowered not in seen:
            aliases.append(alias)
            seen.add(lowered)
    return aliases


def latest_timestamp(*values: str | None) -> str | None:
    latest = None
    for value in values:
        if value and (latest is None or value > latest):
            latest = value
    return latest


def text_contains_term(text: str, term: str) -> bool:
    if not text or not term:
        return False
    if term.isascii():
        return term.lower() in text.lower()
    return term in text


def text_mentions_alias(text: str, aliases: list[str] | None) -> bool:
    return any(text_contains_term(text, alias) for alias in normalize_aliases(aliases))


def _alias_mentions(text: str, aliases: list[str] | None) -> list[str]:
    return [
        alias for alias in normalize_aliases(aliases)
        if text_contains_term(text, alias)
    ]


def _has_generic_alias_relationship_claim(text: str, aliases: list[str] | None) -> bool:
    if not text:
        return False

    alias_mentions = _alias_mentions(text, aliases)
    has_pair_reference = len(alias_mentions) >= 2 or (
        bool(alias_mentions)
        and any(marker in text for marker in PAIR_REFERENCE_MARKERS)
    )
    if not has_pair_reference:
        return False

    return bool(_GENERIC_RELATIONSHIP_CLAIM_PATTERN.search(text))


def has_relationship_context(text: str, aliases: list[str] | None = None) -> bool:
    if not text:
        return False
    if any(marker in text for marker in RELATIONSHIP_CONTEXT_MARKERS):
        return True
    return text_mentions_alias(text, aliases)


def relationship_key(character_id_a: str, character_id_b: str) -> str:
    return f"{character_id_a}_{character_id_b}"


def relationship_map_from_records(records: list[dict] | None) -> dict[str, dict]:
    relationships = {}
    for record in records or []:
        char_a = record.get("character_id_a")
        char_b = record.get("character_id_b")
        if char_a and char_b:
            relationships[relationship_key(char_a, char_b)] = record
    return relationships


def relationship_between(
    character_relationships: dict | None,
    character_id_a: str,
    character_id_b: str
) -> dict | None:
    if not character_relationships:
        return None
    return (
        character_relationships.get(relationship_key(character_id_a, character_id_b))
        or character_relationships.get(relationship_key(character_id_b, character_id_a))
    )


def relationship_summary_for_prompt(relationship: dict) -> str:
    rel_type = str(relationship.get("relationship_type") or "").strip() or "未定义"
    parts = [f"当前关系类型 = {rel_type}"]

    affinity = relationship.get("affinity")
    if affinity is not None:
        try:
            parts.append(f"关系强度 = {float(affinity):g}/100")
        except (TypeError, ValueError):
            pass

    desc = str(relationship.get("description") or "").strip()
    if desc:
        parts.append(f"说明 = {desc}")

    return "；".join(parts)


def undefined_relationship_summary() -> str:
    return "当前关系 = 未定义（不得从角色卡背景、长期记忆或历史发言恢复旧关系）"


def build_relationship_graph_lines(
    participants: list[tuple[str, str]],
    character_relationships: dict | None,
    include_missing: bool = True
) -> list[str]:
    lines = []
    for idx, (char_a, name_a) in enumerate(participants):
        for char_b, name_b in participants[idx + 1:]:
            relationship = relationship_between(character_relationships, char_a, char_b)
            if relationship:
                lines.append(
                    f"- {name_a} 与 {name_b}：{relationship_summary_for_prompt(relationship)}"
                )
            elif include_missing:
                lines.append(f"- {name_a} 与 {name_b}：{undefined_relationship_summary()}")
    return lines


def build_relationship_graph_lines_for_pairs(
    pairs: list[tuple[str, str]],
    character_names: dict[str, str],
    character_relationships: dict | None
) -> list[str]:
    lines = []
    seen = set()
    for char_a, char_b in pairs:
        if not char_a or not char_b or char_a == char_b:
            continue
        pair_key = tuple(sorted((char_a, char_b)))
        if pair_key in seen:
            continue
        seen.add(pair_key)

        name_a = character_names.get(char_a) or char_a
        name_b = character_names.get(char_b) or char_b
        relationship = relationship_between(character_relationships, char_a, char_b)
        if relationship:
            lines.append(
                f"- {name_a} 与 {name_b}：{relationship_summary_for_prompt(relationship)}"
            )
        else:
            lines.append(f"- {name_a} 与 {name_b}：{undefined_relationship_summary()}")
    return lines


def format_relationship_graph_context(lines: list[str] | None) -> str:
    if not lines:
        return ""
    return "\n".join([
        "【当前关系图谱（最高优先级，覆盖角色卡背景）】",
        "下面是当前角色关系的唯一权威事实。",
        "如果角色卡简介、角色卡人物关系、长期记忆、共享记忆、群体记忆或历史发言与本节冲突，必须以本节为准。",
        "关系类型是用户可自定义文本，不要把它改写成系统预设枚举。",
        "关系强度是图谱数值，不固定等同于亲密、敌意或好感；具体含义以关系类型和说明为准。",
        "回答“你们是什么关系”“你和某某是什么关系”这类问题时，只能按本节关系作答。",
        *lines,
        "",
    ])


def _relationship_terms_for_record(relationship: dict | None) -> set[str]:
    if not relationship:
        return set()

    terms = set()
    for key in ("relationship_type", "description"):
        value = str(relationship.get(key) or "").strip()
        if not value:
            continue
        terms.add(value)
        for chunk in re.split(r"[\s,，。；;：:/|（）()【】\[\]、]+", value):
            chunk = chunk.strip()
            if len(chunk) >= 2:
                terms.add(chunk)
            terms.update(LEGACY_RELATIONSHIP_TYPE_SYNONYMS.get(chunk.lower(), ()))
    return terms


def _contains_current_relationship_term(text: str, relationship: dict | None) -> bool:
    return any(text_contains_term(text, term) for term in _relationship_terms_for_record(relationship))


def _relationship_claim_terms_in_text(text: str) -> set[str]:
    return {
        term
        for term in RELATIONSHIP_CLAIM_TERMS
        if text_contains_term(text, term)
    }


def _relationship_allows_term(relationship: dict | None, term: str) -> bool:
    return any(
        text_contains_term(current_term, term) or text_contains_term(term, current_term)
        for current_term in _relationship_terms_for_record(relationship)
    )


def _has_disallowed_relationship_term(text: str, relationship: dict | None) -> bool:
    return any(
        not _relationship_allows_term(relationship, term)
        for term in _relationship_claim_terms_in_text(text)
    )


def is_relationship_memory_text(
    text: str,
    participant_aliases: list[str] | None = None,
    relationship_context: bool = False,
    relationship: dict | None = None
) -> bool:
    if not text:
        return False

    aliases = normalize_aliases(participant_aliases)
    has_claim_term = any(term in text for term in RELATIONSHIP_CLAIM_TERMS)
    has_weak_claim_term = any(term in text for term in WEAK_RELATIONSHIP_CLAIM_TERMS)
    has_current_term = _contains_current_relationship_term(text, relationship)
    has_explicit_marker = any(marker in text for marker in EXPLICIT_RELATIONSHIP_MARKERS)
    has_pair_marker = any(marker in text for marker in PAIR_REFERENCE_MARKERS)
    has_alias = text_mentions_alias(text, aliases)
    has_multiple_aliases = len(_alias_mentions(text, aliases)) >= 2
    has_claim_pattern = bool(_RELATIONSHIP_CLAIM_PATTERN.search(text))
    has_generic_alias_claim = _has_generic_alias_relationship_claim(text, aliases)

    if relationship_context and (
        has_claim_term
        or has_current_term
        or has_explicit_marker
        or has_claim_pattern
        or has_generic_alias_claim
    ):
        return True

    if has_weak_claim_term:
        return has_multiple_aliases or (
            has_alias and (has_pair_marker or has_explicit_marker or has_claim_pattern)
        )

    if has_claim_term or has_current_term:
        return (
            has_alias
            or has_explicit_marker
            or relationship_context
            or (has_pair_marker and has_claim_pattern)
        )

    if has_alias and (has_explicit_marker or has_claim_pattern):
        return True

    if has_generic_alias_claim:
        return True

    return False


def memory_created_before_or_unknown(created_at: str | None, cutoff: str | None) -> bool:
    if not cutoff:
        return False
    if not created_at:
        return True
    return created_at < cutoff


def filter_stale_relationship_memory_records(
    records: list[dict],
    relationship_updated_at: str | None,
    participant_aliases: list[str] | None = None,
    text_key: str = "memory_text",
    relationship_context: bool = False,
    relationship: dict | None = None
) -> list[dict]:
    if not relationship_updated_at:
        return records

    filtered = []
    for record in records:
        text = str(record.get(text_key) or "")
        if (
            memory_created_before_or_unknown(record.get("created_at"), relationship_updated_at)
            and is_relationship_memory_text(
                text,
                participant_aliases,
                relationship_context=relationship_context,
                relationship=relationship,
            )
        ):
            continue
        filtered.append(record)
    return filtered


def relationship_text_conflicts_with_graph(
    text: str,
    relationship: dict | None,
    aliases: list[str] | None = None
) -> bool:
    if not text:
        return False

    if (
        _contains_current_relationship_term(text, relationship)
        and not _has_disallowed_relationship_term(text, relationship)
    ):
        return False

    if not is_relationship_memory_text(text, aliases, relationship_context=False, relationship=relationship):
        return False

    return True
