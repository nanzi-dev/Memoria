"""
角色卡加载模块（Character Loader）

用途：
- 从本地 JSON 文件加载角色卡
- 对 JSON 数据进行 Pydantic 校验
- 提供缓存机制，避免重复 IO 和解析
- 支持热重载（编剧后台更新角色卡）

未来扩展：
- 可替换为数据库加载（接口不变）
- 可扩展为远程 API 加载
"""

from functools import lru_cache
import json
from pathlib import Path

from app.core.character_schema import CharacterCard

# =========================
# 角色卡存储目录
# =========================
CHARACTERS_DIR = Path(__file__).resolve().parent.parent / "characters"


# =========================
# 获取角色列表
# =========================
def list_character_ids():
    """
    列出所有角色卡的 ID(文件名)
    """
    if not CHARACTERS_DIR.exists():
        return []
    return sorted(p.stem for p in CHARACTERS_DIR.glob("*.json"))


# =========================
# 加载角色卡（带缓存）
# =========================
@lru_cache(maxsize=64)  # 缓存最多64个角色卡
def load_character_card(character_id: str) -> CharacterCard:
    """
    加载角色卡（核心函数）

    特点：
    - 本地 JSON 读取
    - 自动 Pydantic 校验
    - LRU 缓存（最多 64 个角色）

    注意：
    - 如果 JSON 格式错误，会在这里直接抛异常
    - 保证进入 runtime 的一定是合法结构
    """
    
    path = CHARACTERS_DIR / f"{character_id}.json"
    
    # -------------------------
    # 文件存在性检查
    # -------------------------
    if not path.exists():
        raise FileNotFoundError(f"角色卡 '{character_id}' 不存在")
    
    try:
        # -------------------------
        # 读取 JSON 文件
        # -------------------------
        raw_text = path.read_text(encoding = "utf-8")

        # -------------------------
        # JSON 解析
        # -------------------------
        raw = json.loads(raw_text)
        
        # -------------------------
        # Pydantic 校验（核心）
        # -------------------------
        return CharacterCard.model_validate(raw)
    
    except json.JSONDecodeError as e:
        raise ValueError(
            f"角色卡 '{character_id}' JSON 格式错误: {e.msg} (行 {e.lineno}, 列 {e.colno})"
        )from e
        
    except Exception as e:
        raise RuntimeError(
            f"加载角色卡 '{character_id}' 时发生错误: {str(e)}"
        )from e
        
# =========================
# 热重载角色卡
# =========================
def reload_character_card(character_id: str) -> CharacterCard:
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
    return load_character_card(character_id)

        