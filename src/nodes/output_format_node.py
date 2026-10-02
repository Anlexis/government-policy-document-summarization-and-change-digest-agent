"""OutputFormatNode — GOV-C2-018 Government Policy Digest Agent.

Renders the assembled digest in the requested format and applies the output
boundary before anything leaves the domain pipeline.
"""

import re
from typing import Any, ClassVar, Dict, Optional, Tuple

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event
from src.services.output_gate import (
    DEADLINE_SECTION_HEADING,
    REASON_LEAKAGE,
    REASON_MISSING_DEADLINE_SECTION,
    WITHHELD_NOTICE,
    carries_deadline_section,
    cleared_output_fields,
    scan_output,
)

_MARKDOWN_HEADING_RE = re.compile(r"^#{1,3}\s*")
_MARKDOWN_STRONG_RE = re.compile(r"\*\*(.+?)\*\*")


class OutputFormatNode(FunctionNode):
    """Render the weekly digest in the requested format, then gate it.

    On a violation the node does three things together, and all three matter:
    it returns an error status, it replaces the report with a non-empty
    withheld notice, and it CLEARS every other state field that carries report
    text. Returning the error alone is not containment — the platform's output
    envelope falls back to the ungated fields, so an error that leaves them
    populated still ships the report it just refused.
    """

    required_trust_level: ClassVar[TrustLevel] = TrustLevel.ANONYMOUS

    def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        assembled_digest = state.get("assembled_digest") or ""
        output_format = state.get("output_format") or "markdown"

        if not assembled_digest:
            emit_trace_event(
                "digest_render_skipped",
                {"reason": "empty_digest", "output_format": output_format},
                state,
            )
            return {
                **cleared_output_fields(),
                "status": AgentStatus.ERROR.value,
                "error_log": ["OutputFormatNode: no assembled digest to render"],
            }

        rendered = _render_digest(assembled_digest, output_format)

        violation = _gate_violation(rendered)
        if violation is not None:
            reason, detail = violation
            emit_trace_event("digest_output_withheld", {"reason": reason, **detail}, state)
            return {
                **cleared_output_fields(),
                "result": WITHHELD_NOTICE,
                "status": AgentStatus.ERROR.value,
                "error_log": [f"OutputFormatNode: {reason}"],
            }

        emit_trace_event(
            "digest_output_formatted",
            {
                "output_format": output_format,
                "output_length": len(rendered),
                "deadline_section_present": True,
            },
            state,
        )

        return {
            "result": rendered,
            "status": AgentStatus.SUCCESS.value,
        }


def _gate_violation(content: str) -> Optional[Tuple[str, Dict[str, Any]]]:
    """Return (reason, audit_detail) when `content` may not be released.

    Categories are type names, never the matched text — an audit record that
    quotes the finding re-publishes exactly what the gate refused.
    """
    categories = scan_output(content)
    if categories:
        return REASON_LEAKAGE, {"categories": categories}
    if not carries_deadline_section(content):
        return REASON_MISSING_DEADLINE_SECTION, {"expected_section": DEADLINE_SECTION_HEADING}
    return None


def _render_digest(digest: str, output_format: str) -> str:
    """Render the digest in the requested format.

    `markdown` is the assembled form as-is. `email` is the same content with the
    markdown decoration removed so it reads correctly in a plain-text client;
    the section headings survive as plain lines, which is what the output
    boundary keys on.
    """
    if output_format == "email":
        lines = []
        for line in digest.splitlines():
            line = _MARKDOWN_HEADING_RE.sub("", line)
            line = _MARKDOWN_STRONG_RE.sub(r"\1", line)
            lines.append(line)
        return "\n".join(lines)
    return digest
