"""
Prompt 组装模块

作用：
- 将 CharacterCard + runtime_state → LLM system prompt
- 负责角色扮演约束与输出格式控制
- 输出严格 JSON 格式（由调用层负责解析兜底）
"""

# =========================
# Prompt 模板
# =========================
from app.core.character_schema import CharacterCard


SYSTEM_PROMPT_TEMPLATE = """你现在要完全代入并扮演游戏中的角色"{name}"，
你必须始终保持该角色身份、性格、语言风格与行为逻辑，禁止跳出角色。

【角色身份】
{core_identity_summary}
年龄：{age}　性别：{gender}　身份：{occupation}
外貌特征：{appearance}

【性格】
核心特质：{core_traits}
价值观：{values}
恐惧与禁忌：{fears_and_taboos}
习惯与特征：{quirks}

【说话方式（必须严格遵守）】
语气：{register}
词汇风格：{vocabulary_notes}
句式结构：{sentence_patterns}
口头禅：{catchphrases}
绝不会说的话：{things_never_says}

【背景】
{short_bio}

【当前对话状态】
玩家：{player_name}
好感度：{affinity}/100
信任度：{trust}/100
当前情绪：{current_mood}
已知玩家信息：{known_player_facts}

【交互规则】
初始态度：{initial_attitude_to_player}
未建立信任时避免话题：{topics_to_avoid_unless_trusted}
喜欢的话题：{topics_he_loves}
被冒犯时反应：{response_to_rudeness}

【动作系统】
你可以使用以下不同类型的动作：
【打招呼动作】
{greeting_actions}
【告别动作】
{farewell_actions}
【同意 / 认可动作】
{agreement_actions}
【反对 / 否认动作】
{disagreement_actions}
【情绪反应动作】
{emotional_actions}

【硬性约束】
禁止提及“我是AI”“语言模型”等任何现实身份。
禁止跳出角色或解释系统规则。
必须保持沉浸式对话。

【输出要求（极其重要）】
你必须且只能输出一个 JSON 对象，不允许任何额外文本。
不允许 Markdown，不允许解释，不允许代码块。

JSON 格式如下：
{{"dialogue": "角色对话（可含[动作]）",
  "action": "从上述所有动作分类中选择最符合当前语境的一个动作（必须是原始动作字符串之一，不要自造）",
  "affinity_delta": 整数(-10~10),
  "mood_after": "必须从列表选择：{mood_values}",
  "memory_worth_keeping": "重要事实总结或 null"
}}
"""

# =========================
# 工具函数
# =========================
def _join(items, sep = "、") -> str:
    """
    将列表拼接为自然语言文本
    """
    if not items:
        return "无"
    return sep.join(str(i) for i in items)

def _safe_get_runtime(runtime_state: dict, key: str, default):
    """
    安全获取 runtime 状态中的值，避免 KeyError
    """
    if not isinstance(runtime_state, dict):
        return default
    value = runtime_state.get(key)
    return default if value is None else value


# =========================
# 主 Prompt 构建函数
# =========================
def build_system_prompt(card: CharacterCard, runtime_state: dict, player_name: str):
    """
    构建 system prompt（核心函数）

    输入：
    - card: 角色静态设定
    - runtime_state: 动态状态（好感度/信任/记忆等）
    - player_name: 当前玩家名称
    """
    
    identity = card.identity    # 角色身份
    personality = card.personality # 角色性格
    speech_style = card.speech_style # 角色语言风格
    background = card.background  # 角色背景
    rules = card.interaction_rules # 角色交互规则
    actions = card.action_vocabulary # 角色动作词库
    mood_values = card.runtime_state_schema.current_mood.emotions # 角色情绪列表
    
    # -------------------------
    # runtime 安全提取
    # -------------------------
    known_facts = _safe_get_runtime(runtime_state, "known_player_facts", {}) # 已知玩家信息
    affinity = _safe_get_runtime(runtime_state, "affection_level", 0) # 好感度
    trust = _safe_get_runtime(runtime_state, "trust_level", 0) # 信任度
    current_mood = _safe_get_runtime(runtime_state, "current_mood", card.runtime_state_schema.current_mood.default_mood) # 当前情绪
    
    # -------------------------
    # known facts 兼容处理
    # -------------------------
    if isinstance(known_facts, dict):
        known_facts_str = ";".join([f"{k}:{v}" for k, v in known_facts.items()])
    elif isinstance(known_facts, list):
        known_facts_str = _join(known_facts)
    else:
        known_facts_str = str(known_facts) if known_facts else "暂无"
        
    # -------------------------
    # Prompt 渲染
    # -------------------------
    return SYSTEM_PROMPT_TEMPLATE.format(
        name = card.meta.name,
        
        # identity
        core_identity_summary = identity.core_identity_summary,
        age = identity.age,
        gender = identity.gender,
        occupation = identity.occupation,
        appearance = identity.appearance,
        
        # personality
        core_traits=_join(personality.core_traits),
        values=_join(personality.values_and_beliefs, "；"),
        fears_and_taboos=_join(personality.fears_and_tabooes, "；"),
        quirks=_join(personality.quirks_and_habits, "；"),

        # speech
        register=speech_style.tone_register,
        vocabulary_notes=speech_style.vocabulary_notes,
        sentence_patterns=_join(speech_style.sentence_patterns, "；"),
        catchphrases=_join(speech_style.catchphrases),
        things_never_says=_join(speech_style.things_never_to_say, "；"),

        # background
        short_bio=background.story_bio,

        # runtime
        player_name=player_name,
        affinity=affinity,
        trust=trust,
        current_mood=current_mood,
        known_player_facts=known_facts_str,

        # rules
        initial_attitude_to_player=rules.initial_attitude_to_player,
        topics_to_avoid_unless_trusted=_join(rules.topics_to_avoid_unless_trusted),
        topics_he_loves=_join(rules.topics_he_or_she_loves_to_discuss),
        response_to_rudeness=_join(rules.response_to_rudeness),

        # actions
        greeting_actions=_join(actions.greeting_actions),
        farewell_actions = _join(actions.farewell_actions),
        agreement_actions = _join(actions.agreement_actions),
        disagreement_actions = _join(actions.disagreement_actions),
        emotional_actions = _join(actions.emotional_reactions),

        mood_values=_join(mood_values),
    )

def build_opening_line_prompt(card: CharacterCard, runtime_state: dict, player_name: str) -> str:
    """会话开场白用的简短追加指令，拼在 system prompt 后面一起发送。"""
    return (
        f"\n【特别说明】这是与玩家'{player_name}'的新一轮见面对话，"
        f"请你作为{card.meta.name}，根据当前好感度（{runtime_state.get('affinity', 0)}）和心情，"
        f"主动说一句开场白打招呼，不需要玩家先说话。仍然按要求只输出 JSON。"
    )