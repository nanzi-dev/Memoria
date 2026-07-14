"""
角色卡(Character Card)数据模型定义

用途：
- 用于定义 NPC / 角色的完整结构化信息
- 支持 prompt 生成 / 角色模拟 / 行为约束
- 在加载阶段进行数据校验，避免运行时缺字段问题
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from memoria.core.locale import Locale

# =========================
# 基础元信息
# =========================
class Meta(BaseModel):
    """角色基础元信息"""
    name: str                   # 角色名称
    display_name: str           # 角色显示名称
    aliases: list[str] = Field(default_factory=list)   # 角色别名列表
    game_module: str = ""       # 角色所属游戏模块
    created_by: str = ""        # 角色创建者
    last_updated: str = ""      # 角色最后更新时间
    
# =========================
# 身份信息
# =========================
class Identity(BaseModel):
    """角色身份信息"""
    age: str | int                  # 角色年龄（可以是数字或描述性字符串）
    gender: str                     # 角色性别
    occupation: str                 # 角色职业
    race_or_species: str            # 角色种族或物种
    appearance: str                 # 角色外貌描述
    social_status: str = ""         # 角色社会地位
    core_identity_summary: str = "" # 角色核心身份总结

# =========================
# 性格系统
# =========================
class Personality(BaseModel):
    """角色性格结构"""
    mbti_or_archetype: str = ""                                     # MBTI 或其他性格原型
    core_traits: list[str] = Field(default_factory=list)            # 核心性格特征
    values_and_beliefs: list[str] = Field(default_factory=list)     # 价值观与信念
    fears_and_tabooes: list[str] = Field(default_factory=list)      # 恐惧与禁忌
    quirks_and_habits: list[str] = Field(default_factory=list)      # 怪癖与习惯
    moral_alignment: str = ""                                       # 道德取向

# =========================
# 语言风格
# =========================
class speechStyle(BaseModel):
    """语言表达风格"""
    tone_register: str                                            # 语气
    vocabulary_notes: str                                         # 用词习惯说明
    sentence_patterns: list[str] = Field(default_factory=list)    # 常用句式
    catchphrases: list[str] = Field(default_factory=list)         # 口头禅
    things_never_to_say: list[str] = Field(default_factory=list)  # 禁忌用语
    language: str = "zh-CN"                                       # 语言类型，默认中文
    formality_default: str = ""                                   # 默认正式程度
    
# =========================
# 关键事件
# =========================
class KeyEvent(BaseModel):
    """角色关键事件"""
    event: str                  # 事件描述
    description: str = ""       # 事件详细说明
    emotional_weight: int = 0   # 情感权重，正数为积极，负数为消极
    
# =========================
# 人物关系
# =========================
class Relationship(BaseModel):
    """角色关系"""
    target: str                   # 目标角色ID
    relationship_type: str        # 关系类型（用户自定义文本）
    description: str = ""         # 关系描述
    emotional_weight: int = 0     # 情感权重，正数为积极，负数为消极

# =========================
# 秘密
# =========================
class Secret(BaseModel):
    """角色隐藏信息"""
    secret: str                   # 秘密内容
    description: str = ""         # 秘密详细说明
    reveal_conditions: str        # 揭示条件

# =========================
# 背景故事
# =========================
class Background(BaseModel):
    """角色背景故事"""
    story_bio: str                                                      # 角色背景简介                    
    key_events: list[KeyEvent] = Field(default_factory=list)            # 关键事件列表
    relationships: list[Relationship] = Field(default_factory=list)     # 人物关系列表
    secrets: list[Secret] = Field(default_factory=list)                 # 秘密列表
    
# =========================
# 目标与动机
# =========================
class GoalsAndMotivations(BaseModel):
    """角色目标与动机"""
    current_goals: list[str] = Field(default_factory=list)          # 当前目标列表
    long_term_goals: list[str] = Field(default_factory=list)        # 长期目标列表
    what_triggers_anger: list[str] = Field(default_factory=list)   # 触发愤怒的因素列表
    what_brings_joy: list[str] = Field(default_factory=list)       # 带来快乐的因素列表
    
# =========================
# 交互规则
# =========================
class InteractionRules(BaseModel):
    """角色交互规则"""
    initial_attitude_to_player: str = "neutral"                                    # 角色对玩家的初始态度（如友好、中立、敌对）
    topics_to_avoid_unless_trusted: list[str] = Field(default_factory=list)        # 除非信任，否则避免讨论的话题列表
    topics_he_or_she_loves_to_discuss: list[str] = Field(default_factory=list)     # 角色喜欢讨论的话题列表
    response_to_rudeness: list[str] = Field(default_factory=list)                  # 对粗鲁行为的反应（如忽略、反击、逐渐变得敌对等）
    gift_reactions: list[tuple[str, str]] = Field(default_factory=list)            # 对不同类型礼物的反应（如喜欢、讨厌、无感等）
    
# =========================
# 行为动作词库
# =========================
class ActionVocabulary(BaseModel):
    """角色行为动作词库"""
    # =========================
    # 场景类动作（对话阶段）
    # =========================
    greeting_actions: list[str] = Field(default_factory=list)   # 打招呼
    farewell_actions: list[str] = Field(default_factory=list)   # 告别

    # =========================
    # 意图类动作（语义回应）
    # =========================
    agreement_actions: list[str] = Field(default_factory=list)      # 同意 / 认可
    disagreement_actions: list[str] = Field(default_factory=list)   # 反对 / 否定

    # =========================
    # 情绪类动作（状态驱动）
    # =========================
    emotional_reactions: list[str] = Field(default_factory=list)    # 情绪反应（喜悦/愤怒/悲伤等）

    # =========================
    # 默认与兜底机制
    # =========================
    default_action: str = "neutral"  # 无匹配时使用

    fallback_priority: list[str] = Field(
        default_factory=lambda: [
            "emotional_reactions",
            "agreement_actions",
            "disagreement_actions",
            "greeting_actions",
            "farewell_actions"
        ]
    )                                  # 默认动作
    
# =========================
# 情绪状态结构
# =========================
class MoodSchema(BaseModel):
    """角色情绪状态结构"""
    type: str = "enum"                                   # 情绪类型（如快乐、悲伤、愤怒等）
    emotions: list[str] = Field(default_factory=list)    # 可选情绪集合
    intensity: int = 0                                   # 情绪强度，范围 0-100
    default_mood: str = "neutral"                        # 默认情绪状态

# =========================
# 运行时状态
# =========================
class RelationshipState(BaseModel):
    """运行时关系状态"""
    target_id: str                   # 目标角色ID
    affection_level: float = 0.0     # 好感度
    trust_level: float = 0.0         # 信任度
    
class RuntmeStateSchema(BaseModel):
    """角色运行时状态结构"""
    relationships: list[RelationshipState] = Field(default_factory=list)    # 角色关系状态列表
    current_mood: MoodSchema = Field(default_factory=MoodSchema)            # 当前情绪状态
    known_player_facts: dict[str, str] = Field(default_factory=dict)        # 角色已知的关于玩家的事实字典
    
# =========================
# 安全约束
# =========================
class SafetyConstraints(BaseModel):
    """角色安全约束"""
    topics_to_avoid: list[str] = Field(default_factory=list)        # 需要避免讨论的话题列表
    out_of_character_handling: str = ""                             # OOC处理方式


class CharacterVoice(BaseModel):
    """Speech synthesis settings stored with a character card."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    builtin_voice: str = Field(default="alloy", alias="builtinVoice")
    custom_voice_id: str | None = Field(default=None, alias="customVoiceId")
    custom_voice_status: Literal[
        "unconfigured", "pending", "ready", "unavailable", "failed"
    ] = Field(default="unconfigured", alias="customVoiceStatus")
    tts_instructions: str = Field(default="", alias="ttsInstructions")


