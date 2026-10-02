"""AgentCore Platform v1.0"""

# Backbone finalisation node: the last checkpoint before the digest leaves the
# agent. It re-runs the same output boundary the render node ran, on the value
# that actually reached this slot — a second, independent pass over the same
# rules rather than a second RULE SET that could drift from the first.

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
from src.services.llm_factory import resolve_llm
from src.services.llm_review import render_review, review_result
from src.services.source_disclosure import source_label


class PostProcessNode(FunctionNode):
    """Release the digest, or withhold it and clear every field that carries it.

    Withholding is three things at once — an error status, a non-empty notice
    in place of the report, and every report-bearing state field cleared. The
    third is the one that is easy to omit and the one that decides whether the
    refusal holds: the platform's output envelope reads the gated field first
    and falls back to the ungated result, so an error that leaves the report in
    state ships it anyway.
    """

    required_trust_level: ClassVar[TrustLevel] = TrustLevel.ANONYMOUS

    def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        result = state.get("result") or ""

        if not result:
            emit_trace_event("digest_release_skipped", {"reason": "no_report_produced"}, state)
            return {
                **cleared_output_fields(),
                "status": AgentStatus.ERROR.value,
                "error_log": ["PostProcessNode: the pipeline produced no report to release"],
            }

        _llm, _ = resolve_llm(None, state)
        _remarks = review_result(
            _llm,
            user_input=str(state.get("user_input") or ""),
            result=result,
            domain="GOV GovernmentPolicyDigestAgent",
        )
        _review = render_review(_remarks)
        # Remarks are LLM text derived from the caller's raw words, so they pass through the
        # same gate the answer does -- appending after the gate would put unscanned text past
        # it. A tripped review is dropped on its own: withholding a correct answer because an
        # advisory remark quoted an identifier would let the review change the outcome, and
        # the whole design rests on it being unable to.
        if _review and isinstance(result, str) and not _gate_violation(result + _review):
            result = result + _review

        # Say where the answer came from. This agent answers from a corpus defined inside
        # its own module; a reader seeing a citation has no way to tell that from a live query
        # against the system of record, and the review round rated that confusion its most
        # serious finding. Added before the gate below so it passes the same checks the answer
        # does.
        result = result + source_label(state)
        violation = _gate_violation(result)
        if violation is not None:
            reason, detail = violation
            emit_trace_event("digest_release_withheld", {"reason": reason, **detail}, state)
            return {
                **cleared_output_fields(),
                "result": WITHHELD_NOTICE,
                "formatted_output": WITHHELD_NOTICE,
                "status": AgentStatus.ERROR.value,
                "error_log": [f"PostProcessNode: {reason}"],
            }

        emit_trace_event(
            "digest_released",
            {"output_length": len(result), "deadline_section_present": True},
            state,
        )

        return {
            "formatted_output": result,
            "status": AgentStatus.SUCCESS.value,
        }


def _gate_violation(content: str) -> Optional[Tuple[str, Dict[str, Any]]]:
    """Return (reason, audit_detail) when `content` may not be released."""
    categories = scan_output(content)
    if categories:
        return REASON_LEAKAGE, {"categories": categories}
    if not carries_deadline_section(content):
        return REASON_MISSING_DEADLINE_SECTION, {"expected_section": DEADLINE_SECTION_HEADING}
    return None
