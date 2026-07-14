"""
角色卡管理 API 路由

用途：
1. 角色卡的 CRUD 操作（创建、读取、更新、删除）
2. 从文件导入角色卡到数据库
3. 角色卡的启用/禁用管理
"""

import base64
import json
import logging
import mimetypes
import threading
from pathlib import Path
from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from memoria.api.avatar_fetcher import download_remote_image
from memoria.api.upload_utils import read_upload_limited
from memoria.api.user import require_current_user_id
from memoria.core import character_loader
from memoria.core.character_schema import CharacterCard
from memoria.db import repository

logger = logging.getLogger(__name__)
router = APIRouter(dependencies=[Depends(require_current_user_id)])


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
    avatar_url: str | None = None
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
    avatar_url: str | None = None
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
def list_characters_admin(
    only_active: bool = True,
    current_user_id: str = Depends(require_current_user_id),
):
    """
    获取所有角色卡列表（管理后台）
    
    Args:
        only_active: 是否仅返回启用的角色卡
    """
    try:
        cards = repository.list_character_cards_from_db(current_user_id, only_active=only_active)
        return [CharacterCardListItem(**card) for card in cards]
    except Exception as e:
        logger.error(f"获取角色卡列表失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取角色卡列表失败: {str(e)}")


# =========================
# 获取角色卡详情
# =========================
@router.get("/admin/characters/{character_id}", response_model=CharacterCardDetail)
def get_character_detail(
    character_id: str,
    current_user_id: str = Depends(require_current_user_id),
):
    """
    获取指定角色卡的完整数据
    
    Args:
        character_id: 角色 ID
    """
    try:
        db_card = repository.get_character_card_from_db(current_user_id, character_id, include_inactive=True)
        
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
            avatar_url=db_card.get("avatar_url"),
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
def create_character(
    req: CharacterCardCreateRequest,
    current_user_id: str = Depends(require_current_user_id),
):
    """
    创建新角色卡
    
    Args:
        req: 包含完整角色卡数据的请求
    """
    try:
        # 使用 Pydantic 验证数据格式
        card = CharacterCard.model_validate(req.character_data)
        
        # 检查角色 ID 是否已存在
        existing = repository.get_character_card_from_db(current_user_id, card.character_id)
        if existing:
            raise HTTPException(
                status_code=400, 
                detail=f"角色卡 '{card.character_id}' 已存在，请使用更新接口"
            )
        
        # 保存到数据库
        card_json = json.dumps(req.character_data, ensure_ascii=False, indent=2)
        # 先保存原始 URL，头像异步下载
        success = repository.save_character_card_to_db(
            owner_user_id=current_user_id,
            character_id=card.character_id,
            card_data_json=card_json,
            version=card.version,
            name=card.meta.name,
            display_name=card.meta.display_name,
            source="db",
            avatar_url=card.avatar_url
        )
        _process_avatar_async(current_user_id, card.character_id, card.avatar_url)
        
        if not success:
            raise HTTPException(status_code=500, detail="保存角色卡到数据库失败")
        
        # 清除缓存
        character_loader.reload_character_card(card.character_id, current_user_id)
        
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
def update_character(
    character_id: str,
    req: CharacterCardUpdateRequest,
    current_user_id: str = Depends(require_current_user_id),
):
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
        existing = repository.get_character_card_from_db(current_user_id, character_id)
        if not existing:
            raise HTTPException(
                status_code=404,
                detail=f"角色卡 '{character_id}' 不存在，请使用创建接口"
            )
        
        # 更新到数据库
        card_json = json.dumps(req.character_data, ensure_ascii=False, indent=2)
        # 先保存原始 URL，头像异步下载
        success = repository.save_character_card_to_db(
            owner_user_id=current_user_id,
            character_id=card.character_id,
            card_data_json=card_json,
            version=card.version,
            name=card.meta.name,
            display_name=card.meta.display_name,
            source=existing.get("source", "db"),
            avatar_url=card.avatar_url
        )
        _process_avatar_async(current_user_id, card.character_id, card.avatar_url)
        
        if not success:
            raise HTTPException(status_code=500, detail="更新角色卡到数据库失败")
        
        # 清除缓存
        character_loader.reload_character_card(character_id, current_user_id)
        
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
def delete_character(
    character_id: str,
    permanent: bool = False,
    current_user_id: str = Depends(require_current_user_id),
):
    """
    删除角色卡
    
    Args:
        character_id: 角色 ID
        permanent: 是否永久删除（默认为软删除）
    """
    try:
        # 检查是否存在（包括已禁用的）
        existing = repository.get_character_card_from_db(current_user_id, character_id, include_inactive=True)
        if not existing:
            raise HTTPException(status_code=404, detail=f"角色卡 '{character_id}' 不存在")
        
        # 永久删除时由仓储层在同一事务中清理角色关系；软禁用保留关系。
        success = repository.delete_character_card_from_db(
            owner_user_id=current_user_id,
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
def activate_character(
    character_id: str,
    current_user_id: str = Depends(require_current_user_id),
):
    """
    激活已禁用的角色卡
    
    Args:
        character_id: 角色 ID
    """
    try:
        success = repository.activate_character_card(current_user_id, character_id)
        
        if not success:
            raise HTTPException(status_code=500, detail="激活角色卡失败")
        
        # 清除缓存
        character_loader.reload_character_card(character_id, current_user_id)
        
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
def import_character_from_file(
    req: ImportFromFileRequest,
    current_user_id: str = Depends(require_current_user_id),
):
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
        raw_data = character_loader.normalize_character_data(json.loads(raw_text))
        card = CharacterCard.model_validate(raw_data)
        
        # 保存到数据库
        card_json = json.dumps(raw_data, ensure_ascii=False, indent=2)
        success = repository.save_character_card_to_db(
            owner_user_id=current_user_id,
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
        character_loader.reload_character_card(card.character_id, current_user_id)
        
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

# =========================
# 头像管理
# =========================
MAX_AVATAR_SIZE = 2 * 1024 * 1024  # 2MB
MAX_AVATAR_UPLOAD_SIZE = 8 * 1024 * 1024  # 输入上限；较大图片再压缩到 2MB
MAX_AVATAR_DIMENSION = 512  # 最大宽/高，超出等比缩放
ALLOWED_MIME_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp"}

AVATAR_DOWNLOAD_TIMEOUT = 5  # seconds — shorter so saves don't stall

def _resize_image(data: bytes, max_dim: int) -> bytes | None:
    """用 PIL 等比压缩图片到 max_dim 以内，返回 JPEG bytes"""
    try:
        from PIL import Image
        import io
        img = Image.open(io.BytesIO(data))
        w, h = img.size
        ratio = min(1.0, max_dim / max(w, h))
        new_size = (int(w * ratio), int(h * ratio))
        if ratio < 1.0:
            img = img.resize(new_size, Image.LANCZOS)
        # 统一转 JPEG 以压缩体积
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=80, optimize=True)
        result = buf.getvalue()
        if len(result) > MAX_AVATAR_SIZE:
            # 还是太大，降到 quality=50 再试
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=50, optimize=True)
            result = buf.getvalue()
        if len(result) > MAX_AVATAR_SIZE:
            logger.warning(f"压缩后仍超过 2MB: {len(result)}")
            return None
        return result
    except Exception as e:
        logger.warning(f"PIL 压缩图片失败: {e}")
        return None

