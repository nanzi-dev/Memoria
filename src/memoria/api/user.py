"""
用户注册、登录、资料管理 API
"""

import hashlib
import hmac
import secrets
import re
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, HTTPException, UploadFile, File, Header, Response, Cookie, Depends, Query
from pydantic import BaseModel, Field, StrictInt
from starlette.concurrency import run_in_threadpool

from memoria.api.avatar_fetcher import download_remote_image
from memoria.api.avatar_image import avatar_data_url, normalize_avatar_image
from memoria.api.upload_utils import read_upload_limited
from memoria.core.config import configs
from memoria.core import world_clock
from memoria.db import repository

router = APIRouter()

# 兼容旧测试/开发进程中的临时 token；新登录态持久化到数据库。
_tokens: dict[str, str] = {}  # token -> user_id

MAX_AVATAR_UPLOAD_SIZE = 8 * 1024 * 1024
AUTH_COOKIE_NAME = "memoria-token"
AUTH_COOKIE_MAX_AGE = 60 * 60 * 24 * 30  # 30 天
PASSWORD_HASH_ALGORITHM = "pbkdf2_sha256"
PASSWORD_HASH_ITERATIONS = 210_000

def _hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        bytes.fromhex(salt),
        PASSWORD_HASH_ITERATIONS,
    ).hex()
    return f"{PASSWORD_HASH_ALGORITHM}${PASSWORD_HASH_ITERATIONS}${salt}${digest}"


def _legacy_sha256(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


def _verify_password(password: str, stored_hash: str) -> bool:
    if stored_hash.startswith(f"{PASSWORD_HASH_ALGORITHM}$"):
        try:
            _, iterations, salt, expected = stored_hash.split("$", 3)
            digest = hashlib.pbkdf2_hmac(
                "sha256",
                password.encode("utf-8"),
                bytes.fromhex(salt),
                int(iterations),
            ).hex()
            return hmac.compare_digest(digest, expected)
        except Exception:
            return False
    return hmac.compare_digest(_legacy_sha256(password), stored_hash)


def _needs_password_rehash(stored_hash: str) -> bool:
    return not stored_hash.startswith(f"{PASSWORD_HASH_ALGORITHM}${PASSWORD_HASH_ITERATIONS}$")

def _gen_token() -> str:
    return secrets.token_hex(32)

def _gen_user_id() -> str:
    """生成 usr_<8字符> 格式的用户 ID"""
    return "usr_" + secrets.token_hex(4)


def _set_auth_cookie(response: Response, token: str) -> None:
    """写入登录态 Cookie。"""
    response.set_cookie(
        key=AUTH_COOKIE_NAME,
        value=token,
        max_age=AUTH_COOKIE_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=configs.auth_cookie_secure,
        path="/",
    )


def _store_auth_token(token: str, user_id: str) -> None:
    expires_at = (datetime.now(timezone.utc) + timedelta(seconds=AUTH_COOKIE_MAX_AGE)).isoformat()
    repository.create_auth_token(token, user_id, expires_at)


def _get_token_from_request(
    authorization: str | None = None,
    cookie_token: str | None = None,
) -> str:
    """从 Authorization header 或 HttpOnly Cookie 提取 token。"""
    if authorization and authorization.startswith("Bearer "):
        return authorization[7:]
    if cookie_token:
        return cookie_token
    raise HTTPException(401, "未提供认证信息")


def _validate_username(username: str) -> str:
    """校验用户名格式"""
    if not username or len(username) < 2 or len(username) > 20:
        raise HTTPException(400, "用户名长度需在 2-20 之间")
    if not re.match(r'^[\w\u4e00-\u9fff-]+$', username):
        raise HTTPException(400, "用户名只能包含字母、数字、中文、下划线和连字符")
    return username

def _validate_password(password: str) -> str:
    """校验密码格式：至少 8 位，含字母和数字"""
    if not password or len(password) < 8:
        raise HTTPException(400, "密码长度不能少于 8 位")
    if not re.search(r'[A-Za-z]', password):
        raise HTTPException(400, "密码必须包含至少一个字母")
    if not re.search(r'\d', password):
        raise HTTPException(400, "密码必须包含至少一个数字")
    return password

def _resize_image(data: bytes, max_dim: int = 512) -> bytes | None:
    """兼容旧调用：将图片压缩为 JPEG。"""
    try:
        normalized = normalize_avatar_image(data)
        if normalized.content_type == "image/jpeg":
            return normalized.data

        from PIL import Image
        import io

        with Image.open(io.BytesIO(data)) as image:
            image.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS)
            if image.mode != "RGB":
                image = image.convert("RGB")
            output = io.BytesIO()
            image.save(output, format="JPEG", quality=85)
            return output.getvalue()
    except (HTTPException, OSError, ValueError):
        return None


