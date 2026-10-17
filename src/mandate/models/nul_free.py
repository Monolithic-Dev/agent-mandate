"""Models that refuse NUL characters anywhere in their input.

The graph database cannot store a NUL inside a string parameter and fails the whole query.
Turning that into a clean validation error at the edge means hostile text can never reach
the database as an unexplained failure.

(The module is not called ``nul``: that is a reserved device name on Windows.)
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, model_validator


def contains_nul(value: Any) -> bool:
    if isinstance(value, str):
        return "\x00" in value
    if isinstance(value, dict):
        return any(contains_nul(k) or contains_nul(v) for k, v in value.items())
    if isinstance(value, list | tuple | set | frozenset):
        return any(contains_nul(item) for item in value)
    return False


class NulFreeModel(BaseModel):
    @model_validator(mode="before")
    @classmethod
    def _no_nul(cls, data: Any) -> Any:
        if contains_nul(data):
            raise ValueError("text may not contain NUL characters")
        return data
