"""AgentCore Platform v1.0"""

# Request contract for the policy-digest agent.
#
# Everything a caller can send arrives here first and leaves as either a
# validated contract or a refusal. The rules are deliberately narrow:
#
#   * every field is declared — an undeclared key is a refusal, not something
#     to ignore, because ignoring a key still carries it into the run;
#   * every number goes through a finite, bounded parser — NaN and Infinity
#     parse as floats and then compare False against any bound, which turns a
#     cap into a no-op;
#   * every string that reaches the rendered digest is locked to an inert
#     alphabet, so a caller cannot write the report;
#   * free-text document bodies are screened for instruction-injection forms
#     and for personal data before anything downstream reads them;
#   * a refusal names the FIELD and a fixed reason label — never the value, and
#     never the matched text.

import json
import math
import re
from typing import Any, Dict, List, Optional, Pattern, Tuple

# ── Domain vocabulary ────────────────────────────────────────────────────────

MINISTRY_TAXONOMY: Tuple[str, ...] = ("厚労省", "国交省", "経産省", "金融庁")
OUTPUT_FORMATS: Tuple[str, ...] = ("markdown", "email")

# ── Structural bounds (independent of runtime configuration) ─────────────────

MAX_DOCUMENT_ENTRIES = 40
MAX_TITLE_CHARS = 200
MAX_CONTENT_CHARS = 20_000
MAX_DOCUMENTS_FLOOR = 1
MAX_DOCUMENTS_CEILING = 200

# ── Inert alphabets for caller strings that reach the rendered digest ────────
#
# A period label and a document date are printed verbatim in the digest, so
# they are restricted to characters that cannot carry markup, directives or
# line structure. A ministry code is checked against the taxonomy instead — a
# closed list is stronger than any character rule.

_INERT_PERIOD_RE = re.compile(r"\A[0-9A-Za-z_/-]{1,32}\Z")
_INERT_DATE_RE = re.compile(r"\A[0-9]{4}-[0-9]{2}-[0-9]{2}\Z")
_INERT_CHANNEL_RE = re.compile(r"\A[a-z0-9_]{1,32}\Z")

# Titles carry real Japanese prose, so they cannot be locked to an inert
# alphabet. They are length-capped and screened instead, and the characters
# that would let a title restructure the report are rejected outright.
_TITLE_FORBIDDEN_RE = re.compile(r"[\r\n<>|]")

# ── Instruction-injection screen ─────────────────────────────────────────────
#
# Two families, because they fail differently:
#
#   Control tokens are the chat-template markers a model treats as structure —
#   `<|...|>`, `[INST]`, `<<SYS>>`. They carry no natural-language signal at
#   all, so matching the form is both sufficient and safe. The platform input
#   gate blocks the first two on its own but scores `<<SYS>>` as harmless, so
#   this screen owns the whole class rather than the part someone else covers.
#
#   Directive phrases need statement context. An unanchored verb match fires on
#   ordinary administrative prose (a quoted notice that says "disregard"), and a
#   screen that refuses real documents is the failure mode that actually stops
#   work — so each phrase must reach its object before it counts.

_CONTROL_TOKEN_RE = re.compile(r"<\|[^|>\n]{0,64}\|>|\[/?INST\]|<</?SYS>>", re.IGNORECASE)

_DIRECTIVE_RE = re.compile(
    r"\b(?:ignore|disregard|forget|override)\b[^.\n]{0,40}"
    r"\b(?:previous|prior|above|earlier|all)\b[^.\n]{0,20}"
    r"\b(?:instruction|instructions|prompt|prompts|rule|rules|direction|directions)\b"
    r"|\bsystem\s+prompt\b"
    r"|\bjailbreak\b"
    r"|\bdeveloper\s+mode\b"
    r"|\bact\s+as\s+(?:the\s+)?(?:system|administrator|developer)\b",
    re.IGNORECASE,
)

_EXECUTABLE_MARKUP_RE = re.compile(r"<\s*(?:script|iframe|object|embed|style)\b", re.IGNORECASE)

# Markup strip used for the second pass. Removing tags re-assembles a directive
# that was split across them, which the raw pass cannot see; running the raw
# pass first keeps the token forms that the strip would otherwise delete.
_MARKUP_TAG_RE = re.compile(r"<[^<>\n]{1,200}>")

# ── Personal-data screen ─────────────────────────────────────────────────────
#
# Written WITHOUT a word-boundary assertion. Python computes that assertion
# from its word-character class, which includes Kanji and Kana — so no boundary
# exists between a Japanese label and the digits that follow it, and a guarded
# pattern silently misses 個人番号1234-5678-9012 while matching the same digits
# after an ASCII space. Explicit "not a digit" lookarounds hold on both
# alphabets.

