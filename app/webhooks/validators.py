from __future__ import annotations

import hashlib
import hmac

from fastapi import HTTPException

from app.config import settings


def verify_github_signature(payload: bytes, sig_header: str | None) -> bool:
    if not sig_header or not sig_header.startswith("sha256="):
        return False

    expected = "sha256=" + hmac.new(
        settings.GITHUB_WEBHOOK_SECRET.encode(),
        payload,
        hashlib.sha256
    ).hexdigest()

    return hmac.compare_digest(expected, sig_header)


def require_valid_github_signature(payload: bytes, sig_header: str | None) -> None:
    if not verify_github_signature(payload, sig_header):
        raise HTTPException(status_code=403, detail="Invalid or missing GitHub webhook signature")