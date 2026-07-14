"""Speech authorization, caching, and character voice workflow services."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import wave
from io import BytesIO
from typing import AsyncIterator, Literal

from memoria.core import character_loader
from memoria.core.character_schema import CharacterCard
from memoria.core.config import Configs, configs
from memoria.core.locale import Locale
from memoria.core.speech_provider import (
    CONSENT_PHRASES,
    OpenAISpeechProvider,
    SpeechProviderError,
)
from memoria.db import repository


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
    "audio/wav",
    "audio/x-wav",
    "audio/ogg",
    "audio/aac",
    "audio/flac",
    "audio/webm",
    "audio/mp4",
    "video/mp4",
}


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
class _CacheLockEntry:
    lock: asyncio.Lock
    users: int = 0


class SpeechService:
    def __init__(
        self,
        settings: Configs = configs,
        provider: OpenAISpeechProvider | None = None,
    ) -> None:
        self.settings = settings
        self.provider = provider or OpenAISpeechProvider(settings)
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
            text = await self.provider.transcribe(
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

    async def message_audio(
        self,
        *,
        session_id: str,
        message_id: int,
        current_user_id: str,
        mode: SpeechMode,
    ) -> SpeechAudio:
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
        voice: str | dict[str, str]
        if card.voice.custom_voice_status == "ready" and card.voice.custom_voice_id:
            voice = {"id": card.voice.custom_voice_id}
        else:
            voice = card.voice.builtin_voice

        text = str(message.get("content") or "").strip()
        if not text:
            raise SpeechServiceError(400, "Assistant message is empty")
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
            return SpeechAudio(cache_path, cache_key, True)

        async with self._cache_lock(cache_key):
            if cache_path.is_file() and cache_path.stat().st_size > 0:
                os.utime(cache_path, None)
                return SpeechAudio(cache_path, cache_key, True)
            try:
                audio = await self.provider.synthesize(
                    text,
                    voice=voice,
                    instructions=card.voice.tts_instructions,
                )
            except SpeechProviderError as exc:
                raise self._provider_error(exc) from exc
            if not audio:
                raise SpeechServiceError(502, "Speech provider returned empty audio", "provider_failure")
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            temp_path = cache_path.with_suffix(f"{cache_path.suffix}.tmp")
            try:
                temp_path.write_bytes(audio)
                temp_path.replace(cache_path)
            finally:
                temp_path.unlink(missing_ok=True)
            self.cleanup_cache()
        return SpeechAudio(cache_path, cache_key, False)

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
        voice: str | dict[str, str],
        instructions: str,
    ) -> str:
        payload = {
            "mode": mode,
            "message_id": message_id,
            "text_hash": hashlib.sha256(text.encode("utf-8")).hexdigest(),
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
        name: str | None = None,
    ) -> dict:
        card, _ = self._owned_character(owner_user_id, character_id)
        self.validate_custom_voice_upload(audio, mime_type)
        workflow = self._read_workflow(owner_user_id, character_id)
        self._save_workflow_audio(owner_user_id, character_id, "consent", filename, audio)
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
            result = await self.provider.create_voice_consent(
                audio,
                filename=filename,
                mime_type=mime_type,
                name=(name or f"{card.meta.display_name} consent").strip(),
                locale=locale,
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

        consent_id = str(result.get("id") or "").strip()
        if not consent_id:
            error = "Speech provider did not return a consent ID"
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

        workflow.update(
            status="pending",
            consent_id=consent_id,
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
        name: str | None = None,
    ) -> dict:
        card, _ = self._owned_character(owner_user_id, character_id)
        self.validate_custom_voice_upload(audio, mime_type)
        workflow = self._read_workflow(owner_user_id, character_id)
        consent_id = workflow.get("consent_id")
        if not consent_id:
            raise SpeechServiceError(400, "Upload a valid consent recording first")
        self._save_workflow_audio(owner_user_id, character_id, "sample", filename, audio)
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
            result = await self.provider.create_custom_voice(
                audio,
                filename=filename,
                mime_type=mime_type,
                name=(name or card.meta.display_name).strip(),
                consent_id=consent_id,
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
        configured = bool(self.settings.speech_api_key.get_secret_value().strip())
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
    ) -> None:
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
    ) -> None:
        directory = self._workflow_dir(owner_user_id, character_id)
        directory.mkdir(parents=True, exist_ok=True)
        suffix = Path(filename or "").suffix.lower()
        suffix = suffix if re.fullmatch(r"\.[a-z0-9]{1,8}", suffix) else ".bin"
        (directory / f"{kind}{suffix}").write_bytes(audio)


speech_service = SpeechService()