_PERSONAL_DATA_PATTERNS: Tuple[Tuple[str, Pattern[str]], ...] = (
    ("individual_number", re.compile(r"(?<![0-9])[0-9]{4}[-\s]?[0-9]{4}[-\s]?[0-9]{4}(?![0-9])")),
    ("national_id", re.compile(r"(?<![0-9])[0-9]{3}-[0-9]{2}-[0-9]{4}(?![0-9])")),
    ("telephone", re.compile(r"(?<![0-9])0[0-9]{1,4}-[0-9]{1,4}-[0-9]{3,4}(?![0-9])")),
    ("email_address", re.compile(r"[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9-]{1,63}(?:\.[A-Za-z0-9-]{1,63}){1,3}")),
)


def detect_personal_data(text: str) -> List[str]:
    """Return the personal-data categories present in `text` (never the values)."""
    if not isinstance(text, str) or not text:
        return []
    return [name for name, pattern in _PERSONAL_DATA_PATTERNS if pattern.search(text)]


def contains_injection(text: str) -> bool:
    """True when a string carries an instruction-injection form.

    Screens the raw string and the markup-stripped string. Raw catches control
    tokens the strip would delete; stripped catches directives spliced across
    tags. Executable-markup openers are matched on the raw pass only, since the
    strip is what removes them.
    """
    if not isinstance(text, str) or not text:
        return False
    if _EXECUTABLE_MARKUP_RE.search(text):
        return True
    for candidate in (text, _MARKUP_TAG_RE.sub("", text)):
        if _CONTROL_TOKEN_RE.search(candidate) or _DIRECTIVE_RE.search(candidate):
            return True
    return False


def payload_contains_injection(value: object) -> bool:
    """Depth-first injection screen over a parsed payload, KEYS included.

    Keys are screened because a caller controls them as freely as values, and
    the scan runs after parsing, so escape sequences in the wire format have
    already resolved to the characters they denote.
    """
    if isinstance(value, str):
        return contains_injection(value)
    if isinstance(value, dict):
        for key, nested in value.items():
            if contains_injection(str(key)) or payload_contains_injection(nested):
                return True
        return False
    if isinstance(value, (list, tuple)):
        return any(payload_contains_injection(item) for item in value)
    return False


# ── Bounded numeric parsing ──────────────────────────────────────────────────