def _download_avatar_sync(avatar_url: str) -> str | None:
    """尝试下载远程头像 URL 并返回 base64 data URL，失败返回 None"""
    if not avatar_url or avatar_url.startswith("data:"):
        return None
    try:
        image = download_remote_image(avatar_url, timeout=AVATAR_DOWNLOAD_TIMEOUT)
        data = image.data
        content_type = image.content_type
        # 超过尺寸限制时用 PIL 等比压缩
        if len(data) > MAX_AVATAR_SIZE:
            data = _resize_image(data, MAX_AVATAR_DIMENSION)
            if data is None:
                logger.warning("图片过大且压缩失败")
                return None
            content_type = "image/jpeg"
        return f"data:{content_type};base64,{base64.b64encode(data).decode('ascii')}"
    except Exception as e:
        logger.warning(f"下载头像 URL 失败，保留原始 URL: {e}")
        return None

def _process_avatar_url(avatar_url: str | None) -> str | None:
    """同步下载头像 URL（用于 GET 详情等需要实时返回的场景）"""
    if not avatar_url or avatar_url.startswith("data:"):
        return avatar_url
    if avatar_url.startswith("http://") or avatar_url.startswith("https://"):
        downloaded = _download_avatar_sync(avatar_url)
        if downloaded is not None:
            return downloaded
        return avatar_url
    return avatar_url

def _process_avatar_async(owner_user_id: str, character_id: str, avatar_url: str | None):
    """后台线程下载头像并更新数据库，不阻塞当前请求"""
    if not avatar_url or avatar_url.startswith("data:"):
        return
    if avatar_url.startswith("http://") or avatar_url.startswith("https://"):
        def _bg_download():
            downloaded = _download_avatar_sync(avatar_url)
            if downloaded is not None:
                repository.update_character_avatar(owner_user_id, character_id, downloaded)
        threading.Thread(target=_bg_download, daemon=True).start()



class AvatarUrlRequest(BaseModel):
    """通过 URL 设置头像"""
    url: str = Field(..., description="头像图片的 URL 地址")


