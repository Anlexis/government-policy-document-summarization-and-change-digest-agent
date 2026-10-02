"""SummarizeGenerateNode — GOV-C2-018 Government Policy Digest Agent.

Per-ministry summary generation, regulatory-change extraction with effective
dates, and operational-impact flags.
"""

import re
from typing import Any, ClassVar, Dict, List

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event
from src.schemas.state import from_json, to_json

# Japanese date form: YYYY年MM月DD日
_DATE_PATTERN = re.compile(r"(\d{4}年\d{1,2}月\d{1,2}日)")
# Words that mark a passage as requiring operator action.
_ACTION_KEYWORDS = ("申請", "提出", "対応", "義務", "更新", "届出")


class SummarizeGenerateNode(FunctionNode):
    """Summarise each ministry's documents and extract the changes that matter.

    Extraction is rule-based and deterministic, which is what makes the digest
    reproducible: the same document set produces the same digest every time, and
    a deployment that swaps in a language model changes the wording without
    changing the state contract or the output boundary.
    """

    required_trust_level: ClassVar[TrustLevel] = TrustLevel.ANONYMOUS

    def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        documents = from_json(state.get("fetched_documents"), [])
        if not isinstance(documents, list) or not documents:
            return {
                "status": AgentStatus.ERROR.value,
                "error_log": ["SummarizeGenerateNode: no documents to summarize"],
                # The runner surfaces `formatted_output or result` as `output`. A reason left only in
                # error_log reaches no one: the terminal result carries just `status`, and get_output()
                # does not copy error_log out of the graph -- the caller sees a blank spinner.
                "formatted_output": "Request could not be completed. "
                + ("SummarizeGenerateNode: no documents to summarize"),
            }

        per_ministry: Dict[str, List[str]] = {}
        regulatory_changes: List[Dict[str, str]] = []
        operational_flags: List[Dict[str, Any]] = []

        for doc in documents:
            ministry = doc.get("ministry", "不明")
            title = doc.get("title", "")
            content = doc.get("content", "")

            per_ministry.setdefault(ministry, []).append(_extract_summary(title, content))
            regulatory_changes.extend(_extract_regulatory_changes(ministry, title, content))
            operational_flags.extend(_extract_operational_flags(ministry, title, content))

        ministry_summaries = {name: " ".join(items) for name, items in per_ministry.items()}

        emit_trace_event(
            "summaries_generated",
            {
                "ministries_processed": sorted(ministry_summaries.keys()),
                "regulatory_changes_count": len(regulatory_changes),
                "operational_flags_count": len(operational_flags),
            },
            state,
        )

        return {
            "per_ministry_summaries": to_json(ministry_summaries),
            "regulatory_changes": to_json(regulatory_changes),
            "operational_flags": to_json(operational_flags),
            "status": AgentStatus.SUCCESS.value,
        }


def _extract_summary(title: str, content: str) -> str:
    """Concise summary from the title plus the first meaningful sentence."""
    sentences = re.split(r"[。\.\n]", content.strip())
    meaningful = [s.strip() for s in sentences if len(s.strip()) > 5]
    body = meaningful[0] if meaningful else ""
    return f"【{title}】{body}" if body else f"【{title}】"


def _extract_regulatory_changes(ministry: str, title: str, content: str) -> List[Dict[str, str]]:
    """Extract regulatory-change records with their effective dates."""
    dates = _DATE_PATTERN.findall(content)
    if not dates:
        return []
    return [
        {
            "ministry": ministry,
            "change": title,
            "effective_date": dates[0],  # first date = primary effective date
            "impact": "規制変更",
        }
    ]


def _extract_operational_flags(ministry: str, title: str, content: str) -> List[Dict[str, Any]]:
    """Flag documents that require operator action."""
    if not any(keyword in content for keyword in _ACTION_KEYWORDS):
        return []
    return [
        {
            "flag": "要対応",
            "description": f"{ministry}: {title}",
            "ministries": [ministry],
        }
    ]
