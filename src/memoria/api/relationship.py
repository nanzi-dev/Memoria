"""
角色关系管理 API

用途：
1. 查询、创建、更新角色间关系
2. 获取角色关系网络
3. 支持关系可视化
"""

from typing import Literal

from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, HTTPException

from memoria.api.user import require_current_user_id
from memoria.db import repository

router = APIRouter()


# =========================
# 请求/响应模型
# =========================
class RelationshipCreateRequest(BaseModel):
    """创建关系请求"""
    character_id_a: str = Field(..., description="角色 A ID")
    character_id_b: str = Field(..., description="角色 B ID")
    relationship_type: str = Field(..., description="关系类型，支持自定义文本")
    affinity: float = Field(default=0.0, ge=-100, le=100, description="关系强度（-100 ~ 100）")
    description: str | None = Field(None, description="关系描述")


class RelationshipUpdateRequest(BaseModel):
    """更新关系请求"""
    relationship_type: str | None = None
    affinity: float | None = Field(None, ge=-100, le=100)
    description: str | None = None


class RelationshipInfo(BaseModel):
    """关系信息"""
    id: int
    character_id_a: str
    character_id_b: str
    relationship_type: str
    affinity: float
    description: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class RelationshipNetworkNode(BaseModel):
    """关系网络节点"""
    character_id: str
    node_type: Literal["player", "character"]
    name: str
    avatar_url: str | None = None
    is_active: bool = True


class RelationshipNetworkEdge(BaseModel):
    """关系网络边"""
    source: str
    target: str
    relationship_type: str
    affinity: float
    description: str | None = None


class RelationshipNetwork(BaseModel):
    """关系网络"""
    nodes: list[RelationshipNetworkNode]
    edges: list[RelationshipNetworkEdge]


class OperationResponse(BaseModel):
    """操作响应"""
    success: bool
    message: str


def _require_relationship_characters(
    current_user_id: str,
    character_id_a: str,
    character_id_b: str,
) -> None:
    """Require distinct nodes owned by the current user."""
    if character_id_a == character_id_b:
        raise HTTPException(status_code=400, detail="不能创建角色与自身的关系")

    current_player_node = repository.player_node_id(current_user_id)
    for character_id in (character_id_a, character_id_b):
        if repository.is_player_node_id(character_id):
            if character_id != current_player_node:
                raise HTTPException(status_code=403, detail="不能访问其他用户的玩家角色")
            continue
        character = repository.get_character_card_from_db(
            current_user_id,
            character_id,
            include_inactive=True,
        )
        if not character:
            raise HTTPException(status_code=404, detail=f"角色 '{character_id}' 不存在")


# =========================
# 创建关系
# =========================
@router.post("/relationships", response_model=OperationResponse)
def create_relationship(
    req: RelationshipCreateRequest,
    current_user_id: str = Depends(require_current_user_id),
):
    """创建角色关系"""
    try:
        _require_relationship_characters(
            current_user_id,
            req.character_id_a,
            req.character_id_b,
        )

        # 检查是否已存在关系
        existing = repository.get_character_relationship(
            current_user_id,
            req.character_id_a,
            req.character_id_b
        )
        
        if existing:
            raise HTTPException(status_code=409, detail="关系已存在，请使用更新接口")
        
        # 创建关系
        success = repository.save_character_relationship(
            owner_user_id=current_user_id,
            character_id_a=req.character_id_a,
            character_id_b=req.character_id_b,
            relationship_type=req.relationship_type,
            affinity=req.affinity,
            description=req.description
        )
        
        if not success:
            raise HTTPException(status_code=500, detail="创建关系失败")
        
        return OperationResponse(
            success=True,
            message=f"关系创建成功: {req.character_id_a} <-> {req.character_id_b}"
        )
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"创建关系失败: {str(e)}")