@router.get("/admin/characters/{character_id}/avatar", response_model=dict)
def get_character_avatar(
    character_id: str,
    current_user_id: str = Depends(require_current_user_id),
):
    """
    获取角色头像
    
    Returns:
        dict: {"avatar_url": "..."} — base64 data URL 或网络 URL，无头像时 avatar_url 为 None
    """
    try:
        db_card = repository.get_character_card_from_db(current_user_id, character_id, include_inactive=True)
        if not db_card:
            raise HTTPException(status_code=404, detail=f"角色卡 '{character_id}' 不存在")
        
        return {"character_id": character_id, "avatar_url": db_card.get("avatar_url")}
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取头像失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取头像失败: {str(e)}")


@router.post("/admin/characters/{character_id}/avatar/upload", response_model=OperationResponse)
async def upload_character_avatar(
    character_id: str,
    file: UploadFile = File(...),
    current_user_id: str = Depends(require_current_user_id),
):
    """
    从本地文件上传头像（转换为 base64 data URL 存入数据库）
    
    - 支持 PNG / JPEG / GIF / WebP
    - 最大 2MB
    """
    try:
        # 检查角色是否存在
        db_card = repository.get_character_card_from_db(current_user_id, character_id, include_inactive=True)
        if not db_card:
            raise HTTPException(status_code=404, detail=f"角色卡 '{character_id}' 不存在")
        
        contents = await read_upload_limited(
            file,
            MAX_AVATAR_UPLOAD_SIZE,
            detail="头像文件超过 8 MB 上传限制",
        )
        
        # 校验 MIME 类型
        mime_type = file.content_type or mimetypes.guess_type(file.filename)[0]
        if mime_type not in ALLOWED_MIME_TYPES:
            raise HTTPException(status_code=400,
                detail=f"不支持的图片格式: {mime_type}，支持: {', '.join(sorted(ALLOWED_MIME_TYPES))}")
        
        # 超过 2MB 自动压缩到 512px
        data = contents
        if len(data) > MAX_AVATAR_SIZE:
            data = _resize_image(data, MAX_AVATAR_DIMENSION)
            if data is None:
                raise HTTPException(status_code=400,
                    detail=f"文件过大且压缩失败，最大允许 {MAX_AVATAR_SIZE // (1024*1024)} MB")
            mime_type = "image/jpeg"  # 压缩后都是 JPEG
        
        # 转换为 base64 data URL
        b64 = base64.b64encode(data).decode("ascii")
        data_url = f"data:{mime_type};base64,{b64}"
        
        # 更新数据库
        repository.update_character_avatar(current_user_id, character_id, data_url)
        
        logger.info(f"头像已上传: character_id={character_id}, mime={mime_type}, size={len(data)}")
        
        return OperationResponse(
            success=True,
            message=f"头像上传成功 ({len(data)} bytes)",
            character_id=character_id
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"头像上传失败: {e}")
        raise HTTPException(status_code=500, detail=f"头像上传失败: {str(e)}")


@router.post("/admin/characters/{character_id}/avatar/url", response_model=OperationResponse)
def set_character_avatar_url(
    character_id: str,
    req: AvatarUrlRequest,
    current_user_id: str = Depends(require_current_user_id),
):
    """
    通过网络 URL 设置头像 — 服务端下载并转为 data URL 存储，避免前端 CORS 问题
    """
    try:
        db_card = repository.get_character_card_from_db(current_user_id, character_id, include_inactive=True)
        if not db_card:
            raise HTTPException(status_code=404, detail=f"角色卡 '{character_id}' 不存在")
        
        url = req.url.strip()
        if not url:
            repository.update_character_avatar(current_user_id, character_id, None)
            return OperationResponse(
                success=True, message="头像已清除", character_id=character_id
            )
        
        image = download_remote_image(url, timeout=10)
        data = image.data
        content_type = image.content_type
        if len(data) > MAX_AVATAR_SIZE:
            data = _resize_image(data, MAX_AVATAR_DIMENSION)
            if data is None:
                raise HTTPException(status_code=400,
                    detail=f"图片过大且压缩失败，最大允许 {MAX_AVATAR_SIZE // (1024*1024)} MB")
            content_type = "image/jpeg"
        
        b64 = base64.b64encode(data).decode("ascii")
        data_url = f"data:{content_type};base64,{b64}"
        
        repository.update_character_avatar(current_user_id, character_id, data_url)
        logger.info(f"头像 URL 已下载并存储: character_id={character_id}, size={len(data)}")
        
        return OperationResponse(
            success=True, message="头像已下载并存储", character_id=character_id
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"设置头像 URL 失败: {e}")
        raise HTTPException(status_code=500, detail=f"设置头像 URL 失败: {str(e)}")
