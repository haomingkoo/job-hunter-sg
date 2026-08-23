"""One bounded boundary for reading and parsing an uploaded resume."""

from __future__ import annotations

import threading
from dataclasses import dataclass

from fastapi import HTTPException, UploadFile
from starlette.concurrency import run_in_threadpool

from resume_parser import MAX_FILE_SIZE, parse_resume_isolated


_RESUME_PARSE_SLOTS = threading.BoundedSemaphore(1)


@dataclass(frozen=True)
class ParsedResumeUpload:
    filename: str
    content_type: str
    file_bytes: bytes
    parsed_resume: dict


async def parse_uploaded_resume(file: UploadFile) -> ParsedResumeUpload:
    """Read, close, capacity-gate, and parse one PDF or DOCX upload."""
    filename = file.filename or "resume"
    content_type = file.content_type or ""
    try:
        file_bytes = await file.read(MAX_FILE_SIZE + 1)
    finally:
        await file.close()
    if len(file_bytes) > MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail="File too large. Maximum is 5MB.")
    if not _RESUME_PARSE_SLOTS.acquire(blocking=False):
        raise HTTPException(
            status_code=503,
            detail="Resume parsing is busy. Please try again shortly.",
            headers={"Retry-After": "2"},
        )
    try:
        try:
            parsed_resume = await run_in_threadpool(
                parse_resume_isolated,
                filename=filename,
                content_type=content_type,
                file_bytes=file_bytes,
            )
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
    finally:
        _RESUME_PARSE_SLOTS.release()
    return ParsedResumeUpload(
        filename=filename,
        content_type=content_type,
        file_bytes=file_bytes,
        parsed_resume=parsed_resume,
    )
