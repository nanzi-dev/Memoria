"""
角色卡加载模块（Character Loader）

用途：
- 业务请求按用户从数据库加载角色卡
- 开发/测试请求未指定用户时可加载本地 JSON 模板
- 对 JSON 数据进行 Pydantic 校验
- 提供缓存机制，避免重复 IO 和解析
- 支持热重载（编剧后台更新角色卡）
"""

from functools import lru_cache
import json
import logging
from pathlib import Path

from memoria.db import repository
from memoria.core.character_schema import CharacterCard
from memoria.core.locale import Locale

logger = logging.getLogger(__name__)

# =========================
# 角色卡存储目录
# =========================
CHARACTERS_DIR = Path(__file__).resolve().parent.parent / "characters"


def normalize_character_data(raw: dict) -> dict:
    """兼容直接角色卡 JSON 和 {"character_data": {...}} 包装格式。"""
    if isinstance(raw, dict) and isinstance(raw.get("character_data"), dict):
        return raw["character_data"]
    return raw


# =========================
# 获取角色列表
# =========================
def list_character_ids(owner_user_id: str | None = None):
    """
    列出所有角色卡的 ID
    
    传入 owner_user_id 时只列出该用户数据库中的启用角色。
    不传 owner_user_id 时保留开发/测试用的静态文件扫描能力。
    """
    character_ids = set()
    
    # 从数据库获取
    try:
        if owner_user_id is not None:
            db_cards = repository.list_character_cards_from_db(owner_user_id, only_active=True)
            character_ids.update(card["character_id"] for card in db_cards)
    except Exception as e:
        logger.warning(f"从数据库获取角色列表失败: {e}")
    
    # 从文件系统获取
    if owner_user_id is None and CHARACTERS_DIR.exists():
        character_ids.update(p.stem for p in CHARACTERS_DIR.glob("*.json"))
    
    return sorted(character_ids)


# =========================
# 加载角色卡（带缓存）
# =========================
@lru_cache(maxsize=256)
def load_character_card(
    character_id: str,
    owner_user_id: str | None = None,
    locale: Locale | None = None,
) -> CharacterCard:
    """
    加载角色卡（核心函数）

    特点：
    - 传入 owner_user_id 时只从该用户数据库读取
    - 未传 owner_user_id 时保留本地 JSON 文件加载能力，供模板/测试使用
    - 自动 Pydantic 校验
    - LRU 缓存（最多 256 个角色）

    注意：
    - 如果 JSON 格式错误，会在这里直接抛异常
    - 保证进入 runtime 的一定是合法结构
    """
    
    # -------------------------
    # 优先从数据库加载
    # -------------------------
    try:
        db_card = None
        if owner_user_id is not None:
            db_card = repository.get_character_card_from_db(owner_user_id, character_id)
        
        if db_card and db_card.get("card_data"):
            logger.debug(f"从数据库加载角色卡: owner={owner_user_id}, character_id={character_id}")
            raw = normalize_character_data(json.loads(db_card["card_data"]))
            return _localized_character_card(raw, locale)

    except Exception as e:
        logger.warning(f"从数据库加载角色卡 '{character_id}' 失败: {e}")
        if owner_user_id is not None:
            raise

    if owner_user_id is not None:
        raise FileNotFoundError(f"用户 '{owner_user_id}' 的角色卡 '{character_id}' 不存在或已禁用")

    # -------------------------
    # 回退到文件加载
    # -------------------------
    path = CHARACTERS_DIR / f"{character_id}.json"
    
    # -------------------------
    # 文件存在性检查
    # -------------------------
    if not path.exists():
        raise FileNotFoundError(f"角色卡 '{character_id}' 在数据库和文件系统中都不存在")
    
    try:
        logger.debug(f"从文件加载角色卡: {character_id}")
        
        # -------------------------
        # 读取 JSON 文件
        # -------------------------
        raw_text = path.read_text(encoding = "utf-8")

        # -------------------------
        # JSON 解析
        # -------------------------
        raw = normalize_character_data(json.loads(raw_text))
        
        # -------------------------
        # Pydantic 校验（核心）
        # -------------------------
        return _localized_character_card(raw, locale)
    
    except json.JSONDecodeError as e:
        raise ValueError(
            f"角色卡 '{character_id}' JSON 格式错误: {e.msg} (行 {e.lineno}, 列 {e.colno})"
        ) from e
        
    except Exception as e:
        raise RuntimeError(
            f"加载角色卡 '{character_id}' 时发生错误: {str(e)}"
        ) from e
        
# =========================
# 热重载角色卡
# =========================
def reload_character_card(
    character_id: str,
    owner_user_id: str | None = None,
    locale: Locale | None = None,
) -> CharacterCard:
    """
    热重载角色卡（清除缓存并重新加载）

    用途：
    - 当角色卡 JSON 文件被外部修改时，调用此函数可以刷新缓存
    
    实现方式：
    - 清除 cache
    - 重新调用 load
    """
    # 清除缓存
    load_character_card.cache_clear()
    
    # 重新加载
    return load_character_card(character_id, owner_user_id, locale)


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge mappings; supplied lists and scalar values replace."""
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _localized_character_card(raw: dict, locale: Locale | None) -> CharacterCard:
    card = CharacterCard.model_validate(raw)
    if locale is None or locale not in card.i18n:
        return card

    base = card.model_dump(mode="python")
    override = card.i18n[locale].model_dump(exclude_none=True)
    base.pop("i18n", None)
    return CharacterCard.model_validate(_deep_merge(base, override))
