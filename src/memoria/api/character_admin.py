"""
角色卡管理 API 路由

用途：
1. 角色卡的 CRUD 操作（创建、读取、更新、删除）
2. 从文件导入角色卡到数据库
3. 角色卡的启用/禁用管理
"""

import json
import logging
from pathlib import Path
from pydantic import BaseModel, Field
from fastapi import APIRouter, HTTPException

from memoria.core import character_loader
from memoria.core.character_schema import CharacterCard
from memoria.db import repository

logger = logging.getLogger(__name__)
router = APIRouter()


# =========================
# 请求/响应模型
# =========================
class CharacterCardCreateRequest(BaseModel):
    """创建角色卡请求"""
    character_data: dict = Field(..., description="完整的角色卡 JSON 数据")

class CharacterCardUpdateRequest(BaseModel):
    """更新角色卡请求"""
    character_data: dict = Field(..., description="完整的角色卡 JSON 数据")

class CharacterCardListItem(BaseModel):
    """角色卡列表项"""
    character_id: str
    name: str | None = None
    display_name: str | None = None
    version: str | None = None
    is_active: int = 1
    source: str = "db"
    created_at: str | None = None
    updated_at: str | None = None

class CharacterCardDetail(BaseModel):
    """角色卡详情"""
    character_id: str
    card_data: dict
    version: str | None = None
    name: str | None = None
    display_name: str | None = None
    is_active: int = 1
    source: str = "db"
    created_at: str | None = None
    updated_at: str | None = None

class ImportFromFileRequest(BaseModel):
    """从文件导入请求"""
    character_id: str = Field(..., description="要导入的角色 ID（对应文件名）")

class OperationResponse(BaseModel):
    """操作响应"""
    success: bool
    message: str
    character_id: str | None = None


# =========================
# 角色卡列表
# =========================
@router.get("/admin/characters", response_model=list[CharacterCardListItem])
def list_characters_admin(only_active: bool = True):
    """
    获取所有角色卡列表（管理后台）
    
    Args:
        only_active: 是否仅返回启用的角色卡
    """
    try:
        cards = repository.list_character_cards_from_db(only_active=only_active)
        return [CharacterCardListItem(**card) for card in cards]
    except Exception as e:
        logger.error(f"获取角色卡列表失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取角色卡列表失败: {str(e)}")


