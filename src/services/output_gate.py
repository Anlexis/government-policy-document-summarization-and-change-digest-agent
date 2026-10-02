"""AgentCore Platform v1.0"""

# The single output boundary for the policy digest.
#
# Both gate points — the inner render node and the outer finalisation node —
# call THIS module rather than carrying a pattern list each. One implementation
# means the two cannot drift apart, and it means the credential rules are the
# platform's own: a local list that is narrower than the platform's lets a value
# through that the platform then raises on deeper in the call, at which point
# the raising node's whole result is discarded and any clearing it did goes with
# it. A detector gap is not a smaller gate — it is a way around the gate.
#
# Two independent checks, each with its own reason label:
#
#   1. Leakage — credential shapes (platform detector) and personal data
#      (CJK-safe screen). A hit withholds the report.
#   2. The digest invariant — every released digest carries the compliance
#      deadline section. The section is the reason this agent exists: it is
#      emitted even when the period held no deadlines, with an explicit
#      "none this period" line. A released report without it would read as
#      "no deadlines" to someone who cannot tell the difference between an
#      empty section and a missing one, so its absence withholds the report
#      too.

import re
from typing import Dict, List, Optional, Pattern, Tuple

from framework.security.credential_detector import detect_credentials
from src.services.caller_contract import detect_personal_data

# Local additions, on TOP of the platform detector — never instead of it. The
# platform's set recognises credential VALUES by their own shape; this one
# recognises a secret by the way it is written down, which is how a secret
# usually appears inside a document body. An assignment separator is required so
# the words alone, which occur in ordinary policy prose, are not enough.
_LOCAL_PATTERNS: Tuple[Tuple[str, Pattern[str]], ...] = (
    (
        "assigned_secret",
        re.compile(
            r"\b(?:password|passwd|secret|api[_-]?key|access[_-]?token|token|credential)\b\s*[:=]\s*\S{6,}",
            re.IGNORECASE,
        ),
    ),
)

# The heading the deadline gate always emits. Kept here, next to the check that
# enforces it, so the renderer and the gate cannot disagree about its text.
# The markdown level marker is NOT part of it: the plain-text rendering strips
# leading `#` characters, and a gate keyed on the marker would then refuse every
# plain-text digest it had just rendered correctly.
DEADLINE_SECTION_HEADING = "⚠️ コンプライアンス期限アラート（必読）"

# Reason labels are a closed set. What reaches the caller and the audit record
# is one of these strings plus the category names below — never the offending
# text, never a file path, never a traceback.
REASON_LEAKAGE = "output_withheld_sensitive_content"
REASON_MISSING_DEADLINE_SECTION = "output_withheld_deadline_section_absent"

# Replacement for a withheld report. It has to be non-empty: the platform's
# output envelope falls back to the ungated field whenever the gated one is
# falsy, so an empty string re-opens exactly the path this gate exists to close.
WITHHELD_NOTICE = (
    "この配信は保留されました。ダイジェスト本文は出力ゲートにより差し止められています。"
    " (Digest withheld by the output gate.)"
)

# State fields that carry report text. On a violation every one of them is
# cleared: returning an error while leaving the ungated text in state still
# ships it, because the envelope falls back to whatever the gated field does
# not cover.
OUTPUT_BEARING_FIELDS: List[str] = [
    "result",
    "formatted_output",
    "assembled_digest",
    "per_ministry_summaries",
    "regulatory_changes",
    "operational_flags",
    "deadline_highlights",
    "cross_ministry_dependencies",
    "fetched_documents",
]


def scan_output(content: str) -> List[str]:
    """Return the sensitive-content categories found in `content`.

    Empty list means nothing was found. Categories are type names only
    ("aws_key", "individual_number", ...) — the matched text never leaves here.
    """
    if not content:
        return []
    categories = [finding["type"] for finding in detect_credentials(content)]
    categories.extend(name for name, pattern in _LOCAL_PATTERNS if pattern.search(content))
    categories.extend(detect_personal_data(content))
    # Stable, de-duplicated order so an audit record for the same content reads
    # the same way every time.
    return sorted(set(categories))


def carries_deadline_section(content: str) -> bool:
    """True when the digest carries its mandatory compliance-deadline section."""
    return DEADLINE_SECTION_HEADING in (content or "")


def cleared_output_fields() -> Dict[str, Optional[str]]:
    """The state delta that removes every report-bearing field."""
    return {field: None for field in OUTPUT_BEARING_FIELDS}
