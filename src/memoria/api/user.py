"""
用户注册、登录、资料管理 API
"""

import base64
import hashlib
import mimetypes
import secrets
import re

from fastapi import APIRouter, HTTPException, UploadFile, File, Header, Response, Cookie
from pydantic import BaseModel, Field

from memoria.db import repository

router = APIRouter()

# 简单的 token 存储（生产环境应使用 JWT）
_tokens: dict[str, str] = {}  # token -> user_id

ALLOWED_MIME_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp"}
MAX_AVATAR_SIZE = 2 * 1024 * 1024  # 2MB
AUTH_COOKIE_NAME = "memoria-token"
AUTH_COOKIE_MAX_AGE = 60 * 60 * 24 * 30  # 30 天

def _hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()

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
        secure=False,
        path="/",
    )


def _get_token_from_request(
    authorization: str | None = None,
    token: str | None = None,
    cookie_token: str | None = None,
) -> str:
    """从 Authorization header、query param 或 Cookie 提取 token"""
    if authorization and authorization.startswith("Bearer "):
        return authorization[7:]
    if token:
        return token
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
    """压缩图片到指定尺寸"""
    try:
        from PIL import Image
        import io
        img = Image.open(io.BytesIO(data))
        img.thumbnail((max_dim, max_dim), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85)
        return buf.getvalue()
    except Exception:
        return None

def get_current_user_id(token: str) -> str | None:
    """从 token 获取 user_id"""
    return _tokens.get(token)


def require_current_user_id(
    token: str | None = None,
    authorization: str | None = Header(None),
    cookie_token: str | None = Cookie(None, alias=AUTH_COOKIE_NAME),
) -> str:
    """要求请求已登录，并返回当前 user_id。"""
    auth_token = _get_token_from_request(authorization, token, cookie_token)
    uid = get_current_user_id(auth_token)
    if not uid:
        raise HTTPException(401, "未登录或 token 已过期")
    return uid


# =========================
# 请求 / 响应模型
# =========================
class RegisterRequest(BaseModel):
    username: str
    password: str
    gender: str = "unknown"

class LoginRequest(BaseModel):
    username: str
    password: str

class UpdateProfileRequest(BaseModel):
    username: str | None = None
    gender: str | None = None

class SetAvatarUrlRequest(BaseModel):
    url: str

class UserResponse(BaseModel):
    user_id: str
    username: str
    gender: str
    avatar_url: str | None = None

class AuthResponse(BaseModel):
    token: str
    user: UserResponse

class OperationResponse(BaseModel):
    success: bool
    message: str


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
    _tokens[token] = uid
    _set_auth_cookie(response, token)
    user = repository.get_user_by_id(uid)
    return AuthResponse(token=token, user=UserResponse(
        user_id=uid, username=req.username, gender=req.gender
    ))


# =========================
# 登录
# =========================
@router.post("/user/login", response_model=AuthResponse)
def login(req: LoginRequest, response: Response):
    user = repository.get_user_by_username(req.username)
    if not user or user["password_hash"] != _hash_password(req.password):
        raise HTTPException(401, "用户名或密码错误")

    token = _gen_token()
    _tokens[token] = user["user_id"]
    _set_auth_cookie(response, token)
    return AuthResponse(token=token, user=UserResponse(
        user_id=user["user_id"],
        username=user["username"],
        gender=user["gender"],
        avatar_url=user.get("avatar_url"),
    ))


# =========================
# 退出登录
# =========================
@router.post("/user/logout", response_model=OperationResponse)
def logout(
    response: Response,
    token: str | None = None,
    authorization: str | None = Header(None),
    cookie_token: str | None = Cookie(None, alias=AUTH_COOKIE_NAME),
):
    try:
        auth_token = _get_token_from_request(authorization, token, cookie_token)
        _tokens.pop(auth_token, None)
    except HTTPException:
        pass
    response.delete_cookie(AUTH_COOKIE_NAME, path="/")
    return OperationResponse(success=True, message="已退出登录")


