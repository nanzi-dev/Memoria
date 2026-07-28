"""
Shared remote avatar downloader with SSRF guardrails.
"""

from __future__ import annotations

import base64
import ipaddress
import socket
import threading
import time
from dataclasses import dataclass
from urllib.parse import SplitResult, urljoin, urlsplit, urlunsplit

import requests
from fastapi import HTTPException
from requests.adapters import HTTPAdapter


ALLOWED_IMAGE_MIME_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp"}
MAX_REMOTE_IMAGE_BYTES = 8 * 1024 * 1024
MAX_REDIRECTS = 3
MAX_REMOTE_DOWNLOAD_SECONDS = 20.0
MAX_CONCURRENT_REMOTE_DOWNLOADS = 8
REMOTE_IMAGE_CHUNK_BYTES = 4 * 1024
USER_AGENT = "Memoria/1.0"
PROXY_FAKE_IP_NETWORKS = (ipaddress.ip_network("198.18.0.0/15"),)
DOH_ENDPOINTS = (
    ("https://1.1.1.1/dns-query", "cloudflare-dns.com"),
    ("https://8.8.8.8/resolve", "dns.google"),
)
_DOWNLOAD_SLOTS = threading.BoundedSemaphore(MAX_CONCURRENT_REMOTE_DOWNLOADS)


@dataclass(frozen=True)
class DownloadedImage:
    data: bytes
    content_type: str

    def to_data_url(self) -> str:
        b64 = base64.b64encode(self.data).decode("ascii")
        return f"data:{self.content_type};base64,{b64}"


@dataclass(frozen=True)
class _ValidatedTarget:
    url: str
    request_url: str
    host_header: str
    hostname: str
    peer_ip: str


class _PinnedHTTPSAdapter(HTTPAdapter):
    def __init__(self, hostname: str) -> None:
        self._hostname = hostname
        super().__init__()

    def init_poolmanager(self, *args, **kwargs):
        kwargs["server_hostname"] = self._hostname
        kwargs["assert_hostname"] = self._hostname
        return super().init_poolmanager(*args, **kwargs)


def _is_blocked_ip(raw_ip: str) -> bool:
    try:
        ip = ipaddress.ip_address(raw_ip)
    except ValueError:
        return True
    return not ip.is_global


def _is_proxy_fake_ip(raw_ip: str) -> bool:
    try:
        ip = ipaddress.ip_address(raw_ip)
    except ValueError:
        return False
    return any(ip in network for network in PROXY_FAKE_IP_NETWORKS)


def _parse_url(url: str) -> tuple[SplitResult, str, int]:
    if any(ord(char) < 32 for char in url) or "\\" in url:
        raise HTTPException(status_code=400, detail="图片 URL 格式无效")

    try:
        parsed = urlsplit(url)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError:
        raise HTTPException(status_code=400, detail="图片 URL 格式无效")

    if parsed.scheme not in {"http", "https"}:
        raise HTTPException(status_code=400, detail="仅支持 http/https 图片 URL")
    if not hostname:
        raise HTTPException(status_code=400, detail="图片 URL 缺少主机名")
    if parsed.username is not None or parsed.password is not None:
        raise HTTPException(status_code=400, detail="图片 URL 不允许包含用户凭据")

    return parsed, hostname, port or (443 if parsed.scheme == "https" else 80)


def _canonical_hostname(hostname: str) -> tuple[str, str | None]:
    candidate = hostname.rstrip(".")
    try:
        return str(ipaddress.ip_address(candidate)), str(ipaddress.ip_address(candidate))
    except ValueError:
        pass

    # getaddrinfo accepts legacy numeric forms such as 2130706433 and 127.1.
    try:
        socket.inet_aton(candidate)
    except OSError:
        pass
    else:
        raise HTTPException(status_code=400, detail="图片 URL 主机名格式无效")

    try:
        ascii_hostname = candidate.encode("idna").decode("ascii").lower()
    except UnicodeError:
        raise HTTPException(status_code=400, detail="图片 URL 主机名格式无效")

    labels = ascii_hostname.split(".")
    if (
        not ascii_hostname
        or len(ascii_hostname) > 253
        or any(
            not label
            or len(label) > 63
            or label.startswith("-")
            or label.endswith("-")
            or not all(char.isalnum() or char == "-" for char in label)
            for label in labels
        )
    ):
        raise HTTPException(status_code=400, detail="图片 URL 主机名格式无效")
    return ascii_hostname, None