def get_current_user_id(token: str) -> str | None:
    """从 token 获取 user_id"""
    try:
        uid = repository.get_user_id_for_auth_token(token)
        if uid:
            return uid
    except Exception:
        pass
    return _tokens.get(token)


def require_current_user_id(
    authorization: str | None = Header(None),
    cookie_token: str | None = Cookie(None, alias=AUTH_COOKIE_NAME),
) -> str:
    """要求请求已登录，并返回当前 user_id。"""
    auth_token = _get_token_from_request(authorization, cookie_token)
    uid = get_current_user_id(auth_token)
    if not uid:
        raise HTTPException(401, "未登录或 token 已过期")
    return uid


def require_admin_user_id(
    user_id: str = Depends(require_current_user_id),
) -> str:
    """要求当前用户具有系统管理员权限。"""
    user = repository.get_user_by_id(user_id)
    if not user or not bool(user.get("is_admin")):
        raise HTTPException(403, "需要管理员权限")
    return user_id


# =========================
# 请求 / 响应模型
# =========================
class RegisterRequest(BaseModel):
    username: str
    password: str
    gender: Literal["male", "female", "unknown"] = "unknown"

class LoginRequest(BaseModel):
    username: str
    password: str

class UpdateProfileRequest(BaseModel):
    username: str | None = None
    gender: Literal["male", "female", "unknown"] | None = None


class UpdateSpeechSettingsRequest(BaseModel):
    tts_auto_play: bool
    stt_auto_send: bool

class SetAvatarUrlRequest(BaseModel):
    url: str


class UserCharacterCardUpdate(BaseModel):
    display_name: str | None = Field(default=None, max_length=50)
    avatar_url: str | None = Field(default=None, max_length=4_000_000)
    gender: str | None = Field(default=None, max_length=30)
    pronouns: str | None = Field(default=None, max_length=50)
    age: int | None = Field(default=None, ge=0, le=10_000)
    species: str | None = Field(default=None, max_length=80)
    occupation: str | None = Field(default=None, max_length=120)
    appearance: str | None = Field(default=None, max_length=4_000)
    personality: str | None = Field(default=None, max_length=4_000)
    background: str | None = Field(default=None, max_length=8_000)
    goals: str | None = Field(default=None, max_length=4_000)


class UserCharacterCardResponse(BaseModel):
    user_id: str
    node_id: str
    display_name: str
    avatar_url: str | None = None
    gender: str
    pronouns: str
    age: int | None = None
    species: str
    occupation: str
    appearance: str
    personality: str
    background: str
    goals: str
    created_at: str
    updated_at: str


class UserRoleSummary(BaseModel):
    node_id: str
    display_name: str
    avatar_url: str | None = None
    updated_at: str | None = None


class NextScheduledEventResponse(BaseModel):
    event_id: str
    event_name: str | None = None
    character_id: str
    next_run_at: str
    next_due_real_at: str | None = None
    missed_count: int = 0


class WorldClockResponse(BaseModel):
    world_now: str
    real_now: str
    timezone: str
    timezone_mode: str
    time_scale: int
    paused: bool
    clock_revision: int
    real_offset_seconds: int
    next_event: NextScheduledEventResponse | None = None


class UpdateWorldClockRequest(BaseModel):
    expected_revision: StrictInt
    timezone: str | None = None
    timezone_mode: str | None = None
    time_scale: StrictInt | None = None


class ClockRevisionRequest(BaseModel):
    expected_revision: StrictInt


class SetWorldClockRequest(ClockRevisionRequest):
    world_now: str


class AdvanceWorldClockRequest(ClockRevisionRequest):
    seconds: StrictInt = Field(gt=0, le=366 * 24 * 60 * 60)

