"""Validation and normalization for avatar image bytes."""

from __future__ import annotations

import base64
import io
from dataclasses import dataclass

from fastapi import HTTPException
from PIL import Image, UnidentifiedImageError


MAX_AVATAR_SIZE = 2 * 1024 * 1024
MAX_AVATAR_DIMENSION = 512
MAX_AVATAR_PIXELS = 16_000_000

_FORMAT_TO_MIME = {
    "PNG": "image/png",
    "JPEG": "image/jpeg",
    "GIF": "image/gif",
    "WEBP": "image/webp",
}


@dataclass(frozen=True)
class NormalizedAvatar:
    data: bytes
    content_type: str

    def to_data_url(self) -> str:
        encoded = base64.b64encode(self.data).decode("ascii")
        return f"data:{self.content_type};base64,{encoded}"


def _inspect_image(data: bytes) -> tuple[str, tuple[int, int]]:
    try:
        with Image.open(io.BytesIO(data)) as image:
            image_format = (image.format or "").upper()
            if image_format not in _FORMAT_TO_MIME:
                raise HTTPException(status_code=400, detail="不支持的图片格式")

            width, height = image.size
            if width <= 0 or height <= 0:
                raise HTTPException(status_code=400, detail="无效的图片尺寸")
            if width * height > MAX_AVATAR_PIXELS:
                raise HTTPException(
                    status_code=400,
                    detail=f"图片像素超过 {MAX_AVATAR_PIXELS} 上限",
                )

            image.verify()
            return image_format, (width, height)
    except HTTPException:
        raise
    except Image.DecompressionBombError:
        raise HTTPException(
            status_code=400,
            detail=f"图片像素超过 {MAX_AVATAR_PIXELS} 上限",
        )
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError):
        raise HTTPException(status_code=400, detail="无效的图片文件")


def _resize_to_jpeg(data: bytes) -> bytes:
    try:
        with Image.open(io.BytesIO(data)) as image:
            image.thumbnail(
                (MAX_AVATAR_DIMENSION, MAX_AVATAR_DIMENSION),
                Image.Resampling.LANCZOS,
            )
            if image.mode != "RGB":
                image = image.convert("RGB")

            for quality in (85, 70, 50):
                output = io.BytesIO()
                image.save(output, format="JPEG", quality=quality, optimize=True)
                resized = output.getvalue()
                if len(resized) <= MAX_AVATAR_SIZE:
                    return resized
    except (
        Image.DecompressionBombError,
        UnidentifiedImageError,
        OSError,
        SyntaxError,
        ValueError,
    ):
        pass

    raise HTTPException(status_code=400, detail="图片压缩失败")


def normalize_avatar_image(data: bytes) -> NormalizedAvatar:
    image_format, (width, height) = _inspect_image(data)
    if (
        len(data) <= MAX_AVATAR_SIZE
        and width <= MAX_AVATAR_DIMENSION
        and height <= MAX_AVATAR_DIMENSION
    ):
        return NormalizedAvatar(data=data, content_type=_FORMAT_TO_MIME[image_format])

    return NormalizedAvatar(
        data=_resize_to_jpeg(data),
        content_type="image/jpeg",
    )


def avatar_data_url(data: bytes) -> str:
    return normalize_avatar_image(data).to_data_url()