def finite_in_range(value: object, minimum: float, maximum: float) -> Optional[float]:
    """Parse a caller number, or return None when it is not finite and in range.

    Booleans are rejected before the numeric branch: a bool IS an int in Python,
    so `max_documents: true` would otherwise be accepted as 1. Non-finite values
    are rejected explicitly — NaN and Infinity both survive `float()`, and every
    comparison against NaN is False, so a range check written the obvious way
    lets them through and the bound stops applying.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
    elif isinstance(value, str):
        try:
            number = float(value.strip())
        except (TypeError, ValueError):
            return None
    else:
        return None
    if not math.isfinite(number):
        return None
    if number < minimum or number > maximum:
        return None
    return number


# ── Refusal reasons (closed set) ─────────────────────────────────────────────

REASON_NOT_A_MAPPING = "request_context_must_be_a_mapping"
REASON_UNKNOWN_FIELD = "unrecognised_field"
REASON_INVALID_VALUE = "value_outside_the_accepted_range_or_alphabet"
REASON_INJECTION = "instruction_like_content_rejected"
REASON_PERSONAL_DATA = "personal_data_rejected"

REFUSAL_REASONS: Tuple[str, ...] = (
    REASON_NOT_A_MAPPING,
    REASON_UNKNOWN_FIELD,
    REASON_INVALID_VALUE,
    REASON_INJECTION,
    REASON_PERSONAL_DATA,
)

ACCEPTED_FIELDS: Tuple[str, ...] = (
    "channel",
    "ministries",
    "reporting_period",
    "output_format",
    "max_documents",
    "documents",
)

_DOCUMENT_FIELDS: Tuple[str, ...] = ("ministry", "title", "date", "content")


class ContractError(Exception):
    """A caller field failed validation.

    Carries the field name and one of the fixed reason labels above. The
    rejected value never travels with it — a refusal that quotes the input
    turns the error channel into an echo of whatever was sent.
    """

    def __init__(self, field: str, reason: str) -> None:
        super().__init__(f"{field}: {reason}")
        self.field = field
        self.reason = reason


def _as_mapping(value: object, field: str) -> Dict[str, Any]:
    if not isinstance(value, dict):
        raise ContractError(field, REASON_NOT_A_MAPPING)
    return {str(key): item for key, item in value.items()}


def _as_list(value: object, field: str) -> List[Any]:
    if not isinstance(value, list):
        raise ContractError(field, REASON_INVALID_VALUE)
    return value


def _as_bounded_str(value: object, field: str, maximum: int) -> str:
    if not isinstance(value, str) or not 0 < len(value) <= maximum:
        raise ContractError(field, REASON_INVALID_VALUE)
    return value


def _require(condition: bool, field: str, reason: str) -> None:
    if not condition:
        raise ContractError(field, reason)


def _validate_document(entry: object, index: int) -> Dict[str, str]:
    """Validate one caller-supplied policy document."""
    label = f"documents[{index}]"
    fields = _as_mapping(entry, label)
    _require(all(key in _DOCUMENT_FIELDS for key in fields), label, REASON_UNKNOWN_FIELD)

    ministry = fields.get("ministry")
    _require(ministry in MINISTRY_TAXONOMY, f"{label}.ministry", REASON_INVALID_VALUE)

    title = _as_bounded_str(fields.get("title"), f"{label}.title", MAX_TITLE_CHARS)
    _require(not _TITLE_FORBIDDEN_RE.search(title), f"{label}.title", REASON_INVALID_VALUE)

    date = _as_bounded_str(fields.get("date"), f"{label}.date", 10)
    _require(bool(_INERT_DATE_RE.match(date)), f"{label}.date", REASON_INVALID_VALUE)

    content = _as_bounded_str(fields.get("content"), f"{label}.content", MAX_CONTENT_CHARS)

    for field_name, text in ((f"{label}.title", title), (f"{label}.content", content)):
        _require(not contains_injection(text), field_name, REASON_INJECTION)
        _require(not detect_personal_data(text), field_name, REASON_PERSONAL_DATA)

    return {"ministry": str(ministry), "title": title, "date": date, "content": content}


# A request may also be written as a JSON object in the request string itself.
# That shape predates the structured channel and is still accepted, but it is
# routed through the SAME validator — one spelling difference only.
REQUEST_STRING_ALIASES: Dict[str, str] = {"period": "reporting_period"}


def structured_fields_from_request_string(user_input: str) -> Dict[str, Any]:
    """Return the structured fields carried inside a JSON request string.

    Returns {} for ordinary prose, so a plain-language request is never
    misread as a malformed structured one.
    """
    if not isinstance(user_input, str):
        return {}
    text = user_input.strip()
    if not (text.startswith("{") and text.endswith("}")):
        return {}
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, TypeError, ValueError):
        return {}
    if not isinstance(parsed, dict):
        return {}
    return {REQUEST_STRING_ALIASES.get(str(key), str(key)): value for key, value in parsed.items()}


def validate_request_context(raw: object) -> Dict[str, Any]:
    """Validate the caller's structured request; raise ContractError on refusal.

    Returns a contract carrying only the fields the caller actually sent, each
    already bounded and inert. Absent fields stay absent so downstream nodes can
    tell "not requested" from "requested and empty" and fall back to their own
    defaults.
    """
    if raw is None:
        return {}
    fields = _as_mapping(raw, "request_context")
    if not fields:
        return {}

    unknown = [key for key in fields if key not in ACCEPTED_FIELDS]
    if unknown:
        # The offending name is caller data, so the refusal reports how many
        # were rejected rather than echoing them back.
        raise ContractError(f"request_context ({len(unknown)} field(s))", REASON_UNKNOWN_FIELD)

    _require(not payload_contains_injection(fields), "request_context", REASON_INJECTION)

    contract: Dict[str, Any] = {}

    if "channel" in fields:
        channel = _as_bounded_str(fields["channel"], "channel", 32)
        _require(bool(_INERT_CHANNEL_RE.match(channel)), "channel", REASON_INVALID_VALUE)
        contract["channel"] = channel

    if "ministries" in fields:
        ministries = _as_list(fields["ministries"], "ministries")
        _require(0 < len(ministries) <= len(MINISTRY_TAXONOMY), "ministries", REASON_INVALID_VALUE)
        _require(all(item in MINISTRY_TAXONOMY for item in ministries), "ministries", REASON_INVALID_VALUE)
        # Deduplicate while keeping the taxonomy's own order, so the rendered
        # section order never depends on how the caller happened to sort them.
        contract["ministries"] = [name for name in MINISTRY_TAXONOMY if name in ministries]

    if "reporting_period" in fields:
        period = _as_bounded_str(fields["reporting_period"], "reporting_period", 32)
        _require(bool(_INERT_PERIOD_RE.match(period)), "reporting_period", REASON_INVALID_VALUE)
        contract["reporting_period"] = period

    if "output_format" in fields:
        _require(fields["output_format"] in OUTPUT_FORMATS, "output_format", REASON_INVALID_VALUE)
        contract["output_format"] = str(fields["output_format"])

    if "max_documents" in fields:
        parsed = finite_in_range(fields["max_documents"], MAX_DOCUMENTS_FLOOR, MAX_DOCUMENTS_CEILING)
        _require(parsed is not None and float(parsed).is_integer(), "max_documents", REASON_INVALID_VALUE)
        contract["max_documents"] = int(parsed or 0)

    if "documents" in fields:
        documents = _as_list(fields["documents"], "documents")
        _require(0 < len(documents) <= MAX_DOCUMENT_ENTRIES, "documents", REASON_INVALID_VALUE)
        contract["documents"] = [_validate_document(entry, index) for index, entry in enumerate(documents)]

    return contract