def _remaining_seconds(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise HTTPException(status_code=400, detail="图片下载超时")
    return remaining


def _query_doh(hostname: str, record_type: str, deadline: float) -> list[str]:
    last_error: Exception | None = None
    for endpoint, host_header in DOH_ENDPOINTS:
        remaining = _remaining_seconds(deadline)
        phase_timeout = max(0.1, min(3.0, remaining / 2))
        session = requests.Session()
        session.trust_env = False
        try:
            session.mount(
                endpoint.rsplit("/", 1)[0] + "/",
                _PinnedHTTPSAdapter(host_header),
            )
            response = session.get(
                endpoint,
                params={"name": hostname, "type": record_type},
                headers={"Accept": "application/dns-json", "Host": host_header},
                allow_redirects=False,
                timeout=(phase_timeout, phase_timeout),
            )
            try:
                response.raise_for_status()
                payload = response.json()
            finally:
                response.close()

            if payload.get("Status") != 0:
                raise ValueError("DNS query failed")
            answer_type = 1 if record_type == "A" else 28
            addresses = []
            for answer in payload.get("Answer") or []:
                if answer.get("type") != answer_type:
                    continue
                address = ipaddress.ip_address(str(answer.get("data", "")))
                if address.version == (4 if record_type == "A" else 6):
                    addresses.append(str(address))
            return addresses
        except (requests.RequestException, ValueError, TypeError, AttributeError) as exc:
            last_error = exc
        finally:
            session.close()

    raise HTTPException(status_code=400, detail="无法安全解析图片 URL 主机") from last_error


def _resolve_public_dns(hostname: str, deadline: float) -> list[str]:
    addresses = _query_doh(hostname, "A", deadline)
    if not addresses:
        addresses = _query_doh(hostname, "AAAA", deadline)
    if not addresses or any(_is_blocked_ip(address) for address in addresses):
        raise HTTPException(status_code=400, detail="不允许访问内网或保留地址")
    return list(dict.fromkeys(addresses))


def _resolved_addresses(hostname: str, port: int, deadline: float) -> list[str]:
    try:
        resolved = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
    except socket.gaierror:
        raise HTTPException(status_code=400, detail="图片 URL 主机无法解析")

    addresses = list(dict.fromkeys(str(item[4][0]) for item in resolved))
    if not addresses:
        raise HTTPException(status_code=400, detail="图片 URL 主机无法解析")
    if any(_is_proxy_fake_ip(address) for address in addresses):
        return _resolve_public_dns(hostname, deadline)
    if any(_is_blocked_ip(address) for address in addresses):
        raise HTTPException(status_code=400, detail="不允许访问内网或保留地址")
    return addresses


def _host_with_optional_port(hostname: str, port: int, scheme: str) -> str:
    host = f"[{hostname}]" if ":" in hostname else hostname
    default_port = 443 if scheme == "https" else 80
    return host if port == default_port else f"{host}:{port}"


def _validate_url(
    url: str,
    deadline: float | None = None,
) -> _ValidatedTarget:
    if deadline is None:
        deadline = time.monotonic() + MAX_REMOTE_DOWNLOAD_SECONDS
    parsed, raw_hostname, port = _parse_url(url)
    hostname, literal_ip = _canonical_hostname(raw_hostname)

    if literal_ip is not None:
        if _is_blocked_ip(literal_ip):
            raise HTTPException(status_code=400, detail="不允许访问内网或保留地址")
        addresses = [literal_ip]
    else:
        addresses = _resolved_addresses(hostname, port, deadline)

    peer_ip = addresses[0]
    pinned_host = _host_with_optional_port(peer_ip, port, parsed.scheme)
    host_header = _host_with_optional_port(hostname, port, parsed.scheme)
    request_url = urlunsplit((
        parsed.scheme,
        pinned_host,
        parsed.path or "/",
        parsed.query,
        "",
    ))
    canonical_url = urlunsplit((
        parsed.scheme,
        host_header,
        parsed.path or "/",
        parsed.query,
        "",
    ))
    return _ValidatedTarget(
        url=canonical_url,
        request_url=request_url,
        host_header=host_header,
        hostname=hostname,
        peer_ip=peer_ip,
    )


def _connected_peer_ip(response: requests.Response) -> str:
    raw = getattr(response, "raw", None)
    connection_candidates = (
        getattr(raw, "_connection", None),
        getattr(raw, "connection", None),
    )
    for connection in connection_candidates:
        sock = getattr(connection, "sock", None)
        if sock is not None:
            try:
                return str(sock.getpeername()[0])
            except (OSError, TypeError, ValueError):
                pass

    # urllib3 may expose the TLS socket only through the wrapped file object.
    wrapped_sock = getattr(
        getattr(
            getattr(
                getattr(raw, "_fp", None),
                "fp",
                None,
            ),
            "raw",
            None,
        ),
        "_sock",
        None,
    )
    if wrapped_sock is not None:
        try:
            return str(wrapped_sock.getpeername()[0])
        except (OSError, TypeError, ValueError):
            pass
    raise HTTPException(status_code=400, detail="无法验证图片服务器连接地址")


def _validate_connected_peer(
    response: requests.Response,
    expected_ip: str,
) -> None:
    try:
        peer_ip = str(ipaddress.ip_address(_connected_peer_ip(response)))
    except ValueError:
        raise HTTPException(status_code=400, detail="无法验证图片服务器连接地址")
    if peer_ip != expected_ip or _is_blocked_ip(peer_ip):
        raise HTTPException(status_code=400, detail="不允许访问内网或保留地址")


def download_remote_image(url: str, timeout: float = 5.0) -> DownloadedImage:
    if not _DOWNLOAD_SLOTS.acquire(blocking=False):
        raise HTTPException(status_code=429, detail="头像下载任务繁忙，请稍后重试")
    try:
        return _download_remote_image(url, timeout)
    finally:
        _DOWNLOAD_SLOTS.release()


def _download_remote_image(url: str, timeout: float) -> DownloadedImage:
    deadline = time.monotonic() + MAX_REMOTE_DOWNLOAD_SECONDS
    target = _validate_url(url.strip(), deadline)
    session = requests.Session()
    session.trust_env = False
    mounted_https_adapters: list[_PinnedHTTPSAdapter] = []
    try:
        for _ in range(MAX_REDIRECTS + 1):
            remaining = _remaining_seconds(deadline)
            request_timeout = min(timeout, remaining)
            if target.url.startswith("https://"):
                pinned_origin = target.request_url.split("/", 3)[:3]
                adapter = _PinnedHTTPSAdapter(target.hostname)
                mounted_https_adapters.append(adapter)
                session.mount(
                    "/".join(pinned_origin) + "/",
                    adapter,
                )
            try:
                response = session.get(
                    target.request_url,
                    timeout=(request_timeout, request_timeout),
                    headers={"User-Agent": USER_AGENT, "Host": target.host_header},
                    allow_redirects=False,
                    stream=True,
                )
            except requests.RequestException as exc:
                raise HTTPException(status_code=400, detail=f"无法获取图片: {exc}")

            try:
                _validate_connected_peer(response, target.peer_ip)
                if response.is_redirect:
                    location = response.headers.get("Location")
                    if not location:
                        raise HTTPException(status_code=400, detail="图片 URL 重定向缺少 Location")
                    target = _validate_url(urljoin(target.url, location), deadline)
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
                deadline_timer = threading.Timer(
                    _remaining_seconds(deadline),
                    response.close,
                )
                deadline_timer.daemon = True
                deadline_timer.start()
                try:
                    for chunk in response.iter_content(
                        chunk_size=REMOTE_IMAGE_CHUNK_BYTES
                    ):
                        _remaining_seconds(deadline)
                        if not chunk:
                            continue
                        total += len(chunk)
                        if total > MAX_REMOTE_IMAGE_BYTES:
                            raise HTTPException(status_code=400, detail="图片文件过大")
                        chunks.append(chunk)
                    _remaining_seconds(deadline)
                except requests.RequestException as exc:
                    if time.monotonic() >= deadline:
                        raise HTTPException(status_code=400, detail="图片下载超时")
                    raise HTTPException(status_code=400, detail=f"无法获取图片: {exc}")
                finally:
                    deadline_timer.cancel()

                return DownloadedImage(data=b"".join(chunks), content_type=content_type)
            finally:
                response.close()
    finally:
        session.close()
        for adapter in mounted_https_adapters:
            adapter.close()

    raise HTTPException(status_code=400, detail="图片 URL 重定向次数过多")