# =========================
# 获取关系详情
# =========================
@router.get("/relationships/pair/{character_id_a}/{character_id_b}", response_model=RelationshipInfo)
def get_relationship(
    character_id_a: str,
    character_id_b: str,
    current_user_id: str = Depends(require_current_user_id),
):
    """获取两个角色之间的关系"""
    relationship = repository.get_character_relationship(
        current_user_id,
        character_id_a,
        character_id_b
    )
    
    if not relationship:
        raise HTTPException(
            status_code=404,
            detail=f"未找到角色 {character_id_a} 和 {character_id_b} 之间的关系"
        )
    
    return RelationshipInfo(**relationship)


# =========================
# 更新关系
# =========================
@router.put("/relationships/pair/{character_id_a}/{character_id_b}", response_model=OperationResponse)
def update_relationship(
    character_id_a: str,
    character_id_b: str,
    req: RelationshipUpdateRequest,
    current_user_id: str = Depends(require_current_user_id),
):
    """更新角色关系"""
    try:
        _require_relationship_characters(
            current_user_id,
            character_id_a,
            character_id_b,
        )

        # 检查关系是否存在
        existing = repository.get_character_relationship(
            current_user_id,
            character_id_a,
            character_id_b
        )
        
        if not existing:
            raise HTTPException(
                status_code=404,
                detail=f"未找到角色 {character_id_a} 和 {character_id_b} 之间的关系"
            )
        
        # 更新关系
        success = repository.save_character_relationship(
            owner_user_id=current_user_id,
            character_id_a=character_id_a,
            character_id_b=character_id_b,
            relationship_type=req.relationship_type or existing["relationship_type"],
            affinity=req.affinity if req.affinity is not None else existing["affinity"],
            description=req.description if req.description is not None else existing.get("description")
        )
        
        if not success:
            raise HTTPException(status_code=500, detail="更新关系失败")
        
        return OperationResponse(
            success=True,
            message=f"关系更新成功: {character_id_a} <-> {character_id_b}"
        )
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"更新关系失败: {str(e)}")


# =========================
# 删除关系
# =========================
@router.delete("/relationships/{character_id_a}/{character_id_b}", response_model=OperationResponse)
def delete_relationship(
    character_id_a: str,
    character_id_b: str,
    current_user_id: str = Depends(require_current_user_id),
):
    """删除角色关系"""
    try:
        _require_relationship_characters(
            current_user_id,
            character_id_a,
            character_id_b,
        )
        existing = repository.get_character_relationship(
            current_user_id,
            character_id_a,
            character_id_b,
        )
        if not existing:
            raise HTTPException(
                status_code=404,
                detail=f"未找到角色 {character_id_a} 和 {character_id_b} 之间的关系",
            )

        success = repository.delete_character_relationship(
            current_user_id,
            character_id_a,
            character_id_b
        )
        
        if not success:
            raise HTTPException(status_code=500, detail="删除关系失败")
        
        return OperationResponse(
            success=True,
            message=f"关系删除成功: {character_id_a} <-> {character_id_b}"
        )
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"删除关系失败: {str(e)}")


# =========================
# 获取角色的所有关系
# =========================
@router.get("/relationships/character/{character_id}", response_model=list[RelationshipInfo])
def list_character_relationships(
    character_id: str,
    current_user_id: str = Depends(require_current_user_id),
):
    """获取指定角色的所有关系"""
    relationships = repository.list_character_relationships(current_user_id, character_id)
    return [RelationshipInfo(**rel) for rel in relationships]