class _TranslationOverride(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MetaTranslationOverride(_TranslationOverride):
    name: str | None = None
    display_name: str | None = None
    aliases: list[str] | None = None
    game_module: str | None = None
    created_by: str | None = None


class IdentityTranslationOverride(_TranslationOverride):
    age: str | int | None = None
    gender: str | None = None
    occupation: str | None = None
    race_or_species: str | None = None
    appearance: str | None = None
    social_status: str | None = None
    core_identity_summary: str | None = None


class PersonalityTranslationOverride(_TranslationOverride):
    mbti_or_archetype: str | None = None
    core_traits: list[str] | None = None
    values_and_beliefs: list[str] | None = None
    fears_and_tabooes: list[str] | None = None
    quirks_and_habits: list[str] | None = None
    moral_alignment: str | None = None


class SpeechStyleTranslationOverride(_TranslationOverride):
    tone_register: str | None = None
    vocabulary_notes: str | None = None
    sentence_patterns: list[str] | None = None
    catchphrases: list[str] | None = None
    things_never_to_say: list[str] | None = None
    language: str | None = None
    formality_default: str | None = None


class KeyEventTranslationOverride(_TranslationOverride):
    event: str | None = None
    description: str | None = None
    emotional_weight: int | None = None


class SecretTranslationOverride(_TranslationOverride):
    secret: str | None = None
    description: str | None = None
    reveal_conditions: str | None = None


class BackgroundTranslationOverride(_TranslationOverride):
    story_bio: str | None = None
    key_events: list[KeyEventTranslationOverride] | None = None
    secrets: list[SecretTranslationOverride] | None = None


class GoalsTranslationOverride(_TranslationOverride):
    current_goals: list[str] | None = None
    long_term_goals: list[str] | None = None
    what_triggers_anger: list[str] | None = None
    what_brings_joy: list[str] | None = None


class InteractionRulesTranslationOverride(_TranslationOverride):
    initial_attitude_to_player: str | None = None
    topics_to_avoid_unless_trusted: list[str] | None = None
    topics_he_or_she_loves_to_discuss: list[str] | None = None
    response_to_rudeness: list[str] | None = None
    gift_reactions: list[tuple[str, str]] | None = None


class ActionVocabularyTranslationOverride(_TranslationOverride):
    greeting_actions: list[str] | None = None
    farewell_actions: list[str] | None = None
    agreement_actions: list[str] | None = None
    disagreement_actions: list[str] | None = None
    emotional_reactions: list[str] | None = None
    default_action: str | None = None
    fallback_priority: list[str] | None = None


class SafetyTranslationOverride(_TranslationOverride):
    topics_to_avoid: list[str] | None = None
    out_of_character_handling: str | None = None


class CharacterTranslationOverride(_TranslationOverride):
    """Prompt-visible fields that a locale overlay may replace."""

    meta: MetaTranslationOverride | None = None
    identity: IdentityTranslationOverride | None = None
    personality: PersonalityTranslationOverride | None = None
    speech_style: SpeechStyleTranslationOverride | None = None
    background: BackgroundTranslationOverride | None = None
    goals_and_motivations: GoalsTranslationOverride | None = None
    interaction_rules: InteractionRulesTranslationOverride | None = None
    action_vocabulary: ActionVocabularyTranslationOverride | None = None
    safety_constraints: SafetyTranslationOverride | None = None
    

# =========================
# 角色卡主结构
# =========================
class CharacterCard(BaseModel):
    """
    完整角色卡模型
    
    作用：
    - 定义一个角色的完整静态信息 + 运行时状态
    - 用于prompt生成、角色模拟、行为约束等核心功能
    """
    
    character_id: str = Field(..., description="角色唯一ID")   # 角色唯一ID
    version: str = "1.0.0"                                      # 角色卡版本号
    avatar_url: str | None = Field(default=None, description="角色头像（base64 data URL 或网络 URL）")
    voice: CharacterVoice = Field(default_factory=CharacterVoice)
    i18n: dict[Locale, CharacterTranslationOverride] = Field(default_factory=dict)

    meta: Meta = Field(..., description="角色基础元信息")       # 角色基础元信息
    identity: Identity = Field(..., description="角色身份信息")   # 角色身份
    personality: Personality = Field(..., description="角色性格结构")   # 角色性格结构
    speech_style: speechStyle = Field(..., description="角色语言风格")   # 角色语言风格
    
    background: Background = Field(..., description="角色背景故事")                                                 # 角色背景故事
    goals_and_motivations: GoalsAndMotivations = Field(..., description="角色目标与动机")                           # 角色目标与动机
    
    interaction_rules: InteractionRules = Field(..., description="角色交互规则")                                    # 角色交互规则
    action_vocabulary: ActionVocabulary = Field(..., description="角色行为动作词库")                                 # 角色行为动作词库
    
    runtime_state_schema: RuntmeStateSchema = Field(default_factory=RuntmeStateSchema, description="角色运行时状态")        # 角色运行时状态
    
    safety_constraints: SafetyConstraints = Field(default_factory=SafetyConstraints, description="角色安全约束")    # 角色安全约束