class UserResponse(BaseModel):
    user_id: str
    username: str
    is_admin: bool = False
    gender: str
    avatar_url: str | None = None
    timezone: str
    timezone_mode: str
    time_scale: int
    paused: bool
    world_now: str
    real_now: str
    clock_revision: int
    real_offset_seconds: int
    next_event: NextScheduledEventResponse | None = None
    tts_auto_play: bool = False
    stt_auto_send: bool = False
    role_summary: UserRoleSummary

class EventInboxItem(BaseModel):
    id: int
    event_id: str | None = None
    character_id: str | None = None
    session_id: str | None = None
    event_type: str
    title: str | None = None
    content: str
    payload: str | None = None
    world_created_at: str | None = None
    created_at: str
    read_at: str | None = None

class AuthResponse(BaseModel):
    user: UserResponse

class OperationResponse(BaseModel):
    success: bool
    message: str


def _build_user_response(user: dict) -> UserResponse:
    clock = _build_world_clock_response(
        world_clock.get_clock_snapshot(user["user_id"])
    )
    card = repository.get_user_character_card(user["user_id"])
    role_summary = UserRoleSummary(
        node_id=repository.player_node_id(user["user_id"]),
        display_name=(card or {}).get("display_name") or user["username"],
        avatar_url=(card or {}).get("avatar_url"),
        updated_at=(card or {}).get("updated_at"),
    )
    return UserResponse(
        user_id=user["user_id"],
        username=user["username"],
        is_admin=bool(user.get("is_admin", False)),
        gender=user["gender"],
        avatar_url=user.get("avatar_url"),
        tts_auto_play=bool(user.get("tts_auto_play", False)),
        stt_auto_send=bool(user.get("stt_auto_send", False)),
        role_summary=role_summary,
        **clock.model_dump(),
    )


def _build_character_card_response(card: dict) -> UserCharacterCardResponse:
    return UserCharacterCardResponse(
        **card,
        node_id=repository.player_node_id(card["user_id"]),
    )


def _avatar_data_url(data: bytes, mime_type: str | None) -> str:
    # Declared MIME types are attacker-controlled; use the decoded format.
    del mime_type
    return avatar_data_url(data)


def _build_world_clock_response(
    snapshot: world_clock.WorldClockSnapshot,
) -> WorldClockResponse:
    next_schedule = repository.get_next_event_schedule(snapshot.player_id)
    next_event = None
    if next_schedule:
        next_event = NextScheduledEventResponse(
            event_id=next_schedule["event_id"],
            event_name=next_schedule.get("event_name"),
            character_id=next_schedule["character_id"],
            next_run_at=next_schedule["next_run_at"],
            next_due_real_at=next_schedule.get("next_due_real_at"),
            missed_count=int(next_schedule.get("missed_count") or 0),
        )
    return WorldClockResponse(**snapshot.to_api_dict(), next_event=next_event)


def _raise_clock_http_error(exc: ValueError) -> None:
    if isinstance(
        exc,
        (world_clock.ClockRevisionConflict, world_clock.ClockScheduleBusy),
    ):
        raise HTTPException(409, str(exc)) from exc
    raise HTTPException(400, str(exc)) from exc


# =========================
# 注册
# =========================
@router.post("/user/register", response_model=AuthResponse)
def register(req: RegisterRequest, response: Response):
    _validate_username(req.username)
    _validate_password(req.password)
    if repository.get_user_by_username(req.username):
        raise HTTPException(409, "用户名已存在")

    uid = _gen_user_id()
    # 确保 user_id 唯一
    while repository.get_user_by_id(uid):
        uid = _gen_user_id()

    repository.create_user(uid, req.username, _hash_password(req.password), req.gender)
    token = _gen_token()
    _store_auth_token(token, uid)
    _set_auth_cookie(response, token)
    user = repository.get_user_by_id(uid)
    return AuthResponse(user=_build_user_response(user))


# =========================
# 登录
# =========================
@router.post("/user/login", response_model=AuthResponse)
def login(req: LoginRequest, response: Response):
    user = repository.get_user_by_username(req.username)
    if not user or not _verify_password(req.password, user["password_hash"]):
        raise HTTPException(401, "用户名或密码错误")

    if _needs_password_rehash(user["password_hash"]):
        repository.update_user_password_hash(user["user_id"], _hash_password(req.password))

    token = _gen_token()
    _store_auth_token(token, user["user_id"])
    _set_auth_cookie(response, token)
    return AuthResponse(user=_build_user_response(user))


