"""Tests for webhooks/validators.py — no live services needed."""
from __future__ import annotations

import hashlib
import hmac

import pytest

# Patch settings before importing the validator
import os
os.environ.setdefault("DISCORD_TOKEN", "test")
os.environ.setdefault("DISCORD_GUILD_ID", "1")
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-key")
os.environ.setdefault("GITHUB_WEBHOOK_SECRET", "test-secret")
os.environ.setdefault("CHANNEL_TASK_FEED", "1")
os.environ.setdefault("CHANNEL_STANDUP_LOG", "2")
os.environ.setdefault("CHANNEL_GITHUB_FEED", "3")
os.environ.setdefault("CHANNEL_CODE_REVIEW", "4")
os.environ.setdefault("CHANNEL_PHASE_TRACKER", "5")
os.environ.setdefault("CHANNEL_HELP", "6")
os.environ.setdefault("CHANNEL_SHOUTOUTS", "7")
os.environ.setdefault("CHANNEL_ANNOUNCEMENTS", "8")
os.environ.setdefault("CHANNEL_TIP_OF_THE_DAY", "9")
os.environ.setdefault("CHANNEL_RESOURCES", "10")
os.environ.setdefault("CHANNEL_RETRO", "11")
os.environ.setdefault("CHANNEL_RANKINGS", "12")
os.environ.setdefault("CHANNEL_GENERAL", "13")

from app.webhooks.validators import verify_github_signature  # noqa: E402

SECRET = "test-secret"
PAYLOAD = b'{"action": "opened"}'


def _make_sig(payload: bytes, secret: str = SECRET) -> str:
    digest = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def test_valid_signature_returns_true():
    sig = _make_sig(PAYLOAD)
    assert verify_github_signature(PAYLOAD, sig) is True


def test_tampered_payload_returns_false():
    sig = _make_sig(PAYLOAD)
    tampered = b'{"action": "closed"}'
    assert verify_github_signature(tampered, sig) is False


def test_wrong_secret_returns_false():
    sig = _make_sig(PAYLOAD, secret="wrong-secret")
    assert verify_github_signature(PAYLOAD, sig) is False


def test_missing_header_returns_false():
    assert verify_github_signature(PAYLOAD, None) is False


def test_malformed_header_returns_false():
    assert verify_github_signature(PAYLOAD, "md5=abc123") is False


def test_empty_header_returns_false():
    assert verify_github_signature(PAYLOAD, "") is False
