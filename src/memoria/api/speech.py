"""Authenticated speech transcription, synthesis, and Custom Voice routes."""

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse

from memoria.api.upload_utils import read_upload_limited
from memoria.api.user import require_current_user_id
from memoria.core.config import configs
from memoria.core.locale import Locale
from memoria.core.speech_service import (
    SpeechMode,
    SpeechServiceError,
    speech_service,
)


router = APIRouter(dependencies=[Depends(require_current_user_id)])

SPEECH_MEDIA_TYPES = {
    "mp3": "audio/mpeg",
    "opus": "audio/ogg",
    "aac": "audio/aac",
    "flac": "audio/flac",
    "wav": "audio/wav",
    "pcm": "audio/pcm",
}


def _raise_service_error(exc: SpeechServiceError) -> None:
    raise HTTPException(
        status_code=exc.status_code,
        detail={"category": exc.category, "message": exc.detail},
    ) from exc


@router.post("/speech/transcriptions")
async def create_transcription(
    session_id: Annotated[str, Form(...)],
    mode: Annotated[SpeechMode, Form(...)],
    file: Annotated[UploadFile, File(...)],
    current_user_id: str = Depends(require_current_user_id),
):
    audio = await read_upload_limited(
        file,
        configs.speech_stt_upload_max_bytes,
        detail="语音文件超过上传大小限制",
    )
    try:
        return await speech_service.transcribe(
            session_id=session_id,
            current_user_id=current_user_id,
            mode=mode,
            audio=audio,
            filename=file.filename or "recording.webm",
            mime_type=file.content_type or "application/octet-stream",
        )
    except SpeechServiceError as exc:
        _raise_service_error(exc)


async def _message_audio(
    *,
    mode: SpeechMode,
    session_id: str,
    message_id: int,
    current_user_id: str,
) -> FileResponse | StreamingResponse:
    try:
        audio = speech_service.prepare_message_audio(
            session_id=session_id,
            message_id=message_id,
            current_user_id=current_user_id,
            mode=mode,
        )
    except SpeechServiceError as exc:
        _raise_service_error(exc)
    output_format = speech_service.settings.speech_output_format
    cache_hit = audio.cache_hit
    headers = {
        "Cache-Control": "private, max-age=86400",
        "ETag": f'"{audio.cache_key}"',
        "X-Speech-Cache": "HIT" if cache_hit else "MISS",
        "X-AI-Generated-Audio": "true",
    }
    if not cache_hit:
        return StreamingResponse(
            speech_service.stream_message_audio(audio),
            media_type=SPEECH_MEDIA_TYPES[output_format],
            headers={
                **headers,
                "X-Accel-Buffering": "no",
            },
        )
    return FileResponse(
        audio.path,
        media_type=SPEECH_MEDIA_TYPES[output_format],
        filename=f"message-{message_id}.{output_format}",
        headers=headers,
    )


@router.get("/speech/single/sessions/{session_id}/messages/{message_id}/audio")
async def single_message_audio(
    session_id: str,
    message_id: int,
    current_user_id: str = Depends(require_current_user_id),
):
    return await _message_audio(
        mode="single",
        session_id=session_id,
        message_id=message_id,
        current_user_id=current_user_id,
    )


@router.get("/speech/group/sessions/{session_id}/messages/{message_id}/audio")
async def group_message_audio(
    session_id: str,
    message_id: int,
    current_user_id: str = Depends(require_current_user_id),
):
    return await _message_audio(
        mode="group",
        session_id=session_id,
        message_id=message_id,
        current_user_id=current_user_id,
    )


@router.get("/speech/configuration")
def get_speech_configuration():
    return speech_service.provider_configuration()


@router.get("/admin/characters/{character_id}/voice")
def get_character_voice_status(
    character_id: str,
    current_user_id: str = Depends(require_current_user_id),
):
    try:
        return speech_service.voice_status(current_user_id, character_id)
    except SpeechServiceError as exc:
        _raise_service_error(exc)


@router.post("/admin/characters/{character_id}/voice/consent")
async def upload_character_voice_consent(
    character_id: str,
    locale: Annotated[Locale, Form(...)],
    recording: Annotated[UploadFile, File(...)],
    name: Annotated[str | None, Form()] = None,
    current_user_id: str = Depends(require_current_user_id),
):
    audio = await read_upload_limited(
        recording,
        configs.speech_custom_voice_upload_max_bytes,
        detail="声音授权录音超过上传大小限制",
    )
    try:
        return await speech_service.upload_voice_consent(
            owner_user_id=current_user_id,
            character_id=character_id,
            locale=locale,
            audio=audio,
            filename=recording.filename or "consent.webm",
            mime_type=recording.content_type or "application/octet-stream",
            name=name,
        )
    except SpeechServiceError as exc:
        _raise_service_error(exc)


@router.post("/admin/characters/{character_id}/voice")
async def create_character_custom_voice(
    character_id: str,
    audio_sample: Annotated[UploadFile, File(...)],
    reference_transcript: Annotated[str, Form(...)],
    name: Annotated[str | None, Form()] = None,
    current_user_id: str = Depends(require_current_user_id),
):
    audio = await read_upload_limited(
        audio_sample,
        configs.speech_custom_voice_upload_max_bytes,
        detail="自定义声音样本超过上传大小限制",
    )
    try:
        return await speech_service.create_custom_voice(
            owner_user_id=current_user_id,
            character_id=character_id,
            audio=audio,
            filename=audio_sample.filename or "sample.webm",
            mime_type=audio_sample.content_type or "application/octet-stream",
            reference_transcript=reference_transcript,
            name=name,
        )
    except SpeechServiceError as exc:
        _raise_service_error(exc)


@router.delete("/admin/characters/{character_id}/voice")
def unbind_character_custom_voice(
    character_id: str,
    current_user_id: str = Depends(require_current_user_id),
):
    try:
        return speech_service.unbind_custom_voice(current_user_id, character_id)
    except SpeechServiceError as exc:
        _raise_service_error(exc)
