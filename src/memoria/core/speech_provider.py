"""Async OpenAI Speech REST adapter.

This module contains the provider-specific request shapes and error mapping so
the API and service layers do not duplicate OpenAI contracts.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from memoria.core.config import Configs, configs


CONSENT_PHRASES = {
    "zh-CN": "我是此声音的拥有者并授权OpenAI使用此声音创建语音合成模型",
    "en-US": (
        "I am the owner of this voice and I consent to OpenAI using this voice "
        "to create a synthetic voice model."
    ),
}

STT_LANGUAGES = {"zh-CN": "zh", "en-US": "en"}


@dataclass(slots=True)
class SpeechProviderError(Exception):
    category: str
    message: str
    status_code: int = 502

    def __str__(self) -> str:
        return self.message


class OpenAISpeechProvider:
    """Minimal adapter for OpenAI transcription, speech, and custom voices."""

    def __init__(
        self,
        settings: Configs = configs,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.settings = settings
        self._client = client

    def _api_key(self) -> str:
        api_key = self.settings.speech_api_key.get_secret_value().strip()
        if not api_key:
            raise SpeechProviderError(
                "not_configured",
                "Speech API is not configured",
                503,
            )
        return api_key

    async def _request(
        self,
        method: str,
        path: str,
        *,
        custom_voice: bool = False,
        **kwargs: Any,
    ) -> httpx.Response:
        headers = dict(kwargs.pop("headers", {}))
        headers["Authorization"] = f"Bearer {self._api_key()}"
        base_url = self.settings.speech_base_url.rstrip("/")
        client = self._client
        owns_client = client is None
        if client is None:
            client = httpx.AsyncClient(timeout=self.settings.speech_timeout_seconds)

        try:
            response = await client.request(
                method,
                f"{base_url}{path}",
                headers=headers,
                **kwargs,
            )
        except httpx.TimeoutException as exc:
            raise SpeechProviderError("timeout", "Speech provider timed out", 504) from exc
        except httpx.HTTPError as exc:
            raise SpeechProviderError(
                "provider_failure",
                "Speech provider is unavailable",
                502,
            ) from exc
        finally:
            if owns_client:
                await client.aclose()

        if response.is_success:
            return response
        raise self._map_error(response, custom_voice=custom_voice)

    @staticmethod
    def _map_error(
        response: httpx.Response,
        *,
        custom_voice: bool,
    ) -> SpeechProviderError:
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        error = payload.get("error") if isinstance(payload, dict) else None
        if isinstance(error, dict):
            detail = str(error.get("message") or "")
        else:
            detail = str(error or payload.get("detail") or "") if isinstance(payload, dict) else ""
        lowered = detail.lower()

        if response.status_code == 429:
            return SpeechProviderError("rate_limited", "Speech provider rate limit exceeded", 429)
        if custom_voice and any(
            term in lowered
            for term in (
                "not eligible",
                "ineligible",
                "eligibility",
                "not available for this account",
                "custom voices are not available",
            )
        ):
            return SpeechProviderError(
                "unavailable",
                "Custom Voices are not available for this account",
                503,
            )
        if response.status_code in {400, 413, 415, 422}:
            message = detail or "The speech recording or request is invalid"
            return SpeechProviderError("invalid_input", message, 400)
        if response.status_code in {401, 403}:
            return SpeechProviderError("provider_failure", "Speech provider rejected the API key", 502)
        return SpeechProviderError(
            "provider_failure",
            detail or "Speech provider request failed",
            502,
        )

    @staticmethod
    def _json_object(response: httpx.Response) -> dict:
        try:
            payload = response.json()
        except ValueError as exc:
            raise SpeechProviderError(
                "provider_failure",
                "Speech provider returned an invalid JSON response",
                502,
            ) from exc
        if not isinstance(payload, dict):
            raise SpeechProviderError(
                "provider_failure",
                "Speech provider returned an invalid JSON response",
                502,
            )
        return payload

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
            data={
                "model": self.settings.speech_stt_model,
                "language": STT_LANGUAGES[locale],
            },
            files={"file": (filename, audio, mime_type)},
        )
        payload = self._json_object(response)
        return str(payload.get("text") or "").strip()

    async def synthesize(
        self,
        text: str,
        *,
        voice: str | dict[str, str],
        instructions: str = "",
    ) -> bytes:
        payload: dict[str, Any] = {
            "model": self.settings.speech_tts_model,
            "input": text,
            "voice": voice,
            "response_format": self.settings.speech_output_format,
        }
        if instructions.strip():
            payload["instructions"] = instructions.strip()
        response = await self._request("POST", "/audio/speech", json=payload)
        return response.content

    async def create_voice_consent(
        self,
        recording: bytes,
        *,
        filename: str,
        mime_type: str,
        name: str,
        locale: str,
    ) -> dict:
        response = await self._request(
            "POST",
            "/audio/voice_consents",
            custom_voice=True,
            data={"name": name, "language": locale},
            files={"recording": (filename, recording, mime_type)},
        )
        return self._json_object(response)

    async def create_custom_voice(
        self,
        audio_sample: bytes,
        *,
        filename: str,
        mime_type: str,
        name: str,
        consent_id: str,
    ) -> dict:
        response = await self._request(
            "POST",
            "/audio/voices",
            custom_voice=True,
            data={"name": name, "consent": consent_id},
            files={"audio_sample": (filename, audio_sample, mime_type)},
        )
        return self._json_object(response)