# =========================
# 退出登录
# =========================
@router.post("/user/logout", response_model=OperationResponse)
def logout(
    response: Response,
    authorization: str | None = Header(None),
    cookie_token: str | None = Cookie(None, alias=AUTH_COOKIE_NAME),
):
    try:
        auth_token = _get_token_from_request(authorization, cookie_token)
        _tokens.pop(auth_token, None)
        repository.delete_auth_token(auth_token)
    except HTTPException:
        pass
    response.delete_cookie(AUTH_COOKIE_NAME, path="/")
    return OperationResponse(success=True, message="已退出登录")


# =========================
# 获取当前用户信息
# =========================
@router.get("/user/me", response_model=UserResponse)
def get_me(
    uid: str = Depends(require_current_user_id),
):
    user = repository.get_user_by_id(uid)
    if not user:
        raise HTTPException(404, "用户不存在")
    return _build_user_response(user)


# =========================
# 更新资料
# =========================
@router.put("/user/profile", response_model=UserResponse)
def update_profile(
    req: UpdateProfileRequest,
    uid: str = Depends(require_current_user_id),
):
    if req.username:
        _validate_username(req.username)
        existing = repository.get_user_by_username(req.username)
        if existing and existing["user_id"] != uid:
            raise HTTPException(409, "用户名已被占用")
    repository.update_user_profile(uid, username=req.username, gender=req.gender)
    user = repository.get_user_by_id(uid)
    return _build_user_response(user)


@router.put("/user/speech-settings", response_model=UserResponse)
def update_speech_settings(
    req: UpdateSpeechSettingsRequest,
    user_id: str = Depends(require_current_user_id),
):
    repository.update_user_speech_settings(
        user_id,
        tts_auto_play=req.tts_auto_play,
        stt_auto_send=req.stt_auto_send,
    )
    user = repository.get_user_by_id(user_id)
    if not user:
        raise HTTPException(404, "用户不存在")
    return _build_user_response(user)


# =========================
# 用户角色卡
# =========================
@router.get("/user/character-card", response_model=UserCharacterCardResponse)
def get_character_card(
    user_id: str = Depends(require_current_user_id),
):
    card = repository.get_or_create_user_character_card(user_id)
    if not card:
        raise HTTPException(404, "用户不存在")
    return _build_character_card_response(card)


@router.put("/user/character-card", response_model=UserCharacterCardResponse)
def put_character_card(
    req: UserCharacterCardUpdate,
    user_id: str = Depends(require_current_user_id),
):
    fields = req.model_dump(exclude_unset=True)
    for key, value in list(fields.items()):
        if isinstance(value, str):
            fields[key] = value.strip()
    if "display_name" in fields and not fields["display_name"]:
        raise HTTPException(400, "角色名称不能为空")
    avatar_url = fields.get("avatar_url")
    if avatar_url and not avatar_url.startswith("data:image/"):
        raise HTTPException(400, "角色头像请通过头像上传或网络图片接口设置")
    card = repository.update_user_character_card(user_id, fields)
    if not card:
        raise HTTPException(404, "用户不存在")
    return _build_character_card_response(card)


@router.post(
    "/user/character-card/avatar/upload",
    response_model=UserCharacterCardResponse,
)
async def upload_character_card_avatar(
    file: UploadFile = File(...),
    user_id: str = Depends(require_current_user_id),
):
    contents = await read_upload_limited(
        file,
        MAX_AVATAR_UPLOAD_SIZE,
        detail="头像文件超过 8 MB 上传限制",
    )
    avatar_url = await run_in_threadpool(
        _avatar_data_url,
        contents,
        file.content_type,
    )
    card = repository.update_user_character_card(
        user_id,
        {"avatar_url": avatar_url},
    )
    if not card:
        raise HTTPException(404, "用户不存在")
    return _build_character_card_response(card)


@router.post(
    "/user/character-card/avatar/url",
    response_model=UserCharacterCardResponse,
)
def set_character_card_avatar_url(
    req: SetAvatarUrlRequest,
    user_id: str = Depends(require_current_user_id),
):
    url = req.url.strip()
    if not url:
        card = repository.update_user_character_card(
            user_id,
            {"avatar_url": None},
        )
    else:
        image = download_remote_image(url, timeout=10)
        card = repository.update_user_character_card(
            user_id,
            {"avatar_url": _avatar_data_url(image.data, image.content_type)},
        )
    if not card:
        raise HTTPException(404, "用户不存在")
    return _build_character_card_response(card)


