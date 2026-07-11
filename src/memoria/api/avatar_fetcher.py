"""
Shared remote avatar downloader with SSRF guardrails.
"""

from __future__ import annotations

import base64
import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

import requests
from fastapi import HTTPException


ALLOWED_IMAGE_MIME_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp"}
MAX_REMOTE_IMAGE_BYTES = 8 * 1024 * 1024
MAX_REDIRECTS = 3
USER_AGENT = "Memoria/1.0"


@dataclass(frozen=True)
class DownloadedImage:
    data: bytes
    content_type: str

    def to_data_url(self) -> str:
        b64 = base64.b64encode(self.data).decode("ascii")
        return f"data:{self.content_type};base64,{b64}"


def _is_blocked_ip(raw_ip: str) -> bool:
    try:
        ip = ipaddress.ip_address(raw_ip)
    except ValueError:
        return True
    return any((
        ip.is_private,
        ip.is_loopback,
        ip.is_link_local,
        ip.is_multicast,
        ip.is_reserved,
        ip.is_unspecified,
    ))


def _validate_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise HTTPException(status_code=400, detail="仅支持 http/https 图片 URL")
    if not parsed.hostname:
        raise HTTPException(status_code=400, detail="图片 URL 缺少主机名")

    try:
        resolved = socket.getaddrinfo(parsed.hostname, parsed.port, type=socket.SOCK_STREAM)
    except socket.gaierror:
        raise HTTPException(status_code=400, detail="图片 URL 主机无法解析")

    for item in resolved:
        ip = item[4][0]
        if _is_blocked_ip(ip):
            raise HTTPException(status_code=400, detail="不允许访问内网或保留地址")

    return url


def download_remote_image(url: str, timeout: float = 5.0) -> DownloadedImage:
    current_url = _validate_url(url.strip())

    for _ in range(MAX_REDIRECTS + 1):
        try:
            response = requests.get(
                current_url,
                timeout=timeout,
                headers={"User-Agent": USER_AGENT},
                allow_redirects=False,
                stream=True,
            )
        except requests.RequestException as exc:
            raise HTTPException(status_code=400, detail=f"无法获取图片: {exc}")

        if response.is_redirect:
            location = response.headers.get("Location")
            if not location:
                raise HTTPException(status_code=400, detail="图片 URL 重定向缺少 Location")
            current_url = _validate_url(urljoin(current_url, location))
            response.close()
            continue

        try:
            response.raise_for_status()
        except requests.RequestException as exc:
            raise HTTPException(status_code=400, detail=f"无法获取图片: {exc}")

        content_type = (response.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if content_type not in ALLOWED_IMAGE_MIME_TYPES:
            raise HTTPException(status_code=400, detail=f"URL 返回的不是支持的图片: {content_type or 'unknown'}")

        content_length = response.headers.get("Content-Length")
        if content_length:
            try:
                if int(content_length) > MAX_REMOTE_IMAGE_BYTES:
                    raise HTTPException(status_code=400, detail="图片文件过大")
            except ValueError:
                pass

        chunks: list[bytes] = []
        total = 0
        for chunk in response.iter_content(chunk_size=64 * 1024):
            if not chunk:
                continue
            total += len(chunk)
            if total > MAX_REMOTE_IMAGE_BYTES:
                response.close()
                raise HTTPException(status_code=400, detail="图片文件过大")
            chunks.append(chunk)

        return DownloadedImage(data=b"".join(chunks), content_type=content_type)

    raise HTTPException(status_code=400, detail="图片 URL 重定向次数过多")
