"""DeadlineGateNode — GOV-C2-018 Government Policy Digest Agent.

The compliance-deadline gate. It always emits `deadline_highlights`, even when
the period held no deadlines: an explicit empty list is a statement ("nothing
this period"), whereas an absent field is indistinguishable from a step that
did not run. Everything downstream — the assembled digest and the output
boundary — relies on that distinction.
"""

import re
from typing import Any, ClassVar, Dict, List, Set

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event
from src.schemas.state import from_json, to_json

_DATE_PATTERN = re.compile(r"(\d{4}年\d{1,2}月\d{1,2}日)")

# Words that mark a passage as carrying a compliance deadline.
_DEADLINE_KEYWORDS = frozenset({"期限", "締め切り", "施行", "施行日", "申請期限", "提出期限", "まで", "以内"})


class DeadlineGateNode(FunctionNode):
    """Collect every compliance deadline in the period, with its required action.

    Scans the extracted regulatory changes first (they already carry an
    effective date), then the raw documents for any further dated deadline the
    extraction did not surface. Deduplicated by date, so one deadline appears
    once however many documents mention it.
    """

    required_trust_level: ClassVar[TrustLevel] = TrustLevel.ANONYMOUS

    def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        regulatory_changes = from_json(state.get("regulatory_changes"), [])
        documents = from_json(state.get("fetched_documents"), [])
        if not isinstance(regulatory_changes, list):
            regulatory_changes = []
        if not isinstance(documents, list):
            documents = []

        highlights = _extract_deadline_highlights(regulatory_changes, documents)

        emit_trace_event(
            "deadline_gate_applied",
            {
                "deadline_highlights_count": len(highlights),
                "source_changes": len(regulatory_changes),
                "source_documents": len(documents),
            },
            state,
        )

        return {
            "deadline_highlights": to_json(highlights),
            "status": AgentStatus.SUCCESS.value,
        }


def _extract_deadline_highlights(
    regulatory_changes: List[Dict[str, str]], documents: List[Dict[str, str]]
) -> List[Dict[str, str]]:
    """Extract every compliance-deadline highlight.

    Always returns a list; empty means no deadlines were found, which is a
    result, not a failure. Every highlight carries change, effective_date and
    required_action.
    """
    highlights: List[Dict[str, str]] = []
    seen_dates: Set[str] = set()

    for change in regulatory_changes:
        effective_date = change.get("effective_date", "")
        if effective_date and effective_date not in seen_dates:
            highlights.append(
                {
                    "change": change.get("change", ""),
                    "effective_date": effective_date,
                    "required_action": _infer_action(documents),
                }
            )
            seen_dates.add(effective_date)

    for doc in documents:
        content = doc.get("content", "")
        title = doc.get("title", "")
        ministry = doc.get("ministry", "")

        if not any(keyword in content for keyword in _DEADLINE_KEYWORDS):
            continue

        for date_str in _DATE_PATTERN.findall(content):
            if date_str not in seen_dates:
                highlights.append(
                    {
                        "change": f"{ministry}: {title}",
                        "effective_date": date_str,
                        "required_action": _infer_action([doc]),
                    }
                )
                seen_dates.add(date_str)

    return highlights


def _infer_action(documents: List[Dict[str, str]]) -> str:
    """Infer the required action from the documents backing a deadline."""
    content = " ".join(doc.get("content", "") for doc in documents)
    if "申請" in content:
        return "申請書類を期日までに提出してください。"
    if "報告" in content or "提出" in content:
        return "報告・提出書類を期日までに準備し提出してください。"
    if "対応計画" in content:
        return "対応計画を策定し、期日までに提出してください。"
    return "詳細を確認し、期日までに対応してください。"
