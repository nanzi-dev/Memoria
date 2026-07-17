"""Speech authorization, caching, and character voice workflow services."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import secrets
import time
import wave
from io import BytesIO
from typing import Any, AsyncIterator, Literal

from memoria.core import character_loader
from memoria.core.character_schema import CharacterCard
from memoria.core.config import Configs, configs
from memoria.core.locale import Locale
from memoria.core.speech_provider import (
    CONSENT_PHRASES,
    SpeechSynthesisProvider,
    SpeechProviderError,
    TranscriptionProvider,
    create_stt_provider,
    create_tts_provider,
    speech_provider_configuration,
    tts_provider_settings,
)
from memoria.db import repository


logger = logging.getLogger(__name__)

SpeechMode = Literal["single", "group"]

STT_EXTENSIONS = {".mp3", ".mp4", ".mpeg", ".mpga", ".m4a", ".wav", ".webm"}
STT_MIME_TYPES = {
    "audio/mpeg",
    "audio/mp4",
    "video/mp4",
    "audio/m4a",
    "audio/x-m4a",
    "audio/wav",
    "audio/x-wav",
    "audio/webm",
    "video/webm",
}
CUSTOM_VOICE_MIME_TYPES = {
    "audio/mpeg",
    "audio/m4a",
    "audio/x-m4a",
    "audio/wav",
    "audio/x-wav",
}
STAGE_DIRECTION_PATTERNS = (
    re.compile(r"\[[^\[\]]*]"),
    re.compile(r"【[^【】]*】"),
    re.compile(r"（[^（）]*）"),
    re.compile(r"\([^()]*\)"),
)


@dataclass(slots=True)
class SpeechServiceError(Exception):
    status_code: int
    detail: str
    category: str = "invalid_request"

    def __str__(self) -> str:
        return self.detail


@dataclass(slots=True)
class SpeechAudio:
    path: Path
    cache_key: str
    cache_hit: bool


@dataclass(slots=True)
class SpeechSynthesisRequest:
    cache_path: Path
    cache_key: str
    text: str
    voice: str
    instructions: str
    cache_hit: bool = False


@dataclass(slots=True)
class _CacheLockEntry:
    lock: asyncio.Lock
    users: int = 0


class SpeechService:
    def __init__(
        self,
        settings: Configs = configs,
        provider: Any | None = None,
        *,
        tts_provider: SpeechSynthesisProvider | None = None,
        stt_provider: TranscriptionProvider | None = None,
    ) -> None:
        self.settings = settings
        # `provider` remains an injection shortcut for existing callers/tests.
        self.tts_provider = tts_provider or provider or create_tts_provider(settings)
        self.stt_provider = stt_provider or provider or create_stt_provider(settings)
        self._cache_locks: dict[str, _CacheLockEntry] = {}

    @asynccontextmanager
    async def _cache_lock(self, cache_key: str) -> AsyncIterator[None]:
        entry = self._cache_locks.get(cache_key)
        if entry is None:
            entry = _CacheLockEntry(asyncio.Lock())
            self._cache_locks[cache_key] = entry
        entry.users += 1
        acquired = False
        try:
            await entry.lock.acquire()
            acquired = True
            yield
        finally:
            if acquired:
                entry.lock.release()
            entry.users -= 1
            if entry.users == 0 and self._cache_locks.get(cache_key) is entry:
                self._cache_locks.pop(cache_key, None)

    def _require_session(
        self,
        session_id: str,
        current_user_id: str,
        mode: SpeechMode,
    ) -> dict:
        session = repository.get_session(session_id)
        if not session:
            raise SpeechServiceError(404, "Session not found")
        if session.get("player_id") != current_user_id:
            raise SpeechServiceError(403, "You do not have access to this session")
        is_group = bool(session.get("is_multi_character"))
        if is_group != (mode == "group"):
            raise SpeechServiceError(400, "Speech mode does not match the session")
        return session

    @staticmethod
    def _provider_error(exc: SpeechProviderError) -> SpeechServiceError:
        return SpeechServiceError(exc.status_code, exc.message, exc.category)

    @staticmethod
    def _spoken_text(content: str) -> str:
        """Remove bracketed stage directions before speech synthesis."""
        text = content.strip()
        previous = None
        while text != previous:
            previous = text
            for pattern in STAGE_DIRECTION_PATTERNS:
                text = pattern.sub(" ", text)
        return re.sub(r"\s+", " ", text).strip()

    async def transcribe(
        self,
        *,
        session_id: str,
        current_user_id: str,
        mode: SpeechMode,
        audio: bytes,
        filename: str,
        mime_type: str,
    ) -> dict:
        session = self._require_session(session_id, current_user_id, mode)
        self.validate_stt_upload(audio, filename, mime_type)
        locale = session.get("locale") or "zh-CN"
        try:
            text = await self.stt_provider.transcribe(
                audio,
                filename=filename,
                mime_type=mime_type,
                locale=locale,
            )
        except SpeechProviderError as exc:
            raise self._provider_error(exc) from exc
        if not text:
            raise SpeechServiceError(502, "Speech provider returned an empty transcription", "provider_failure")
        return {"text": text, "locale": locale}

    def validate_stt_upload(self, audio: bytes, filename: str, mime_type: str) -> None:
        if not audio:
            raise SpeechServiceError(400, "Audio recording is empty")
        if len(audio) > self.settings.speech_stt_upload_max_bytes:
            raise SpeechServiceError(413, "Audio recording exceeds the 25 MB limit")
        suffix = Path(filename or "").suffix.lower()
        normalized_mime = (mime_type or "").split(";", 1)[0].strip().lower()
        if suffix not in STT_EXTENSIONS or normalized_mime not in STT_MIME_TYPES:
            raise SpeechServiceError(415, "Unsupported transcription audio format")

    def prepare_message_audio(
        self,
        *,
        session_id: str,
        message_id: int,
        current_user_id: str,
        mode: SpeechMode,
    ) -> SpeechAudio | SpeechSynthesisRequest:
        session = self._require_session(session_id, current_user_id, mode)
        message = repository.get_short_term_message(session_id, message_id)
        if not message:
            raise SpeechServiceError(404, "Message not found")
        if message.get("role") != "assistant":
            raise SpeechServiceError(400, "Only assistant messages can be synthesized")

        character_id = (
            message.get("character_id") if mode == "group" else session.get("character_id")
        )
        if not character_id:
            raise SpeechServiceError(400, "Assistant message has no speaking character")
        card = self._load_character(current_user_id, character_id)
        if card.voice.custom_voice_status == "ready" and card.voice.custom_voice_id:
            voice = card.voice.custom_voice_id
        else:
            voice = card.voice.builtin_voice

        text = self._spoken_text(str(message.get("content") or ""))
        if not text:
            raise SpeechServiceError(400, "Assistant message has no spoken dialogue")
        cache_key = self._cache_key(
            mode=mode,
            message_id=message_id,
            text=text,
            voice=voice,
            instructions=card.voice.tts_instructions,
        )
        cache_path = self._cache_dir() / f"{cache_key}.{self.settings.speech_output_format}"
        if cache_path.is_file() and cache_path.stat().st_size > 0:
            os.utime(cache_path, None)
            self._log_audio_request(cache_hit=True, cache_key=cache_key, started_at=None)
            return SpeechAudio(cache_path, cache_key, True)
        return SpeechSynthesisRequest(
            cache_path=cache_path,
            cache_key=cache_key,
            text=text,
            voice=voice,
            instructions=card.voice.tts_instructions,
        )

    async def stream_message_audio(
        self,
        request: SpeechSynthesisRequest,
    ) -> AsyncIterator[bytes]:
        """Stream a cache miss while atomically materializing its replay cache."""
        started_at = time.perf_counter()
        temp_path = request.cache_path.with_suffix(
            f"{request.cache_path.suffix}.{secrets.token_hex(8)}.tmp"
        )
        first_chunk_at: float | None = None
        bytes_written = 0
        completed = False
        async with self._cache_lock(request.cache_key):
            if request.cache_path.is_file() and request.cache_path.stat().st_size > 0:
                os.utime(request.cache_path, None)
                request.cache_hit = True
                self._log_audio_request(
                    cache_hit=True,
                    cache_key=request.cache_key,
                    started_at=started_at,
                )
                for chunk in _read_chunks(request.cache_path):
                    yield chunk
                return

            request.cache_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                stream = self._synthesis_stream(
                    request.text,
                    voice=request.voice,
                    instructions=request.instructions,
                )
                with temp_path.open("wb") as output:
                    async for chunk in stream:
                        if not chunk:
                            continue
                        if first_chunk_at is None:
                            first_chunk_at = time.perf_counter()
                        output.write(chunk)
                        output.flush()
                        bytes_written += len(chunk)
                        yield chunk
                if not bytes_written:
                    raise SpeechServiceError(
                        502,
                        "Speech provider returned empty audio",
                        "provider_failure",
                    )
                temp_path.replace(request.cache_path)
                completed = True
                self.cleanup_cache()
            finally:
                if not completed:
                    temp_path.unlink(missing_ok=True)
                self._log_audio_request(
                    cache_hit=False,
                    cache_key=request.cache_key,
                    started_at=started_at,
                    first_chunk_at=first_chunk_at,
                    completed=completed,
                )

    async def message_audio(
        self,
        *,
        session_id: str,
        message_id: int,
        current_user_id: str,
        mode: SpeechMode,
    ) -> SpeechAudio:
        prepared = self.prepare_message_audio(
            session_id=session_id,
            message_id=message_id,
            current_user_id=current_user_id,
            mode=mode,
        )
        if isinstance(prepared, SpeechAudio):
            return prepared
        async for _ in self.stream_message_audio(prepared):
            pass
        return SpeechAudio(
            prepared.cache_path,
            prepared.cache_key,
            prepared.cache_hit,
        )

    async def _synthesis_stream(
        self,
        text: str,
        *,
        voice: str,
        instructions: str,
    ) -> AsyncIterator[bytes]:
        try:
            synthesize_stream = getattr(self.tts_provider, "synthesize_stream", None)
            if synthesize_stream is not None:
                async for chunk in synthesize_stream(
                    text,
                    voice=voice,
                    instructions=instructions,
                ):
                    yield chunk
                return
            # Compatibility for existing injected providers that only implement
            # the prior buffered `synthesize` method.
            synthesize = getattr(self.tts_provider, "synthesize", None)
            if synthesize is None:
                raise SpeechProviderError(
                    "provider_failure",
                    "TTS provider does not implement synthesis",
                    502,
                )
            audio = await synthesize(text, voice=voice, instructions=instructions)
            if audio:
                yield audio
        except SpeechProviderError as exc:
            raise self._provider_error(exc) from exc

    def _log_audio_request(
        self,
        *,
        cache_hit: bool,
        cache_key: str,
        started_at: float | None,
        first_chunk_at: float | None = None,
        completed: bool = True,
    ) -> None:
        now = time.perf_counter()
        connection = tts_provider_settings(self.settings)
        logger.info(
            "Speech audio request",
            extra={
                "speech_provider": connection.provider,
                "speech_model": connection.model,
                "speech_cache_hit": cache_hit,
                "speech_cache_key_prefix": cache_key[:12],
                "speech_completed": completed,
                "speech_total_ms": (
                    round((now - started_at) * 1000) if started_at is not None else 0
                ),
                "speech_first_chunk_ms": (
                    round((first_chunk_at - started_at) * 1000)
                    if first_chunk_at is not None and started_at is not None
                    else None
                ),
            },
        )

    def _load_character(self, owner_user_id: str, character_id: str) -> CharacterCard:
        db_card = repository.get_character_card_from_db(
            owner_user_id,
            character_id,
            include_inactive=True,
        )
        if not db_card:
            raise SpeechServiceError(404, "Speaking character not found")
        try:
            raw = character_loader.normalize_character_data(json.loads(db_card["card_data"]))
            return CharacterCard.model_validate(raw)
        except (KeyError, TypeError, ValueError) as exc:
            raise SpeechServiceError(500, "Speaking character card is invalid") from exc

    def _cache_dir(self) -> Path:
        return Path(self.settings.speech_storage_path) / "cache"

    def _cache_key(
        self,
        *,
        mode: SpeechMode,
        message_id: int,
        text: str,
        voice: str,
        instructions: str,
    ) -> str:
        payload = {
            "mode": mode,
            "message_id": message_id,
            "text_hash": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "provider": tts_provider_settings(self.settings).provider,
            "provider_contract_version": 3,
            "model": self.settings.speech_tts_model,
            "voice": voice,
            "instructions": instructions,
            "format": self.settings.speech_output_format,
        }
        encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def cleanup_cache(self) -> None:
        cache_dir = self._cache_dir()
        if not cache_dir.exists():
            return
        now = datetime.now(timezone.utc).timestamp()
        files = [path for path in cache_dir.iterdir() if path.is_file() and not path.name.endswith(".tmp")]
        max_age = self.settings.speech_cache_max_age_seconds
        if max_age > 0:
            for path in files:
                try:
                    if now - path.stat().st_mtime > max_age:
                        path.unlink(missing_ok=True)
                except OSError:
                    continue
        files = [path for path in files if path.exists()]
        total = sum(path.stat().st_size for path in files)
        max_bytes = self.settings.speech_cache_max_bytes
        if max_bytes <= 0:
            return
        for path in sorted(files, key=lambda item: item.stat().st_mtime):
            if total <= max_bytes:
                break
            try:
                size = path.stat().st_size
                path.unlink()
                total -= size
            except OSError:
                continue

    def validate_custom_voice_upload(self, audio: bytes, mime_type: str) -> None:
        if not audio:
            raise SpeechServiceError(400, "Voice recording is empty")
        if len(audio) > self.settings.speech_custom_voice_upload_max_bytes:
            raise SpeechServiceError(413, "Voice recording exceeds the 10 MiB limit")
        normalized_mime = (mime_type or "").split(";", 1)[0].strip().lower()
        if normalized_mime not in CUSTOM_VOICE_MIME_TYPES:
            raise SpeechServiceError(415, "Unsupported Custom Voice audio format")
        if normalized_mime in {"audio/wav", "audio/x-wav"}:
            try:
                with wave.open(BytesIO(audio), "rb") as recording:
                    duration = recording.getnframes() / max(1, recording.getframerate())
            except (wave.Error, EOFError):
                raise SpeechServiceError(400, "Invalid WAV recording")
            if duration > 30.0:
                raise SpeechServiceError(400, "Voice recordings must be 30 seconds or less")

    async def upload_voice_consent(
        self,
        *,
        owner_user_id: str,
        character_id: str,
        locale: Locale,
        audio: bytes,
        filename: str,
        mime_type: str,
        reference_transcript: str = "",
        name: str | None = None,
    ) -> dict:
        card, _ = self._owned_character(owner_user_id, character_id)
        self.validate_custom_voice_upload(audio, mime_type)
        workflow = self._read_workflow(owner_user_id, character_id)
        consent_path = self._save_workflow_audio(
            owner_user_id,
            character_id,
            "consent",
            filename,
            audio,
        )
        preserve_ready_voice = (
            card.voice.custom_voice_status == "ready"
            and bool(card.voice.custom_voice_id)
        )
        if not preserve_ready_voice:
            self._patch_character_voice(
                owner_user_id,
                character_id,
                customVoiceStatus="pending",
                customVoiceId=None,
            )
        workflow.update(
            status="pending",
            consent_id=secrets.token_urlsafe(18),
            consent_filename=consent_path.name,
            consent_locale=locale,
            consent_phrase=CONSENT_PHRASES[locale],
            error=None,
            error_category=None,
        )
        self._write_workflow(owner_user_id, character_id, workflow)
        return self.voice_status(owner_user_id, character_id)

    async def create_custom_voice(
        self,
        *,
        owner_user_id: str,
        character_id: str,
        audio: bytes,
        filename: str,
        mime_type: str,
        reference_transcript: str = "",
        name: str | None = None,
    ) -> dict:
        card, _ = self._owned_character(owner_user_id, character_id)
        self.validate_custom_voice_upload(audio, mime_type)
        reference_transcript = reference_transcript.strip()
        if not reference_transcript:
            raise SpeechServiceError(400, "Reference audio transcript is required")
        workflow = self._read_workflow(owner_user_id, character_id)
        consent_filename = str(workflow.get("consent_filename") or "")
        consent_path = self._workflow_dir(owner_user_id, character_id) / consent_filename
        if not workflow.get("consent_id") or not consent_filename or not consent_path.is_file():
            raise SpeechServiceError(400, "Upload a valid consent recording first")
        sample_path = self._save_workflow_audio(
            owner_user_id,
            character_id,
            "sample",
            filename,
            audio,
        )
        preserve_ready_voice = (
            card.voice.custom_voice_status == "ready"
            and bool(card.voice.custom_voice_id)
        )
        if not preserve_ready_voice:
            self._patch_character_voice(
                owner_user_id,
                character_id,
                customVoiceStatus="pending",
                customVoiceId=None,
            )
        try:
            create_voice = getattr(self.tts_provider, "create_custom_voice", None)
            if create_voice is None:
                raise SpeechProviderError(
                    "unavailable",
                    "The configured TTS provider does not support Custom Voice",
                    503,
                )
            result = await create_voice(
                authorization_audio=consent_path.read_bytes(),
                authorization_filename=consent_path.name,
                authorization_mime_type=self._mime_type_for_path(consent_path),
                reference_audio=audio,
                reference_filename=sample_path.name,
                reference_mime_type=mime_type,
                reference_transcript=reference_transcript,
                voice_id=self._new_voice_id(character_id),
                name=(name or card.meta.display_name).strip(),
                locale=str(workflow.get("consent_locale") or "zh-CN"),
            )
        except SpeechProviderError as exc:
            status = "unavailable" if exc.category in {"not_configured", "unavailable"} else "failed"
            if not preserve_ready_voice:
                self._patch_character_voice(
                    owner_user_id,
                    character_id,
                    customVoiceStatus=status,
                    customVoiceId=None,
                )
            workflow.update(status=status, error_category=exc.category, error=exc.message)
            self._write_workflow(owner_user_id, character_id, workflow)
            raise self._provider_error(exc) from exc

        voice_id = str(result.get("id") or "").strip()
        if not voice_id:
            error = "Speech provider did not return a voice ID"
            if not preserve_ready_voice:
                self._patch_character_voice(
                    owner_user_id,
                    character_id,
                    customVoiceStatus="failed",
                    customVoiceId=None,
                )
            workflow.update(status="failed", error_category="provider_failure", error=error)
            self._write_workflow(owner_user_id, character_id, workflow)
            raise SpeechServiceError(502, error, "provider_failure")
        self._patch_character_voice(
            owner_user_id,
            character_id,
            customVoiceId=voice_id,
            customVoiceStatus="ready",
        )
        workflow.update(
            status="ready",
            voice_id=voice_id,
            error=None,
            error_category=None,
        )
        self._write_workflow(owner_user_id, character_id, workflow)
        return self.voice_status(owner_user_id, character_id)

    def voice_status(self, owner_user_id: str, character_id: str) -> dict:
        card, _ = self._owned_character(owner_user_id, character_id)
        workflow = self._read_workflow(owner_user_id, character_id)
        configured = bool(tts_provider_settings(self.settings).api_key)
        return {
            "character_id": character_id,
            "speech_configured": configured,
            "custom_voice_status": card.voice.custom_voice_status,
            "custom_voice_id": card.voice.custom_voice_id,
            "builtin_voice": card.voice.builtin_voice,
            "tts_instructions": card.voice.tts_instructions,
            "consent_id": workflow.get("consent_id"),
            "consent_locale": workflow.get("consent_locale"),
            "error_category": workflow.get("error_category"),
            "error": workflow.get("error"),
            "consent_phrases": CONSENT_PHRASES,
        }

    def provider_configuration(self) -> dict:
        return speech_provider_configuration(self.settings)

    def unbind_custom_voice(self, owner_user_id: str, character_id: str) -> dict:
        self._owned_character(owner_user_id, character_id)
        self._patch_character_voice(
            owner_user_id,
            character_id,
            customVoiceId=None,
            customVoiceStatus="unconfigured",
        )
        workflow = self._read_workflow(owner_user_id, character_id)
        workflow.update(
            status="unconfigured",
            error=None,
            error_category=None,
            unbound_at=datetime.now(timezone.utc).isoformat(),
        )
        self._write_workflow(owner_user_id, character_id, workflow)
        return self.voice_status(owner_user_id, character_id)

    def _owned_character(self, owner_user_id: str, character_id: str) -> tuple[CharacterCard, dict]:
        db_card = repository.get_character_card_from_db(
            owner_user_id,
            character_id,
            include_inactive=True,
        )
        if not db_card:
            raise SpeechServiceError(404, "Character not found")
        try:
            card = CharacterCard.model_validate(json.loads(db_card["card_data"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise SpeechServiceError(500, "Character card is invalid") from exc
        return card, db_card

    def _patch_character_voice(
        self,
        owner_user_id: str,
        character_id: str,
        **updates,
    ) -> Path:
        success = repository.patch_character_card_voice(
            owner_user_id,
            character_id,
            updates,
        )
        if not success:
            raise SpeechServiceError(500, "Failed to update character voice settings")
        character_loader.load_character_card.cache_clear()

    def _workflow_dir(self, owner_user_id: str, character_id: str) -> Path:
        digest = hashlib.sha256(f"{owner_user_id}\0{character_id}".encode("utf-8")).hexdigest()
        return Path(self.settings.speech_storage_path) / "workflows" / digest

    def _read_workflow(self, owner_user_id: str, character_id: str) -> dict:
        path = self._workflow_dir(owner_user_id, character_id) / "metadata.json"
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, ValueError):
            return {"owner_user_id": owner_user_id, "character_id": character_id}
        if payload.get("owner_user_id") != owner_user_id or payload.get("character_id") != character_id:
            return {"owner_user_id": owner_user_id, "character_id": character_id}
        return payload

    def _write_workflow(self, owner_user_id: str, character_id: str, payload: dict) -> None:
        directory = self._workflow_dir(owner_user_id, character_id)
        directory.mkdir(parents=True, exist_ok=True)
        payload.update(
            owner_user_id=owner_user_id,
            character_id=character_id,
            updated_at=datetime.now(timezone.utc).isoformat(),
        )
        path = directory / "metadata.json"
        temp_path = directory / "metadata.json.tmp"
        temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temp_path.replace(path)

    def _save_workflow_audio(
        self,
        owner_user_id: str,
        character_id: str,
        kind: str,
        filename: str,
        audio: bytes,
    ) -> Path:
        directory = self._workflow_dir(owner_user_id, character_id)
        directory.mkdir(parents=True, exist_ok=True)
        suffix = Path(filename or "").suffix.lower()
        suffix = suffix if re.fullmatch(r"\.[a-z0-9]{1,8}", suffix) else ".bin"
        path = directory / f"{kind}{suffix}"
        path.write_bytes(audio)
        return path

    @staticmethod
    def _mime_type_for_path(path: Path) -> str:
        return {
            ".aac": "audio/aac",
            ".flac": "audio/flac",
            ".m4a": "audio/m4a",
            ".mp3": "audio/mpeg",
            ".mp4": "audio/mp4",
            ".ogg": "audio/ogg",
            ".wav": "audio/wav",
            ".webm": "audio/webm",
        }.get(path.suffix.lower(), "application/octet-stream")

    @staticmethod
    def _new_voice_id(character_id: str) -> str:
        normalized = re.sub(r"[^a-zA-Z0-9_-]+", "-", character_id).strip("-")
        return f"memoria-{normalized[:24] or 'voice'}-{secrets.token_hex(6)}"


def _read_chunks(path: Path, chunk_size: int = 64 * 1024):
    with path.open("rb") as audio:
        while chunk := audio.read(chunk_size):
            yield chunk


speech_service = SpeechService()
