"""Provider adapters for transcription, speech synthesis, and voice cloning."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import warnings
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from memoria.core.config import Configs, configs


logger = logging.getLogger(__name__)
_legacy_warning_emitted = False

CONSENT_PHRASES = {
    "zh-CN": "我是此声音的拥有者，并授权本系统使用这段录音创建该角色的合成音色。",
    "en-US": (
        "I own this voice and authorize this system to use this recording "
        "to create a synthetic voice for this character."
    ),
}
STT_LANGUAGES = {"zh-CN": "zh", "en-US": "en"}


@dataclass(slots=True)
class SpeechProviderError(Exception):
    category: str
    message: str
    status_code: int = 502
    retryable: bool = False

    def __str__(self) -> str:
        return self.message


@dataclass(frozen=True, slots=True)
class ProviderSettings:
    provider: str
    api_key: str
    base_url: str
    model: str
    timeout_seconds: float
    max_retries: int


class TranscriptionProvider(Protocol):
    async def transcribe(
        self,
        audio: bytes,
        *,
        filename: str,
        mime_type: str,
        locale: str,
    ) -> str: ...


class SpeechSynthesisProvider(Protocol):
    async def synthesize_stream(
        self,
        text: str,
        *,
        voice: str,
        instructions: str = "",
    ) -> AsyncIterator[bytes]: ...


class VoiceCloningProvider(Protocol):
    async def create_custom_voice(
        self,
        *,
        authorization_audio: bytes,
        authorization_filename: str,
        authorization_mime_type: str,
        reference_audio: bytes,
        reference_filename: str,
        reference_mime_type: str,
        reference_transcript: str,
        voice_id: str,
        name: str,
        locale: str,
    ) -> dict[str, str]: ...


class OpenAICompatibleSpeechProvider:
    """OpenAI-compatible transcription and non-streaming TTS adapter."""

    def __init__(
        self,
        settings: ProviderSettings,
        *,
        output_format: str,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.settings = settings
        self.output_format = output_format
        self._client = client

    def _headers(self) -> dict[str, str]:
        if not self.settings.api_key:
            raise SpeechProviderError(
                "not_configured",
                "Speech API is not configured",
                503,
            )
        return {"Authorization": f"Bearer {self.settings.api_key}"}

    async def _request(
        self,
        method: str,
        path: str,
        **kwargs: Any,
    ) -> httpx.Response:
        client = self._client
        owns_client = client is None
        if client is None:
            client = httpx.AsyncClient(timeout=self.settings.timeout_seconds)
        try:
            response = await client.request(
                method,
                f"{self.settings.base_url.rstrip('/')}{path}",
                headers=self._headers(),
                **kwargs,
            )
        except httpx.TimeoutException as exc:
            raise SpeechProviderError(
                "timeout",
                "Speech provider timed out",
                504,
                retryable=True,
            ) from exc
        except httpx.HTTPError as exc:
            raise SpeechProviderError(
                "provider_failure",
                "Speech provider is unavailable",
                502,
                retryable=True,
            ) from exc
        finally:
            if owns_client:
                await client.aclose()
        if response.is_success:
            return response
        raise _map_http_error(response)

    async def transcribe(
        self,
        audio: bytes,
        *,
        filename: str,
        mime_type: str,
        locale: str,
    ) -> str:
        response = await self._request(
            "POST",
            "/audio/transcriptions",
            data={"model": self.settings.model, "language": STT_LANGUAGES[locale]},
            files={"file": (filename, audio, mime_type)},
        )
        payload = _json_object(response)
        return str(payload.get("text") or "").strip()

    async def synthesize_stream(
        self,
        text: str,
        *,
        voice: str,
        instructions: str = "",
    ) -> AsyncIterator[bytes]:
        payload: dict[str, Any] = {
            "model": self.settings.model,
            "input": text,
            "voice": voice,
            "response_format": self.output_format,
        }
        if instructions.strip():
            payload["instructions"] = instructions.strip()
        response = await self._request("POST", "/audio/speech", json=payload)
        if not response.content:
            raise SpeechProviderError(
                "provider_failure",
                "Speech provider returned empty audio",
                502,
            )
        yield response.content


class MiniMaxSpeechProvider:
    """MiniMax T2A v2 streaming synthesis and fast voice cloning adapter."""

    def __init__(
        self,
        settings: ProviderSettings,
        *,
        output_format: str,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.settings = settings
        self.output_format = output_format
        self._client = client

    def _headers(self) -> dict[str, str]:
        if not self.settings.api_key:
            raise SpeechProviderError(
                "not_configured",
                "MiniMax TTS API is not configured",
                503,
            )
        return {"Authorization": f"Bearer {self.settings.api_key}"}

    def _tts_payload(self, text: str, voice: str, instructions: str) -> dict[str, Any]:
        if self.output_format != "mp3":
            raise SpeechProviderError(
                "invalid_input",
                "MiniMax streaming synthesis requires MP3 output",
                400,
            )
        payload: dict[str, Any] = {
            "model": self.settings.model,
            "text": text,
            "stream": True,
            "voice_setting": {
                "voice_id": voice,
                "speed": 1.0,
                "vol": 1.0,
                "pitch": 0,
            },
            "audio_setting": {
                "sample_rate": 32000,
                "bitrate": 128000,
                "format": "mp3",
                "channel": 1,
            },
        }
        # The T2A v2 API has no instruction field. The existing character
        # instruction remains part of cache identity for future provider swaps.
        del instructions
        return payload

    async def synthesize_stream(
        self,
        text: str,
        *,
        voice: str,
        instructions: str = "",
    ) -> AsyncIterator[bytes]:
        payload = self._tts_payload(text, voice, instructions)
        attempts = self.settings.max_retries + 1
        for attempt in range(attempts):
            yielded = False
            started_at = time.perf_counter()
            try:
                async for chunk in self._request_stream(payload):
                    yielded = True
                    yield chunk
                return
            except SpeechProviderError as exc:
                if yielded or not exc.retryable or attempt + 1 >= attempts:
                    raise
                logger.warning(
                    "Retrying MiniMax TTS before first audio chunk",
                    extra={
                        "provider": "minimax",
                        "model": self.settings.model,
                        "attempt": attempt + 1,
                        "elapsed_ms": round((time.perf_counter() - started_at) * 1000),
                    },
                )
                await asyncio.sleep(0.2 * (attempt + 1))

    async def _request_stream(self, payload: dict[str, Any]) -> AsyncIterator[bytes]:
        client = self._client
        owns_client = client is None
        if client is None:
            client = httpx.AsyncClient(timeout=self.settings.timeout_seconds)
        try:
            async with client.stream(
                "POST",
                f"{self.settings.base_url.rstrip('/')}/t2a_v2",
                headers=self._headers(),
                json=payload,
            ) as response:
                if not response.is_success:
                    content = await response.aread()
                    raise _map_http_error(response, content=content)
                async for payload in _sse_json_events(response):
                    _raise_minimax_response_error(payload)
                    audio_hex = _minimax_audio_hex(payload)
                    if not audio_hex:
                        continue
                    try:
                        yield bytes.fromhex(audio_hex)
                    except ValueError as exc:
                        raise SpeechProviderError(
                            "provider_failure",
                            "MiniMax returned invalid audio data",
                            502,
                        ) from exc
        except SpeechProviderError:
            raise
        except httpx.TimeoutException as exc:
            raise SpeechProviderError(
                "timeout",
                "MiniMax TTS timed out",
                504,
                retryable=True,
            ) from exc
        except httpx.HTTPError as exc:
            raise SpeechProviderError(
                "provider_failure",
                "MiniMax TTS is unavailable",
                502,
                retryable=True,
            ) from exc
        finally:
            if owns_client:
                await client.aclose()

    async def create_custom_voice(
        self,
        *,
        authorization_audio: bytes,
        authorization_filename: str,
        authorization_mime_type: str,
        reference_audio: bytes,
        reference_filename: str,
        reference_mime_type: str,
        reference_transcript: str,
        voice_id: str,
        name: str,
        locale: str,
    ) -> dict[str, str]:
        del name
        prompt_text = reference_transcript.strip()
        if not prompt_text:
            raise SpeechProviderError(
                "invalid_input",
                "A transcript is required for the reference audio",
                400,
            )
        source_file_id = await self._upload_clone_file(
            authorization_audio,
            filename=authorization_filename,
            mime_type=authorization_mime_type,
            purpose="voice_clone",
        )
        prompt_file_id = await self._upload_clone_file(
            reference_audio,
            filename=reference_filename,
            mime_type=reference_mime_type,
            purpose="prompt_audio",
        )
        response = await self._request_json(
            "POST",
            "/voice_clone",
            {
                "file_id": source_file_id,
                "voice_id": voice_id,
                "text_validation": CONSENT_PHRASES[locale],
                "clone_prompt": {
                    "prompt_audio": prompt_file_id,
                    "prompt_text": prompt_text,
                },
                "need_noise_reduction": True,
                "need_volume_normalization": True,
            },
        )
        _raise_minimax_response_error(response)
        return {"id": voice_id}

    async def _upload_clone_file(
        self,
        audio: bytes,
        *,
        filename: str,
        mime_type: str,
        purpose: str,
    ) -> str:
        response = await self._request_json(
            "POST",
            "/files/upload",
            data={"purpose": purpose},
            files={"file": (filename, audio, mime_type)},
        )
        _raise_minimax_response_error(response)
        file_data = response.get("file")
        if not isinstance(file_data, dict) or not file_data.get("file_id"):
            raise SpeechProviderError(
                "provider_failure",
                "MiniMax did not return an uploaded file ID",
                502,
            )
        return str(file_data["file_id"])

    async def _request_json(
        self,
        method: str,
        path: str,
        json_payload: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        client = self._client
        owns_client = client is None
        if client is None:
            client = httpx.AsyncClient(timeout=self.settings.timeout_seconds)
        try:
            response = await client.request(
                method,
                f"{self.settings.base_url.rstrip('/')}{path}",
                headers=self._headers(),
                json=json_payload,
                **kwargs,
            )
        except httpx.TimeoutException as exc:
            raise SpeechProviderError("timeout", "MiniMax request timed out", 504) from exc
        except httpx.HTTPError as exc:
            raise SpeechProviderError(
                "provider_failure",
                "MiniMax is unavailable",
                502,
            ) from exc
        finally:
            if owns_client:
                await client.aclose()
        if not response.is_success:
            raise _map_http_error(response)
        return _json_object(response)


def _json_object(response: httpx.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError as exc:
        raise SpeechProviderError(
            "provider_failure",
            "Speech provider returned invalid JSON",
            502,
        ) from exc
    if not isinstance(payload, dict):
        raise SpeechProviderError(
            "provider_failure",
            "Speech provider returned invalid JSON",
            502,
        )
    return payload


def _map_http_error(
    response: httpx.Response,
    *,
    content: bytes | None = None,
) -> SpeechProviderError:
    try:
        payload = response.json() if content is None else json.loads(content)
    except (ValueError, TypeError):
        payload = {}
    detail = ""
    if isinstance(payload, dict):
        error = payload.get("error")
        base_resp = payload.get("base_resp")
        if isinstance(error, dict):
            detail = str(error.get("message") or "")
        elif isinstance(base_resp, dict):
            detail = str(base_resp.get("status_msg") or "")
        else:
            detail = str(error or payload.get("detail") or "")
    if response.status_code == 429:
        return SpeechProviderError(
            "rate_limited",
            "Speech provider rate limit exceeded",
            429,
        )
    if response.status_code in {400, 413, 415, 422}:
        return SpeechProviderError(
            "invalid_input",
            detail or "The speech request is invalid",
            400,
        )
    if response.status_code in {401, 403}:
        return SpeechProviderError(
            "provider_failure",
            "Speech provider rejected the API key",
            502,
        )
    return SpeechProviderError(
        "provider_failure",
        detail or "Speech provider request failed",
        502,
        retryable=response.status_code >= 500,
    )


async def _sse_json_events(response: httpx.Response) -> AsyncIterator[dict[str, Any]]:
    data_lines: list[str] = []
    async for line in response.aiter_lines():
        if not line:
            if data_lines:
                yield _decode_sse_payload("\n".join(data_lines))
                data_lines = []
            continue
        if line.startswith("data:"):
            data_lines.append(line[5:].lstrip())
    if data_lines:
        yield _decode_sse_payload("\n".join(data_lines))


def _decode_sse_payload(data: str) -> dict[str, Any]:
    if data == "[DONE]":
        return {}
    try:
        payload = json.loads(data)
    except ValueError as exc:
        raise SpeechProviderError(
            "provider_failure",
            "MiniMax returned an invalid streaming response",
            502,
        ) from exc
    if not isinstance(payload, dict):
        raise SpeechProviderError(
            "provider_failure",
            "MiniMax returned an invalid streaming response",
            502,
        )
    return payload


def _minimax_audio_hex(payload: dict[str, Any]) -> str:
    data = payload.get("data")
    if not isinstance(data, dict):
        return ""
    audio = data.get("audio")
    return audio.strip() if isinstance(audio, str) else ""


def _raise_minimax_response_error(payload: dict[str, Any]) -> None:
    base_resp = payload.get("base_resp")
    if not isinstance(base_resp, dict):
        return
    status_code = base_resp.get("status_code")
    if status_code in {None, 0, "0"}:
        return
    message = str(base_resp.get("status_msg") or "MiniMax request failed")
    if str(status_code) in {"2049"}:
        raise SpeechProviderError("provider_failure", "MiniMax rejected the API key", 502)
    if str(status_code) in {"2038"}:
        raise SpeechProviderError("unavailable", "MiniMax voice cloning is unavailable", 503)
    if str(status_code) in {"2037", "2039", "2042", "2048", "20132"}:
        raise SpeechProviderError("invalid_input", message, 400)
    raise SpeechProviderError("provider_failure", message, 502)


def _secret(settings: Configs, name: str) -> str:
    return getattr(settings, name).get_secret_value().strip()


def _legacy_tts_settings(settings: Configs) -> ProviderSettings | None:
    global _legacy_warning_emitted
    api_key = _secret(settings, "speech_api_key")
    if not api_key:
        return None
    if not _legacy_warning_emitted:
        warnings.warn(
            "speech_provider, speech_api_key, speech_base_url, and "
            "speech_timeout_seconds are deprecated; configure speech_tts_* and "
            "speech_stt_* independently.",
            DeprecationWarning,
            stacklevel=3,
        )
        _legacy_warning_emitted = True
    legacy_provider = settings.speech_provider
    provider = "minimax" if legacy_provider in {"minimax", "mimo"} else legacy_provider
    return ProviderSettings(
        provider=provider,
        api_key=api_key,
        base_url=settings.speech_base_url,
        model=settings.speech_tts_model,
        timeout_seconds=settings.speech_timeout_seconds,
        max_retries=settings.speech_tts_max_retries,
    )


def tts_provider_settings(settings: Configs = configs) -> ProviderSettings:
    api_key = _secret(settings, "speech_tts_api_key")
    if not api_key:
        legacy = _legacy_tts_settings(settings)
        if legacy is not None:
            return legacy
    return ProviderSettings(
        provider=settings.speech_tts_provider,
        api_key=api_key,
        base_url=settings.speech_tts_base_url,
        model=settings.speech_tts_model,
        timeout_seconds=settings.speech_tts_timeout_seconds,
        max_retries=settings.speech_tts_max_retries,
    )


def stt_provider_settings(settings: Configs = configs) -> ProviderSettings:
    api_key = _secret(settings, "speech_stt_api_key")
    if not api_key:
        legacy = _legacy_tts_settings(settings)
        if legacy is not None:
            return ProviderSettings(
                provider=legacy.provider if legacy.provider != "minimax" else "openai_compatible",
                api_key=legacy.api_key,
                base_url=legacy.base_url,
                model=settings.speech_stt_model,
                timeout_seconds=legacy.timeout_seconds,
                max_retries=settings.speech_stt_max_retries,
            )
    return ProviderSettings(
        provider=settings.speech_stt_provider,
        api_key=api_key,
        base_url=settings.speech_stt_base_url,
        model=settings.speech_stt_model,
        timeout_seconds=settings.speech_stt_timeout_seconds,
        max_retries=settings.speech_stt_max_retries,
    )


def create_tts_provider(
    settings: Configs = configs,
    client: httpx.AsyncClient | None = None,
) -> SpeechSynthesisProvider:
    connection = tts_provider_settings(settings)
    if connection.provider == "minimax":
        return MiniMaxSpeechProvider(
            connection,
            output_format=settings.speech_output_format,
            client=client,
        )
    if connection.provider in {"openai", "openai_compatible"}:
        return OpenAICompatibleSpeechProvider(
            connection,
            output_format=settings.speech_output_format,
            client=client,
        )
    raise SpeechProviderError(
        "not_configured",
        f"Unsupported TTS provider: {connection.provider}",
        503,
    )


def create_stt_provider(
    settings: Configs = configs,
    client: httpx.AsyncClient | None = None,
) -> TranscriptionProvider:
    connection = stt_provider_settings(settings)
    if connection.provider in {"openai", "openai_compatible"}:
        return OpenAICompatibleSpeechProvider(
            connection,
            output_format=settings.speech_output_format,
            client=client,
        )
    raise SpeechProviderError(
        "not_configured",
        f"Unsupported STT provider: {connection.provider}",
        503,
    )


def speech_provider_configuration(settings: Configs = configs) -> dict[str, Any]:
    connection = tts_provider_settings(settings)
    voices = [
        voice.strip()
        for voice in settings.speech_tts_builtin_voices.split(",")
        if voice.strip()
    ]
    default_voice = settings.speech_tts_default_voice.strip()
    if default_voice not in voices:
        default_voice = voices[0] if voices else "female-shaonv"
    return {
        "provider": connection.provider,
        "provider_label": "MiniMax" if connection.provider == "minimax" else "OpenAI-compatible",
        "builtin_voices": voices,
        "default_builtin_voice": default_voice,
        "custom_voice_supported": connection.provider == "minimax",
    }
