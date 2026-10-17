"""Resource strings and glob patterns (AUTH-011)."""

from __future__ import annotations

import fnmatch
import posixpath

MAX_RESOURCE_LENGTH = 512


def normalise_resource(resource: str) -> str:
    """Return a canonical form of ``resource`` or raise ``ValueError``.

    Rejects empty values, control characters, backslashes and any ``..`` segment, so a
    resource can never be used for traversal. Repeated slashes and a trailing slash are
    collapsed.
    """
    if not isinstance(resource, str):
        raise ValueError("resource must be a string")
    text = resource.strip()
    if not text:
        raise ValueError("resource must not be empty")
    if len(text) > MAX_RESOURCE_LENGTH:
        raise ValueError("resource is too long")
    if "\\" in text or any(ord(ch) < 32 or ord(ch) == 127 for ch in text):
        raise ValueError("resource contains forbidden characters")
    if any(segment == ".." for segment in text.split("/")):
        raise ValueError("resource must not contain '..'")
    normalised = posixpath.normpath(text)
    return normalised.lstrip("/") or "."


def validate_resource_pattern(pattern: str) -> str:
    """Validate a glob pattern used in a scope and return it unchanged."""
    text = pattern.strip()
    if not text:
        raise ValueError("resource pattern must not be empty")
    if len(text) > MAX_RESOURCE_LENGTH:
        raise ValueError("resource pattern is too long")
    if "\\" in text or any(ord(ch) < 32 or ord(ch) == 127 for ch in text):
        raise ValueError("resource pattern contains forbidden characters")
    if any(segment == ".." for segment in text.split("/")):
        raise ValueError("resource pattern must not contain '..'")
    return text


def resource_matches(pattern: str, resource: str) -> bool:
    """True if the normalised ``resource`` matches the case-sensitive glob ``pattern``."""
    try:
        normalised = normalise_resource(resource)
    except ValueError:
        return False
    return fnmatch.fnmatchcase(normalised, pattern)
