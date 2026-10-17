"""Deterministic parser from owner sentences to candidate rules (docs/ai-pipeline.md section 4).

The parser never guesses: text that does not match a known pattern yields no rule, and a
clause it can only half read (an amount it cannot read exactly, a time limit it does not
understand) yields no rule either, rather than a rule broader or longer-lived than the owner
meant. Its output is a *candidate*; activation always needs the owner's confirmation for
high-impact actions.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from mandate.models.domain import Constraints, Effect
from mandate.models.registry import HIGH_IMPACT

# Ways of granting, refusing and asking first. Kept as data so the docs can list them.
ALLOW_LEADS = (
    r"you may",
    r"you can",
    r"you(?:'re| are) allowed to",
    r"feel free to",
)
DENY_LEADS = (
    r"never",
    r"do not",
    r"don't",
    r"must not",
    r"mustn't",
    r"you may not",
    r"you can't",
    r"you cannot",
    r"you(?:'re| are) not allowed to",
)

_ALLOW_LEAD = rf"\b(?:{'|'.join(ALLOW_LEADS)})\s+"
_DENY_LEAD = rf"\b(?:{'|'.join(DENY_LEADS)})\s+(?:ever\s+)?"

# Clause boundaries: sentence ends, "but", and "and" when followed by a directive.
_DIRECTIVE = (
    r"(?:please\s+)?(?:confirm|check\s+with\s+me|ask\s+me|never|do not|don't|must not|"
    r"stop|you may|you can|feel free)\b"
)
_CLAUSE_SPLIT = re.compile(
    rf"[;!?]+|\.(?=\s|$)|,?\s*\bbut\s+(?={_DIRECTIVE})|,?\s*\band\s+(?={_DIRECTIVE})",
    re.IGNORECASE,
)

_ALLOW_VERBS = re.compile(
    _ALLOW_LEAD + r"((?:read|archive|write)(?:\s*(?:,|and|or)\s*(?:read|archive|write))*)\b",
    re.IGNORECASE,
)
# Whole numbers, optionally with thousands separators ("$1,000"). "$12.50" and "$1,00" are
# left unparsed rather than misread.
_AMOUNT = r"\$?\s*(\d{1,3}(?:,\d{3})+|\d+)\b(?!\.\d)(?!,\d)"
_REFUND_LIMIT = re.compile(
    _ALLOW_LEAD + r"(?:issue|give|make|process)\s+refunds?\s+(?:of\s+)?up\s+to\s+" + _AMOUNT,
    re.IGNORECASE,
)
_ACT_ING = r"deleting|removing|trashing|sending|forwarding|replying|refunding|issuing\s+refunds?"
_CONFIRM = re.compile(
    rf"\b(?:(?:confirm|check)(?:\s+with\s+me)?|ask(?:\s+me)?)(?:\s+first)?\s+before\s+({_ACT_ING})\b",
    re.IGNORECASE,
)
_ACT_BASE = r"delete|remove|trash|send|forward|reply|refund|issue\s+refunds?|read|archive|write"
_DENY = re.compile(_DENY_LEAD + rf"({_ACT_BASE})\b", re.IGNORECASE)
_STOP = re.compile(rf"\bstop\s+({_ACT_ING})\b", re.IGNORECASE)
_AMBIGUOUS = re.compile(r"\bwithout\s+(?:asking|confirm\w*)\b", re.IGNORECASE)
_FILE_WORD = re.compile(r"\bfiles?\b", re.IGNORECASE)

# "for the next 2 hours", "for a day", "for 30 minutes": the rules in the clause expire.
_NUMBER_WORDS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
                 "six": 6, "seven": 7, "ten": 10, "twelve": 12}  # fmt: skip
_UNIT_MS = {"minute": 60_000, "min": 60_000, "hour": 3_600_000, "hr": 3_600_000,
            "day": 86_400_000, "week": 604_800_000}  # fmt: skip
_DURATION = re.compile(
    r"\bfor\s+(?:the\s+(?:next\s+)?)?(\d+|an?|one|two|three|four|five|six|seven|ten|twelve)?"
    r"\s*(minute|min|hour|hr|day|week)s?\b",
    re.IGNORECASE,
)
_DURATION_HINT = re.compile(r"\bfor\s+(?:the\s+next\b|\d+\s|an?\s+(?:hour|day|week|minute))", re.I)
MAX_VALID_FOR_MS = 90 * 86_400_000  # a temporary rule lasts at most 90 days

_EMAIL_ALLOW = {"read": "email.read", "archive": "email.archive"}
_FILE_ALLOW = {"read": "file.read", "write": "file.write"}


@dataclass(frozen=True)
class ParsedInstruction:
    effect: Effect
    action_type: str
    resource_pattern: str
    constraints: Constraints
    text_span: str
    valid_for_ms: int | None = None  # None: until revoked

    @property
    def requires_confirmation(self) -> bool:
        """High-impact rules (any effect) need the owner's explicit confirmation."""
        return self.action_type in HIGH_IMPACT


