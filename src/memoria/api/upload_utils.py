"""Helpers for bounded multipart uploads."""

from fastapi import HTTPException, UploadFile


async def read_upload_limited(
    upload: UploadFile,
    max_bytes: int,
    *,
    detail: str,
) -> bytes:
    """Read at most one byte beyond the limit so oversized uploads fail early."""
    data = await upload.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise HTTPException(status_code=413, detail=detail)
    return data