# =========================
# 获取当前用户信息
# =========================
@router.get("/user/me", response_model=UserResponse)
def get_me(
    token: str | None = None,
    authorization: str | None = Header(None),
    cookie_token: str | None = Cookie(None, alias=AUTH_COOKIE_NAME),
):
    token = _get_token_from_request(authorization, token, cookie_token)
    uid = get_current_user_id(token)
    if not uid:
        raise HTTPException(401, "未登录或 token 已过期")
    user = repository.get_user_by_id(uid)
    if not user:
        raise HTTPException(404, "用户不存在")
    return UserResponse(
        user_id=user["user_id"],
        username=user["username"],
        gender=user["gender"],
        avatar_url=user.get("avatar_url"),
    )


# =========================
# 更新资料
# =========================
@router.put("/user/profile", response_model=UserResponse)
def update_profile(
    req: UpdateProfileRequest,
    token: str | None = None,
    authorization: str | None = Header(None),
    cookie_token: str | None = Cookie(None, alias=AUTH_COOKIE_NAME),
):
    token = _get_token_from_request(authorization, token, cookie_token)
    uid = get_current_user_id(token)
    if not uid:
        raise HTTPException(401, "未登录")
    if req.username:
        _validate_username(req.username)
        existing = repository.get_user_by_username(req.username)
        if existing and existing["user_id"] != uid:
            raise HTTPException(409, "用户名已被占用")
    if req.gender and req.gender not in ("male", "female", "unknown"):
        raise HTTPException(400, "性别只能是 male/female/unknown")
    repository.update_user_profile(uid, username=req.username, gender=req.gender)
    user = repository.get_user_by_id(uid)
    return UserResponse(
        user_id=user["user_id"],
        username=user["username"],
        gender=user["gender"],
        avatar_url=user.get("avatar_url"),
    )


# =========================
# 头像上传
# =========================
@router.post("/user/avatar/upload", response_model=OperationResponse)
async def upload_avatar(
    token: str | None = None,
    file: UploadFile = File(...),
    authorization: str | None = Header(None),
    cookie_token: str | None = Cookie(None, alias=AUTH_COOKIE_NAME),
):
    token = _get_token_from_request(authorization, token, cookie_token)
    uid = get_current_user_id(token)
    if not uid:
        raise HTTPException(401, "未登录")

    contents = await file.read()
    mime_type = file.content_type or mimetypes.guess_type(file.filename)[0]
    if mime_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(400, f"不支持的图片格式: {mime_type}")

    data = contents
    if len(data) > MAX_AVATAR_SIZE:
        data = _resize_image(data)
        if data is None:
            raise HTTPException(400, "图片过大且压缩失败")
        mime_type = "image/jpeg"

    b64 = base64.b64encode(data).decode("ascii")
    data_url = f"data:{mime_type};base64,{b64}"
    repository.update_user_profile(uid, avatar_url=data_url)
    return OperationResponse(success=True, message="头像上传成功")


@router.post("/user/avatar/url", response_model=OperationResponse)
def set_avatar_url(
    req: SetAvatarUrlRequest,
    token: str | None = None,
    authorization: str | None = Header(None),
    cookie_token: str | None = Cookie(None, alias=AUTH_COOKIE_NAME),
):
    token = _get_token_from_request(authorization, token, cookie_token)
    uid = get_current_user_id(token)
    if not uid:
        raise HTTPException(401, "未登录")

    url = req.url.strip()
    if not url:
        repository.update_user_profile(uid, avatar_url=None)
        return OperationResponse(success=True, message="头像已清除")

    import requests as _requests
    try:
        resp = _requests.get(url, timeout=10, headers={"User-Agent": "Memoria/1.0"})
        resp.raise_for_status()
    except Exception as e:
        raise HTTPException(400, f"无法获取图片: {e}")

    ct = resp.headers.get("Content-Type", "image/png")
    if not ct.startswith("image/"):
        raise HTTPException(400, f"URL 返回的不是图片: {ct}")

    data = resp.content
    if len(data) > MAX_AVATAR_SIZE:
        data = _resize_image(data)
        if data is None:
            raise HTTPException(400, "图片过大且压缩失败")
        ct = "image/jpeg"

    b64 = base64.b64encode(data).decode("ascii")
    data_url = f"data:{ct};base64,{b64}"
    repository.update_user_profile(uid, avatar_url=data_url)
    return OperationResponse(success=True, message="头像设置成功")