@dataclass(frozen=True)
class ParseResult:
    instructions: list[ParsedInstruction] = field(default_factory=list)
    unparsed: list[str] = field(default_factory=list)


def _clauses(text: str) -> list[str]:
    return [part.strip() for part in _CLAUSE_SPLIT.split(text) if part and part.strip()]


class _Unreadable(Exception):
    """The clause asks for something the parser cannot read exactly."""


def _duration(clause: str) -> int | None:
    match = _DURATION.search(clause)
    if match is None:
        if _DURATION_HINT.search(clause):
            raise _Unreadable  # "for the next while": a time limit we cannot read
        return None
    count_text = (match.group(1) or "1").lower()
    count = int(count_text) if count_text.isdigit() else _NUMBER_WORDS[count_text]
    unit = match.group(2).lower()
    ms = count * _UNIT_MS[unit]
    if count <= 0 or ms > MAX_VALID_FOR_MS:
        raise _Unreadable
    return ms


def _action_for(verb: str, has_file: bool) -> str | None:
    verb = verb.lower()
    if verb.startswith(("delet", "remov", "trash")):
        return "file.delete" if has_file else "email.delete"
    if verb.startswith(("send", "forward", "repl")):
        return "email.send"
    if verb.startswith(("refund", "issu")):
        return "refund.issue"
    if verb.startswith("read"):
        return "file.read" if has_file else "email.read"
    if verb.startswith("archiv"):
        return None if has_file else "email.archive"
    if verb.startswith("writ"):
        return "file.write"
    return None


def _parse_clause(clause: str) -> list[ParsedInstruction]:
    has_file = bool(_FILE_WORD.search(clause))
    found: list[tuple[Effect, str, str, Constraints]] = []

    if match := _ALLOW_VERBS.search(clause):
        table = _FILE_ALLOW if has_file else _EMAIL_ALLOW
        pattern = "files/*" if has_file else "inbox/*"
        for verb in re.findall(r"read|archive|write", match.group(1), re.IGNORECASE):
            action = table.get(verb.lower())
            if action:
                found.append((Effect.ALLOW, action, pattern, Constraints()))

    if match := _REFUND_LIMIT.search(clause):
        amount = int(match.group(1).replace(",", ""))
        found.append((Effect.ALLOW, "refund.issue", "*", Constraints(max_amount=amount)))

    if not _AMBIGUOUS.search(clause):
        # "Never delete without asking me" could mean confirm or deny: do not guess.
        if match := _CONFIRM.search(clause):
            if action := _action_for(match.group(1), has_file):
                found.append((Effect.CONFIRM, action, "*", Constraints()))
        for regex in (_DENY, _STOP):
            for match in regex.finditer(clause):
                action = _action_for(match.group(1), has_file)
                if action and (Effect.DENY, action) not in {(f[0], f[1]) for f in found}:
                    found.append((Effect.DENY, action, "*", Constraints()))

    if not found:
        return []
    valid_for = _duration(clause)
    return [
        ParsedInstruction(effect, action, pattern, constraints, clause, valid_for)
        for effect, action, pattern, constraints in found
    ]


def parse_utterance(text: str) -> ParseResult:
    """Parse an owner sentence into candidate rules and the clauses that matched nothing."""
    normalised = text.replace("’", "'")  # curly apostrophe, same length
    result = ParseResult()
    for clause in _clauses(normalised):
        try:
            parsed = _parse_clause(clause)
        except _Unreadable:
            parsed = []
        if parsed:
            result.instructions.extend(parsed)
        else:
            result.unparsed.append(clause)
    return result


def parse(text: str) -> list[ParsedInstruction]:
    """Convenience: the rules found in ``text`` (empty when nothing matches)."""
    return parse_utterance(text).instructions
