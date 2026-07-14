"""Speech provider and service contract tests."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from io import BytesIO
import json
from pathlib import Path
import uuid
import wave

import fastapi.dependencies.utils
import fastapi.routing
import httpx
import pytest
from fastapi import FastAPI, Response
from pydantic import SecretStr

from memoria.api import speech as speech_api
from memoria.api import user as user_api
from memoria.core.character_loader import normalize_character_data
from memoria.core.character_schema import CharacterCard
from memoria.core.config import configs
from memoria.core.speech_provider import OpenAISpeechProvider, SpeechProviderError
from memoria.core.speech_service import SpeechService, SpeechServiceError
from memoria.db import repository


def _character_card(character_id: str, *, voice: str = "alloy") -> CharacterCard:
    source = Path(__file__).resolve().parent.parent / "src/memoria/characters/npc_luo_xiaohei.json"
    raw = normalize_character_data(json.loads(source.read_text(encoding="utf-8")))
    card = CharacterCard.model_validate(raw)
    card.character_id = character_id
    card.meta.name = character_id
    card.meta.display_name = character_id
    card.voice.builtin_voice = voice
    return card


def _save_card(owner_user_id: str, card: CharacterCard) -> None:
    assert repository.save_character_card_to_db(
        owner_user_id,
        card.character_id,
        json.dumps(card.model_dump(mode="json", by_alias=True), ensure_ascii=False),
        version=card.version,
        name=card.meta.name,
        display_name=card.meta.display_name,
    )


def _wav_bytes(duration_seconds: float = 0.1) -> bytes:
    output = BytesIO()
    with wave.open(output, "wb") as recording:
        recording.setnchannels(1)
        recording.setsampwidth(2)
        recording.setframerate(8000)
        recording.writeframes(b"\0\0" * int(8000 * duration_seconds))
    return output.getvalue()


def _authenticated_user(prefix: str) -> tuple[str, dict[str, str]]:
    user_id = f"{prefix}_{uuid.uuid4().hex[:10]}"
    repository.create_user(
        user_id,
        f"{prefix}_{uuid.uuid4().hex[:8]}",
        "test-hash",
    )
    token = f"token_{uuid.uuid4().hex}"
    expires_at = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    repository.create_auth_token(token, user_id, expires_at)
    return user_id, {"Authorization": f"Bearer {token}"}


def _run_fastapi_sync_inline(monkeypatch) -> None:
    async def run_inline(function, *args, **kwargs):
        return function(*args, **kwargs)

    monkeypatch.setattr(fastapi.routing, "run_in_threadpool", run_inline)
    monkeypatch.setattr(fastapi.dependencies.utils, "run_in_threadpool", run_inline)


class FakeSpeechProvider:
    def __init__(self):
        self.transcriptions = []
        self.syntheses = []
        self.consents = []
        self.voices = []

    async def transcribe(self, audio, **kwargs):
        self.transcriptions.append((audio, kwargs))
        return "transcribed text"

    async def synthesize(self, text, **kwargs):
        self.syntheses.append((text, kwargs))
        return b"RIFF-generated-wav"

    async def create_voice_consent(self, recording, **kwargs):
        self.consents.append((recording, kwargs))
        return {"id": "cons_1234"}

    async def create_custom_voice(self, audio_sample, **kwargs):
        self.voices.append((audio_sample, kwargs))
        return {"id": "voice_1234"}


@pytest.mark.asyncio
async def test_speech_http_routes_enforce_auth_modes_and_audio_contract(monkeypatch, tmp_path):
    _run_fastapi_sync_inline(monkeypatch)

    def inline_file_response(path, *, media_type, filename, headers):
        return Response(
            content=Path(path).read_bytes(),
            media_type=media_type,
            headers={
                **headers,
                "Content-Disposition": f'attachment; filename="{filename}"',
            },
        )

    monkeypatch.setattr(speech_api, "FileResponse", inline_file_response)
    owner, owner_headers = _authenticated_user("speech_http_owner")
    _, intruder_headers = _authenticated_user("speech_http_intruder")
    character_id = f"character_{uuid.uuid4().hex[:8]}"
    session_id = str(uuid.uuid4())
    _save_card(owner, _character_card(character_id, voice="coral"))
    repository.create_session(session_id, character_id, owner, "Player", locale="en-US")
    message_id = repository.append_short_term_message(session_id, "assistant", "Route audio")

    provider = FakeSpeechProvider()
    monkeypatch.setattr(configs, "speech_storage_path", str(tmp_path))
    monkeypatch.setattr(configs, "speech_output_format", "wav")
    monkeypatch.setattr(speech_api, "speech_service", SpeechService(configs, provider))

    app = FastAPI()
    app.include_router(speech_api.router, prefix="/api/v1")
    transport = httpx.ASGITransport(app=app)
    audio_path = f"/api/v1/speech/single/sessions/{session_id}/messages/{message_id}/audio"

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        unauthorized = await client.get(audio_path)
        assert unauthorized.status_code == 401

        cross_user = await client.post(
            "/api/v1/speech/transcriptions",
            data={"session_id": session_id, "mode": "single"},
            files={"file": ("recording.webm", b"webm audio", "audio/webm")},
            headers=intruder_headers,
        )
        assert cross_user.status_code == 403
        assert cross_user.json()["detail"] == {
            "category": "invalid_request",
            "message": "You do not have access to this session",
        }

        wrong_mode = await client.post(
            "/api/v1/speech/transcriptions",
            data={"session_id": session_id, "mode": "group"},
            files={"file": ("recording.webm", b"webm audio", "audio/webm")},
            headers=owner_headers,
        )
        assert wrong_mode.status_code == 400
        assert wrong_mode.json()["detail"]["message"] == "Speech mode does not match the session"

        transcription = await client.post(
            "/api/v1/speech/transcriptions",
            data={"session_id": session_id, "mode": "single"},
            files={"file": ("recording.webm", b"webm audio", "audio/webm")},
            headers=owner_headers,
        )
        assert transcription.status_code == 200
        assert transcription.json() == {"text": "transcribed text", "locale": "en-US"}

        group_audio = await client.get(
            f"/api/v1/speech/group/sessions/{session_id}/messages/{message_id}/audio",
            headers=owner_headers,
        )
        assert group_audio.status_code == 400

        first_audio = await client.get(audio_path, headers=owner_headers)
        assert first_audio.status_code == 200
        assert first_audio.content == b"RIFF-generated-wav"
        assert first_audio.headers["content-type"] == "audio/wav"
        assert first_audio.headers["cache-control"] == "private, max-age=86400"
        assert first_audio.headers["x-speech-cache"] == "MISS"
        assert first_audio.headers["x-ai-generated-audio"] == "true"
        assert first_audio.headers["etag"]

        cached_audio = await client.get(audio_path, headers=owner_headers)
        assert cached_audio.status_code == 200
        assert cached_audio.headers["x-speech-cache"] == "HIT"
        assert cached_audio.headers["etag"] == first_audio.headers["etag"]


@pytest.mark.asyncio
async def test_speech_settings_http_api_persists_and_isolates_users(monkeypatch):
    _run_fastapi_sync_inline(monkeypatch)
    owner, owner_headers = _authenticated_user("speech_settings_owner")
    _, other_headers = _authenticated_user("speech_settings_other")
    app = FastAPI()
    app.include_router(user_api.router, prefix="/api/v1")
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        unauthorized = await client.put(
            "/api/v1/user/speech-settings",
            json={"tts_auto_play": True, "stt_auto_send": True},
        )
        assert unauthorized.status_code == 401

        updated = await client.put(
            "/api/v1/user/speech-settings",
            json={"tts_auto_play": True, "stt_auto_send": True},
            headers=owner_headers,
        )
        assert updated.status_code == 200
        assert updated.json()["user_id"] == owner
        assert updated.json()["tts_auto_play"] is True
        assert updated.json()["stt_auto_send"] is True

        persisted = await client.get("/api/v1/user/me", headers=owner_headers)
        assert persisted.status_code == 200
        assert persisted.json()["tts_auto_play"] is True
        assert persisted.json()["stt_auto_send"] is True

        isolated = await client.get("/api/v1/user/me", headers=other_headers)
        assert isolated.status_code == 200
        assert isolated.json()["tts_auto_play"] is False
        assert isolated.json()["stt_auto_send"] is False


@pytest.mark.asyncio
async def test_provider_uses_official_speech_payloads(monkeypatch):
    requests = []

    async def handler(request: httpx.Request) -> httpx.Response:
        body = await request.aread()
        requests.append((request, body))
        if request.url.path.endswith("/audio/transcriptions"):
            return httpx.Response(200, json={"text": "hello"})
        if request.url.path.endswith("/audio/speech"):
            return httpx.Response(200, content=b"wav")
        if request.url.path.endswith("/audio/voice_consents"):
            return httpx.Response(200, json={"id": "cons_1"})
        return httpx.Response(200, json={"id": "voice_1"})

    monkeypatch.setattr(configs, "speech_api_key", SecretStr("speech-key"))
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = OpenAISpeechProvider(configs, client)

    await provider.transcribe(
        b"audio",
        filename="clip.webm",
        mime_type="audio/webm",
        locale="en-US",
    )
    await provider.synthesize(
        "Hello",
        voice={"id": "voice_1234"},
        instructions="Speak softly.",
    )
    await provider.create_voice_consent(
        b"consent",
        filename="consent.wav",
        mime_type="audio/wav",
        name="Consent",
        locale="zh-CN",
    )
    await provider.create_custom_voice(
        b"sample",
        filename="sample.wav",
        mime_type="audio/wav",
        name="Voice",
        consent_id="cons_1",
    )
    await client.aclose()

    transcription_body = requests[0][1]
    assert b'name="model"' in transcription_body
    assert configs.speech_stt_model.encode() in transcription_body
    assert b'name="language"' in transcription_body
    assert b"\r\n\r\nen\r\n" in transcription_body
    assert b'name="file"; filename="clip.webm"' in transcription_body

    speech_payload = json.loads(requests[1][1])
    assert speech_payload == {
        "model": configs.speech_tts_model,
        "input": "Hello",
        "voice": {"id": "voice_1234"},
        "response_format": "wav",
        "instructions": "Speak softly.",
    }
    assert b'name="recording"; filename="consent.wav"' in requests[2][1]
    assert b'name="language"' in requests[2][1]
    assert b"zh-CN" in requests[2][1]
    assert b'name="audio_sample"; filename="sample.wav"' in requests[3][1]
    assert b'name="consent"' in requests[3][1]
    assert b"cons_1" in requests[3][1]


@pytest.mark.asyncio
async def test_provider_maps_rate_limit_and_custom_voice_unavailable(monkeypatch):
    monkeypatch.setattr(configs, "speech_api_key", SecretStr("speech-key"))

    async def rate_limited(_request):
        return httpx.Response(429, json={"error": {"message": "slow down"}})

    client = httpx.AsyncClient(transport=httpx.MockTransport(rate_limited))
    provider = OpenAISpeechProvider(configs, client)
    with pytest.raises(SpeechProviderError, match="rate limit") as exc_info:
        await provider.synthesize("hello", voice="alloy")
    assert exc_info.value.category == "rate_limited"
    await client.aclose()

    async def forbidden(_request):
        return httpx.Response(403, json={"error": {"message": "not eligible"}})

    client = httpx.AsyncClient(transport=httpx.MockTransport(forbidden))
    provider = OpenAISpeechProvider(configs, client)
    with pytest.raises(SpeechProviderError) as exc_info:
        await provider.create_voice_consent(
            b"audio",
            filename="clip.wav",
            mime_type="audio/wav",
            name="test",
            locale="en-US",
        )
    assert exc_info.value.category == "unavailable"
    await client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [401, 403, 404])
async def test_provider_does_not_infer_custom_voice_unavailable_from_status(
    monkeypatch,
    status_code,
):
    monkeypatch.setattr(configs, "speech_api_key", SecretStr("speech-key"))

    async def rejected(_request):
        return httpx.Response(
            status_code,
            json={"error": {"message": "request rejected"}},
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(rejected))
    provider = OpenAISpeechProvider(configs, client)
    with pytest.raises(SpeechProviderError) as exc_info:
        await provider.create_voice_consent(
            b"audio",
            filename="clip.wav",
            mime_type="audio/wav",
            name="test",
            locale="en-US",
        )
    assert exc_info.value.category == "provider_failure"
    await client.aclose()


@pytest.mark.asyncio
async def test_provider_wraps_successful_non_json_response(monkeypatch):
    monkeypatch.setattr(configs, "speech_api_key", SecretStr("speech-key"))

    async def invalid_json(_request):
        return httpx.Response(200, text="not-json")

    client = httpx.AsyncClient(transport=httpx.MockTransport(invalid_json))
    provider = OpenAISpeechProvider(configs, client)
    with pytest.raises(SpeechProviderError, match="invalid JSON") as exc_info:
        await provider.create_custom_voice(
            b"sample",
            filename="sample.wav",
            mime_type="audio/wav",
            name="test",
            consent_id="consent",
        )
    assert exc_info.value.category == "provider_failure"
    assert exc_info.value.status_code == 502
    await client.aclose()


@pytest.mark.asyncio
async def test_transcription_authorizes_session_and_passes_persisted_locale(monkeypatch, tmp_path):
    owner = f"speech_{uuid.uuid4().hex[:8]}"
    session_id = str(uuid.uuid4())
    repository.create_session(session_id, "char", owner, "Player", locale="en-US")
    provider = FakeSpeechProvider()
    monkeypatch.setattr(configs, "speech_storage_path", str(tmp_path))
    service = SpeechService(configs, provider)

    result = await service.transcribe(
        session_id=session_id,
        current_user_id=owner,
        mode="single",
        audio=b"webm audio",
        filename="recording.webm",
        mime_type="audio/webm;codecs=opus",
    )

    assert result == {"text": "transcribed text", "locale": "en-US"}
    assert provider.transcriptions[0][1]["locale"] == "en-US"
    with pytest.raises(SpeechServiceError) as exc_info:
        await service.transcribe(
            session_id=session_id,
            current_user_id="another-user",
            mode="single",
            audio=b"audio",
            filename="recording.webm",
            mime_type="audio/webm",
        )
    assert exc_info.value.status_code == 403
    with pytest.raises(SpeechServiceError) as exc_info:
        await service.transcribe(
            session_id=session_id,
            current_user_id=owner,
            mode="group",
            audio=b"audio",
            filename="recording.webm",
            mime_type="audio/webm",
        )
    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_tts_is_assistant_only_uses_custom_voice_and_cache_invalidates(monkeypatch, tmp_path):
    owner = f"speech_{uuid.uuid4().hex[:8]}"
    character_id = f"character_{uuid.uuid4().hex[:8]}"
    session_id = str(uuid.uuid4())
    card = _character_card(character_id, voice="coral")
    card.voice.custom_voice_status = "ready"
    card.voice.custom_voice_id = "voice_custom"
    card.voice.tts_instructions = "Calm and measured."
    _save_card(owner, card)
    repository.create_session(session_id, character_id, owner, "Player")
    user_message_id = repository.append_short_term_message(session_id, "user", "Read me")
    assistant_message_id = repository.append_short_term_message(session_id, "assistant", "Hello")
    provider = FakeSpeechProvider()
    monkeypatch.setattr(configs, "speech_storage_path", str(tmp_path))
    service = SpeechService(configs, provider)

    first = await service.message_audio(
        session_id=session_id,
        message_id=assistant_message_id,
        current_user_id=owner,
        mode="single",
    )
    second = await service.message_audio(
        session_id=session_id,
        message_id=assistant_message_id,
        current_user_id=owner,
        mode="single",
    )

    assert first.cache_hit is False
    assert second.cache_hit is True
    assert len(provider.syntheses) == 1
    assert provider.syntheses[0][1]["voice"] == {"id": "voice_custom"}
    assert provider.syntheses[0][1]["instructions"] == "Calm and measured."

    card.voice.tts_instructions = "Faster."
    _save_card(owner, card)
    changed = await service.message_audio(
        session_id=session_id,
        message_id=assistant_message_id,
        current_user_id=owner,
        mode="single",
    )
    assert changed.cache_key != first.cache_key
    assert len(provider.syntheses) == 2

    with pytest.raises(SpeechServiceError, match="Only assistant"):
        await service.message_audio(
            session_id=session_id,
            message_id=user_message_id,
            current_user_id=owner,
            mode="single",
        )


@pytest.mark.asyncio
async def test_tts_cache_lock_cleans_up_after_failure_and_allows_retry(monkeypatch, tmp_path):
    class FlakyProvider(FakeSpeechProvider):
        async def synthesize(self, text, **kwargs):
            self.syntheses.append((text, kwargs))
            if len(self.syntheses) == 1:
                raise SpeechProviderError("provider_failure", "temporary failure", 502)
            return b"RIFF-recovered-wav"

    owner = f"speech_{uuid.uuid4().hex[:8]}"
    character_id = f"character_{uuid.uuid4().hex[:8]}"
    session_id = str(uuid.uuid4())
    _save_card(owner, _character_card(character_id))
    repository.create_session(session_id, character_id, owner, "Player")
    message_id = repository.append_short_term_message(session_id, "assistant", "Retry me")
    provider = FlakyProvider()
    monkeypatch.setattr(configs, "speech_storage_path", str(tmp_path))
    service = SpeechService(configs, provider)

    with pytest.raises(SpeechServiceError, match="temporary failure"):
        await service.message_audio(
            session_id=session_id,
            message_id=message_id,
            current_user_id=owner,
            mode="single",
        )
    assert service._cache_locks == {}

    recovered = await service.message_audio(
        session_id=session_id,
        message_id=message_id,
        current_user_id=owner,
        mode="single",
    )

    assert recovered.cache_hit is False
    assert recovered.path.read_bytes() == b"RIFF-recovered-wav"
    assert len(provider.syntheses) == 2
    assert service._cache_locks == {}


@pytest.mark.asyncio
async def test_tts_concurrent_same_key_synthesizes_once_and_releases_lock(monkeypatch, tmp_path):
    class BlockingProvider(FakeSpeechProvider):
        def __init__(self):
            super().__init__()
            self.started = asyncio.Event()
            self.release = asyncio.Event()

        async def synthesize(self, text, **kwargs):
            self.syntheses.append((text, kwargs))
            self.started.set()
            await self.release.wait()
            return b"RIFF-concurrent-wav"

    owner = f"speech_{uuid.uuid4().hex[:8]}"
    character_id = f"character_{uuid.uuid4().hex[:8]}"
    session_id = str(uuid.uuid4())
    _save_card(owner, _character_card(character_id))
    repository.create_session(session_id, character_id, owner, "Player")
    message_id = repository.append_short_term_message(session_id, "assistant", "Once only")
    provider = BlockingProvider()
    monkeypatch.setattr(configs, "speech_storage_path", str(tmp_path))
    service = SpeechService(configs, provider)

    requests = [
        asyncio.create_task(service.message_audio(
            session_id=session_id,
            message_id=message_id,
            current_user_id=owner,
            mode="single",
        ))
        for _ in range(5)
    ]
    await provider.started.wait()
    await asyncio.sleep(0)
    provider.release.set()
    results = await asyncio.gather(*requests)

    assert len(provider.syntheses) == 1
    assert sum(not result.cache_hit for result in results) == 1
    assert sum(result.cache_hit for result in results) == 4
    assert service._cache_locks == {}


@pytest.mark.asyncio
async def test_group_tts_uses_persisted_message_speaker(monkeypatch, tmp_path):
    owner = f"speech_{uuid.uuid4().hex[:8]}"
    first_id = f"first_{uuid.uuid4().hex[:8]}"
    second_id = f"second_{uuid.uuid4().hex[:8]}"
    _save_card(owner, _character_card(first_id, voice="alloy"))
    _save_card(owner, _character_card(second_id, voice="sage"))
    session_id = str(uuid.uuid4())
    assert repository.create_multi_character_session(
        session_id,
        owner,
        "Player",
        [first_id, second_id],
    )
    message_id = repository.append_multi_character_message(
        session_id,
        "assistant",
        "I am second",
        second_id,
        "Second",
    )
    provider = FakeSpeechProvider()
    monkeypatch.setattr(configs, "speech_storage_path", str(tmp_path))
    service = SpeechService(configs, provider)

    await service.message_audio(
        session_id=session_id,
        message_id=message_id,
        current_user_id=owner,
        mode="group",
    )

    assert provider.syntheses[0][1]["voice"] == "sage"


@pytest.mark.asyncio
async def test_custom_voice_workflow_persists_aliases_and_unbinds_locally(monkeypatch, tmp_path):
    owner = f"speech_{uuid.uuid4().hex[:8]}"
    character_id = f"voice_{uuid.uuid4().hex[:8]}"
    _save_card(owner, _character_card(character_id, voice="cedar"))
    provider = FakeSpeechProvider()
    monkeypatch.setattr(configs, "speech_storage_path", str(tmp_path))
    monkeypatch.setattr(configs, "speech_api_key", SecretStr("speech-key"))
    service = SpeechService(configs, provider)

    consent_status = await service.upload_voice_consent(
        owner_user_id=owner,
        character_id=character_id,
        locale="zh-CN",
        audio=_wav_bytes(),
        filename="consent.wav",
        mime_type="audio/wav",
    )
    assert consent_status["consent_id"] == "cons_1234"
    ready_status = await service.create_custom_voice(
        owner_user_id=owner,
        character_id=character_id,
        audio=_wav_bytes(),
        filename="sample.wav",
        mime_type="audio/wav",
    )
    assert ready_status["custom_voice_status"] == "ready"
    assert ready_status["custom_voice_id"] == "voice_1234"

    stored = json.loads(repository.get_character_card_from_db(owner, character_id)["card_data"])
    assert stored["voice"]["customVoiceId"] == "voice_1234"
    assert stored["voice"]["customVoiceStatus"] == "ready"
    assert "custom_voice_id" not in stored["voice"]

    unbound = service.unbind_custom_voice(owner, character_id)
    assert unbound["custom_voice_status"] == "unconfigured"
    assert unbound["custom_voice_id"] is None
    assert len(provider.voices) == 1


@pytest.mark.asyncio
async def test_custom_voice_success_preserves_concurrent_character_edits(monkeypatch, tmp_path):
    class BlockingProvider(FakeSpeechProvider):
        def __init__(self):
            super().__init__()
            self.started = asyncio.Event()
            self.release = asyncio.Event()

        async def create_custom_voice(self, audio_sample, **kwargs):
            self.voices.append((audio_sample, kwargs))
            self.started.set()
            await self.release.wait()
            return {"id": "voice_reconfigured"}

    owner = f"speech_{uuid.uuid4().hex[:8]}"
    character_id = f"voice_{uuid.uuid4().hex[:8]}"
    _save_card(owner, _character_card(character_id, voice="alloy"))
    provider = BlockingProvider()
    monkeypatch.setattr(configs, "speech_storage_path", str(tmp_path))
    service = SpeechService(configs, provider)
    await service.upload_voice_consent(
        owner_user_id=owner,
        character_id=character_id,
        locale="en-US",
        audio=_wav_bytes(),
        filename="consent.wav",
        mime_type="audio/wav",
    )

    create_task = asyncio.create_task(
        service.create_custom_voice(
            owner_user_id=owner,
            character_id=character_id,
            audio=_wav_bytes(),
            filename="sample.wav",
            mime_type="audio/wav",
        )
    )
    await provider.started.wait()
    concurrent_card = CharacterCard.model_validate(
        json.loads(repository.get_character_card_from_db(owner, character_id)["card_data"])
    )
    concurrent_card.meta.name = "concurrent-name"
    concurrent_card.meta.display_name = "Concurrent Name"
    concurrent_card.voice.builtin_voice = "sage"
    concurrent_card.voice.tts_instructions = "Keep this concurrent edit."
    _save_card(owner, concurrent_card)
    provider.release.set()

    status = await create_task
    stored = CharacterCard.model_validate(
        json.loads(repository.get_character_card_from_db(owner, character_id)["card_data"])
    )
    assert status["custom_voice_id"] == "voice_reconfigured"
    assert stored.meta.name == "concurrent-name"
    assert stored.meta.display_name == "Concurrent Name"
    assert stored.voice.builtin_voice == "sage"
    assert stored.voice.tts_instructions == "Keep this concurrent edit."
    assert stored.voice.custom_voice_id == "voice_reconfigured"
    assert stored.voice.custom_voice_status == "ready"


@pytest.mark.asyncio
async def test_custom_voice_reconfiguration_failure_preserves_ready_voice(monkeypatch, tmp_path):
    class FailingVoiceProvider(FakeSpeechProvider):
        async def create_custom_voice(self, audio_sample, **kwargs):
            raise SpeechProviderError("provider_failure", "temporary failure", 502)

    owner = f"speech_{uuid.uuid4().hex[:8]}"
    character_id = f"voice_{uuid.uuid4().hex[:8]}"
    card = _character_card(character_id, voice="marin")
    card.voice.custom_voice_status = "ready"
    card.voice.custom_voice_id = "voice_existing"
    _save_card(owner, card)
    monkeypatch.setattr(configs, "speech_storage_path", str(tmp_path))
    service = SpeechService(configs, FailingVoiceProvider())
    await service.upload_voice_consent(
        owner_user_id=owner,
        character_id=character_id,
        locale="zh-CN",
        audio=_wav_bytes(),
        filename="consent.wav",
        mime_type="audio/wav",
    )

    with pytest.raises(SpeechServiceError, match="temporary failure"):
        await service.create_custom_voice(
            owner_user_id=owner,
            character_id=character_id,
            audio=_wav_bytes(),
            filename="sample.wav",
            mime_type="audio/wav",
        )

    status = service.voice_status(owner, character_id)
    assert status["custom_voice_status"] == "ready"
    assert status["custom_voice_id"] == "voice_existing"
    assert status["error_category"] == "provider_failure"
    assert status["error"] == "temporary failure"


@pytest.mark.asyncio
async def test_custom_voice_unavailable_persists_fallback_status(monkeypatch, tmp_path):
    class UnavailableProvider(FakeSpeechProvider):
        async def create_voice_consent(self, recording, **kwargs):
            raise SpeechProviderError("unavailable", "Not eligible", 503)

    owner = f"speech_{uuid.uuid4().hex[:8]}"
    character_id = f"voice_{uuid.uuid4().hex[:8]}"
    _save_card(owner, _character_card(character_id, voice="marin"))
    monkeypatch.setattr(configs, "speech_storage_path", str(tmp_path))
    service = SpeechService(configs, UnavailableProvider())

    with pytest.raises(SpeechServiceError) as exc_info:
        await service.upload_voice_consent(
            owner_user_id=owner,
            character_id=character_id,
            locale="en-US",
            audio=_wav_bytes(),
            filename="consent.wav",
            mime_type="audio/wav",
        )

    assert exc_info.value.category == "unavailable"
    stored = CharacterCard.model_validate(
        json.loads(repository.get_character_card_from_db(owner, character_id)["card_data"])
    )
    assert stored.voice.custom_voice_status == "unavailable"
    assert stored.voice.builtin_voice == "marin"


@pytest.mark.asyncio
async def test_custom_voice_missing_provider_ids_persist_failed_workflow(monkeypatch, tmp_path):
    class MissingConsentIdProvider(FakeSpeechProvider):
        async def create_voice_consent(self, recording, **kwargs):
            self.consents.append((recording, kwargs))
            return {}

    class MissingVoiceIdProvider(FakeSpeechProvider):
        async def create_custom_voice(self, audio_sample, **kwargs):
            self.voices.append((audio_sample, kwargs))
            return {}

    owner = f"speech_{uuid.uuid4().hex[:8]}"
    consent_character_id = f"consent_{uuid.uuid4().hex[:8]}"
    voice_character_id = f"voice_{uuid.uuid4().hex[:8]}"
    _save_card(owner, _character_card(consent_character_id))
    _save_card(owner, _character_card(voice_character_id))
    monkeypatch.setattr(configs, "speech_storage_path", str(tmp_path))

    consent_service = SpeechService(configs, MissingConsentIdProvider())
    with pytest.raises(SpeechServiceError, match="consent ID") as consent_error:
        await consent_service.upload_voice_consent(
            owner_user_id=owner,
            character_id=consent_character_id,
            locale="en-US",
            audio=_wav_bytes(),
            filename="consent.wav",
            mime_type="audio/wav",
        )
    assert consent_error.value.category == "provider_failure"
    consent_status = consent_service.voice_status(owner, consent_character_id)
    assert consent_status["custom_voice_status"] == "failed"
    assert consent_status["error_category"] == "provider_failure"
    assert consent_status["consent_id"] is None

    voice_service = SpeechService(configs, MissingVoiceIdProvider())
    await voice_service.upload_voice_consent(
        owner_user_id=owner,
        character_id=voice_character_id,
        locale="zh-CN",
        audio=_wav_bytes(),
        filename="consent.wav",
        mime_type="audio/wav",
    )
    with pytest.raises(SpeechServiceError, match="voice ID") as voice_error:
        await voice_service.create_custom_voice(
            owner_user_id=owner,
            character_id=voice_character_id,
            audio=_wav_bytes(),
            filename="sample.wav",
            mime_type="audio/wav",
        )
    assert voice_error.value.category == "provider_failure"
    voice_status = voice_service.voice_status(owner, voice_character_id)
    assert voice_status["custom_voice_status"] == "failed"
    assert voice_status["error_category"] == "provider_failure"
    assert voice_status["consent_id"] == "cons_1234"


def test_repository_get_short_term_message_is_scoped_to_session():
    first_session = str(uuid.uuid4())
    second_session = str(uuid.uuid4())
    repository.create_session(first_session, "char", "owner", "Player")
    repository.create_session(second_session, "char", "owner", "Player")
    message_id = repository.append_short_term_message(first_session, "assistant", "hello")

    assert repository.get_short_term_message(first_session, message_id)["content"] == "hello"
    assert repository.get_short_term_message(second_session, message_id) is None
