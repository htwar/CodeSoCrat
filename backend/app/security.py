from __future__ import annotations

import re


CONTROL_CHARACTERS_PATTERN = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]")
EMAIL_PATTERN = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,255}$")


def reject_control_characters(value: str, field_name: str) -> str:
    if CONTROL_CHARACTERS_PATTERN.search(value):
        raise ValueError(f"{field_name} contains unsupported control characters.")
    return value


def normalize_text(value: str, field_name: str, *, max_length: int, allow_newlines: bool = False) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must not be empty.")
    if len(normalized) > max_length:
        raise ValueError(f"{field_name} must be {max_length} characters or fewer.")
    reject_control_characters(normalized, field_name)
    if not allow_newlines and ("\n" in normalized or "\r" in normalized or "\t" in normalized):
        raise ValueError(f"{field_name} contains unsupported whitespace.")
    return normalized


def normalize_multiline_text(value: str, field_name: str, *, max_length: int) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must not be empty.")
    if len(normalized) > max_length:
        raise ValueError(f"{field_name} must be {max_length} characters or fewer.")
    reject_control_characters(normalized, field_name)
    return normalized


def validate_email(value: str) -> str:
    normalized = normalize_text(value, "email", max_length=255)
    lowered = normalized.lower()
    if not EMAIL_PATTERN.fullmatch(lowered):
        raise ValueError("email must be a valid email address.")
    return lowered