# =========================
# 获取关系网络
# =========================
@router.get("/relationships/network", response_model=RelationshipNetwork)
def get_relationship_network(
    character_ids: str | None = None,
    current_user_id: str = Depends(require_current_user_id),
):
    """
    获取关系网络（用于可视化）
    
    Args:
        character_ids: 逗号分隔的角色 ID 列表，为空则返回所有关系
    """
    try:
        # 解析角色 ID
        target_ids = set()
        if character_ids:
            target_ids = set(cid.strip() for cid in character_ids.split(",") if cid.strip())
        
        # 获取所有关系
        all_relationships = []
        if target_ids:
            # 获取指定角色的关系
            for char_id in target_ids:
                rels = repository.list_character_relationships(current_user_id, char_id)
                all_relationships.extend(rels)
            
            # 去重
            seen = set()
            unique_rels = []
            for rel in all_relationships:
                rel_key = tuple(sorted([rel["character_id_a"], rel["character_id_b"]]))
                if rel_key not in seen:
                    seen.add(rel_key)
                    unique_rels.append(rel)
            all_relationships = unique_rels
        else:
            # 获取所有角色的关系
            all_relationships = repository.list_all_character_relationships(current_user_id)
        
        # 构建节点和边
        player_card = repository.get_or_create_user_character_card(current_user_id)
        if not player_card:
            raise HTTPException(status_code=404, detail="用户角色卡不存在")
        player_id = repository.player_node_id(current_user_id)
        character_cards = {
            card["character_id"]: card
            for card in repository.list_character_cards_from_db(
                current_user_id,
                only_active=False,
            )
        }
        nodes_dict = {
            player_id: RelationshipNetworkNode(
                character_id=player_id,
                node_type="player",
                name=player_card["display_name"],
                avatar_url=player_card.get("avatar_url"),
                is_active=True,
            )
        }
        edges = []

        def add_character_node(character_id: str) -> None:
            if character_id in nodes_dict:
                return
            card = character_cards.get(character_id)
            nodes_dict[character_id] = RelationshipNetworkNode(
                character_id=character_id,
                node_type="character",
                name=(
                    (card or {}).get("display_name")
                    or (card or {}).get("name")
                    or character_id
                ),
                avatar_url=(card or {}).get("avatar_url"),
                is_active=bool((card or {}).get("is_active", True)),
            )

        if not target_ids:
            for character_id in character_cards:
                add_character_node(character_id)
        
        for rel in all_relationships:
            char_a = rel["character_id_a"]
            char_b = rel["character_id_b"]
            
            if char_a != player_id:
                add_character_node(char_a)
            if char_b != player_id:
                add_character_node(char_b)
            
            # 添加边
            edges.append(RelationshipNetworkEdge(
                source=char_a,
                target=char_b,
                relationship_type=rel["relationship_type"],
                affinity=rel["affinity"],
                description=rel.get("description")
            ))
        
        return RelationshipNetwork(
            nodes=list(nodes_dict.values()),
            edges=edges
        )
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取关系网络失败: {str(e)}")


# =========================
# 批量创建关系
# =========================
@router.post("/relationships/batch", response_model=OperationResponse)
def batch_create_relationships(
    relationships: list[RelationshipCreateRequest],
    current_user_id: str = Depends(require_current_user_id),
):
    """批量创建角色关系"""
    try:
        success_count = 0
        failed_count = 0
        
        for rel in relationships:
            try:
                _require_relationship_characters(
                    current_user_id,
                    rel.character_id_a,
                    rel.character_id_b,
                )
                existing = repository.get_character_relationship(
                    current_user_id,
                    rel.character_id_a,
                    rel.character_id_b,
                )
                if existing:
                    failed_count += 1
                    continue
                success = repository.save_character_relationship(
                    owner_user_id=current_user_id,
                    character_id_a=rel.character_id_a,
                    character_id_b=rel.character_id_b,
                    relationship_type=rel.relationship_type,
                    affinity=rel.affinity,
                    description=rel.description
                )
                if success:
                    success_count += 1
                else:
                    failed_count += 1
            except Exception:
                failed_count += 1
        
        return OperationResponse(
            success=success_count > 0,
            message=f"批量创建完成: 成功 {success_count} 条，失败 {failed_count} 条"
        )
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"批量创建失败: {str(e)}")