# =========================
# 获取角色卡详情
# =========================
@router.get("/admin/characters/{character_id}", response_model=CharacterCardDetail)
def get_character_detail(character_id: str):
    """
    获取指定角色卡的完整数据
    
    Args:
        character_id: 角色 ID
    """
    try:
        db_card = repository.get_character_card_from_db(character_id, include_inactive=True)
        
        if not db_card:
            raise HTTPException(status_code=404, detail=f"角色卡 '{character_id}' 不存在")
        
        # 解析 JSON 数据
        card_data = json.loads(db_card["card_data"])
        
        return CharacterCardDetail(
            character_id=db_card["character_id"],
            card_data=card_data,
            version=db_card.get("version"),
            name=db_card.get("name"),
            display_name=db_card.get("display_name"),
            is_active=db_card.get("is_active", 1),
            source=db_card.get("source", "db"),
            created_at=db_card.get("created_at"),
            updated_at=db_card.get("updated_at")
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取角色卡详情失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取角色卡详情失败: {str(e)}")


# =========================
# 创建角色卡
# =========================
@router.post("/admin/characters", response_model=OperationResponse)
def create_character(req: CharacterCardCreateRequest):
    """
    创建新角色卡
    
    Args:
        req: 包含完整角色卡数据的请求
    """
    try:
        # 使用 Pydantic 验证数据格式
        card = CharacterCard.model_validate(req.character_data)
        
        # 检查角色 ID 是否已存在
        existing = repository.get_character_card_from_db(card.character_id)
        if existing:
            raise HTTPException(
                status_code=400, 
                detail=f"角色卡 '{card.character_id}' 已存在，请使用更新接口"
            )
        
        # 保存到数据库
        card_json = json.dumps(req.character_data, ensure_ascii=False, indent=2)
        success = repository.save_character_card_to_db(
            character_id=card.character_id,
            card_data_json=card_json,
            version=card.version,
            name=card.meta.name,
            display_name=card.meta.display_name,
            source="db"
        )
        
        if not success:
            raise HTTPException(status_code=500, detail="保存角色卡到数据库失败")
        
        # 清除缓存
        character_loader.reload_character_card(card.character_id)
        
        return OperationResponse(
            success=True,
            message=f"角色卡 '{card.character_id}' 创建成功",
            character_id=card.character_id
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"创建角色卡失败: {e}")
        raise HTTPException(status_code=400, detail=f"创建角色卡失败: {str(e)}")


# =========================
# 更新角色卡
# =========================
@router.put("/admin/characters/{character_id}", response_model=OperationResponse)
def update_character(character_id: str, req: CharacterCardUpdateRequest):
    """
    更新现有角色卡
    
    Args:
        character_id: 角色 ID
        req: 包含完整角色卡数据的请求
    """
    try:
        # 验证数据格式
        card = CharacterCard.model_validate(req.character_data)
        
        # 检查角色 ID 是否匹配
        if card.character_id != character_id:
            raise HTTPException(
                status_code=400,
                detail=f"URL 中的角色 ID '{character_id}' 与数据中的 '{card.character_id}' 不匹配"
            )
        
        # 检查是否存在
        existing = repository.get_character_card_from_db(character_id)
        if not existing:
            raise HTTPException(
                status_code=404,
                detail=f"角色卡 '{character_id}' 不存在，请使用创建接口"
            )
        
        # 更新到数据库
        card_json = json.dumps(req.character_data, ensure_ascii=False, indent=2)
        success = repository.save_character_card_to_db(
            character_id=card.character_id,
            card_data_json=card_json,
            version=card.version,
            name=card.meta.name,
            display_name=card.meta.display_name,
            source=existing.get("source", "db")  # 保持原来的 source
        )
        
        if not success:
            raise HTTPException(status_code=500, detail="更新角色卡到数据库失败")
        
        # 清除缓存
        character_loader.reload_character_card(character_id)
        
        return OperationResponse(
            success=True,
            message=f"角色卡 '{character_id}' 更新成功",
            character_id=character_id
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"更新角色卡失败: {e}")
        raise HTTPException(status_code=400, detail=f"更新角色卡失败: {str(e)}")


# =========================
# 删除角色卡
# =========================
@router.delete("/admin/characters/{character_id}", response_model=OperationResponse)
def delete_character(character_id: str, permanent: bool = False):
    """
    删除角色卡
    
    Args:
        character_id: 角色 ID
        permanent: 是否永久删除（默认为软删除）
    """
    try:
        # 检查是否存在（包括已禁用的）
        existing = repository.get_character_card_from_db(character_id, include_inactive=True)
        if not existing:
            raise HTTPException(status_code=404, detail=f"角色卡 '{character_id}' 不存在")
        
        # 删除角色关系
        repository.delete_all_relationships_of_character(character_id)
        
        # 删除角色
        success = repository.delete_character_card_from_db(
            character_id=character_id,
            soft_delete=not permanent
        )
        
        if not success:
            raise HTTPException(status_code=500, detail="删除角色卡失败")
        
        # 清除缓存（不尝试重新加载）
        character_loader.load_character_card.cache_clear()
        
        action = "永久删除" if permanent else "禁用"
        return OperationResponse(
            success=True,
            message=f"角色卡 '{character_id}' 已{action}",
            character_id=character_id
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除角色卡失败: {e}")
        raise HTTPException(status_code=500, detail=f"删除角色卡失败: {str(e)}")


# =========================
# 激活角色卡
# =========================
@router.post("/admin/characters/{character_id}/activate", response_model=OperationResponse)
def activate_character(character_id: str):
    """
    激活已禁用的角色卡
    
    Args:
        character_id: 角色 ID
    """
    try:
        success = repository.activate_character_card(character_id)
        
        if not success:
            raise HTTPException(status_code=500, detail="激活角色卡失败")
        
        # 清除缓存
        character_loader.reload_character_card(character_id)
        
        return OperationResponse(
            success=True,
            message=f"角色卡 '{character_id}' 已激活",
            character_id=character_id
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"激活角色卡失败: {e}")
        raise HTTPException(status_code=500, detail=f"激活角色卡失败: {str(e)}")


# =========================
# 从文件导入角色卡
# =========================
@router.post("/admin/characters/import", response_model=OperationResponse)
def import_character_from_file(req: ImportFromFileRequest):
    """
    从 JSON 文件导入角色卡到数据库
    
    Args:
        req: 包含角色 ID 的请求
    """
    try:
        # 构建文件路径
        characters_dir = Path(__file__).resolve().parent.parent / "characters"
        file_path = characters_dir / f"{req.character_id}.json"
        
        if not file_path.exists():
            raise HTTPException(
                status_code=404,
                detail=f"角色卡文件 '{req.character_id}.json' 不存在"
            )
        
        # 读取并验证文件
        raw_text = file_path.read_text(encoding="utf-8")
        raw_data = json.loads(raw_text)
        card = CharacterCard.model_validate(raw_data)
        
        # 保存到数据库
        card_json = json.dumps(raw_data, ensure_ascii=False, indent=2)
        success = repository.save_character_card_to_db(
            character_id=card.character_id,
            card_data_json=card_json,
            version=card.version,
            name=card.meta.name,
            display_name=card.meta.display_name,
            source="file"  # 标记为从文件导入
        )
        
        if not success:
            raise HTTPException(status_code=500, detail="导入角色卡到数据库失败")
        
        # 清除缓存
        character_loader.reload_character_card(card.character_id)
        
        return OperationResponse(
            success=True,
            message=f"角色卡 '{card.character_id}' 从文件导入成功",
            character_id=card.character_id
        )
    
    except HTTPException:
        raise
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"JSON 格式错误: {str(e)}")
    except Exception as e:
        logger.error(f"导入角色卡失败: {e}")
        raise HTTPException(status_code=400, detail=f"导入角色卡失败: {str(e)}")
