"""Utterance trust (AUTH-002)."""

from __future__ import annotations

from mandate.models.domain import Channel, Role, Trust


def compute_trust(channel: Channel, speaker_role: Role) -> Trust:
    """Trust is ``trusted`` only for an owner speaking directly.

    The server computes this; a client-supplied value is never used.
    """
    if channel is Channel.OWNER_DIRECT and speaker_role is Role.OWNER:
        return Trust.TRUSTED
    return Trust.UNTRUSTED