# =========================
# 世界时钟与事件收件箱
# =========================
@router.get("/user/world-clock", response_model=WorldClockResponse)
def get_world_clock(user_id: str = Depends(require_current_user_id)):
    return _build_world_clock_response(world_clock.get_clock_snapshot(user_id))


@router.put("/user/world-clock", response_model=WorldClockResponse)
def put_world_clock(
    req: UpdateWorldClockRequest,
    user_id: str = Depends(require_current_user_id),
):
    try:
        snapshot = world_clock.update_clock(
            user_id,
            timezone_name=req.timezone,
            timezone_mode=req.timezone_mode,
            time_scale=req.time_scale,
            expected_revision=req.expected_revision,
        )
    except ValueError as exc:
        _raise_clock_http_error(exc)
    return _build_world_clock_response(snapshot)


@router.post("/user/world-clock/sync", response_model=WorldClockResponse)
def sync_world_clock(
    req: ClockRevisionRequest,
    user_id: str = Depends(require_current_user_id),
):
    try:
        snapshot = world_clock.sync_clock(
            user_id,
            expected_revision=req.expected_revision,
        )
    except ValueError as exc:
        _raise_clock_http_error(exc)
    return _build_world_clock_response(snapshot)


@router.post("/user/world-clock/set", response_model=WorldClockResponse)
def set_world_clock(
    req: SetWorldClockRequest,
    user_id: str = Depends(require_current_user_id),
):
    try:
        snapshot = world_clock.set_clock(
            user_id,
            req.world_now,
            expected_revision=req.expected_revision,
        )
    except ValueError as exc:
        _raise_clock_http_error(exc)
    return _build_world_clock_response(snapshot)


@router.post("/user/world-clock/advance", response_model=WorldClockResponse)
def advance_world_clock(
    req: AdvanceWorldClockRequest,
    user_id: str = Depends(require_current_user_id),
):
    try:
        snapshot = world_clock.advance_clock(
            user_id,
            timedelta(seconds=req.seconds),
            expected_revision=req.expected_revision,
        )
    except ValueError as exc:
        _raise_clock_http_error(exc)
    return _build_world_clock_response(snapshot)


@router.get("/user/event-inbox", response_model=list[EventInboxItem])
def get_event_inbox(
    unread_only: bool = True,
    limit: int = Query(default=50, ge=1, le=100),
    user_id: str = Depends(require_current_user_id),
):
    return repository.list_player_event_inbox(
        user_id,
        unread_only=unread_only,
        limit=limit,
    )


@router.post("/user/event-inbox/{inbox_id}/read", response_model=OperationResponse)
def read_event_inbox_item(
    inbox_id: int,
    user_id: str = Depends(require_current_user_id),
):
    if not repository.mark_player_event_read(user_id, inbox_id):
        raise HTTPException(404, "事件通知不存在")
    return OperationResponse(success=True, message="已读")


# =========================
# 头像上传
# =========================
@router.post("/user/avatar/upload", response_model=OperationResponse)
async def upload_avatar(
    file: UploadFile = File(...),
    uid: str = Depends(require_current_user_id),
):
    contents = await read_upload_limited(
        file,
        MAX_AVATAR_UPLOAD_SIZE,
        detail="头像文件超过 8 MB 上传限制",
    )
    data_url = await run_in_threadpool(
        _avatar_data_url,
        contents,
        file.content_type,
    )
    repository.update_user_profile(uid, avatar_url=data_url)
    return OperationResponse(success=True, message="头像上传成功")


@router.post("/user/avatar/url", response_model=OperationResponse)
def set_avatar_url(
    req: SetAvatarUrlRequest,
    uid: str = Depends(require_current_user_id),
):
    url = req.url.strip()
    if not url:
        repository.update_user_profile(uid, avatar_url=None)
        return OperationResponse(success=True, message="头像已清除")

    image = download_remote_image(url, timeout=10)
    repository.update_user_profile(
        uid,
        avatar_url=_avatar_data_url(image.data, image.content_type),
    )
    return OperationResponse(success=True, message="头像设置成功")
