"""DocumentFetchNode — GOV-C2-018 Government Policy Digest Agent.

Assembles the document set for the period: the caller's own policy documents
when they sent any, otherwise the built-in reference corpus.
"""

from typing import Any, ClassVar, Dict, List

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event
from src.schemas.state import from_json, to_json

# Built-in reference corpus. It is what the agent digests when a caller sends no
# documents of their own, so a request with no data still produces a real, fully
# shaped digest rather than an empty one. A deployment that pulls from a
# ministry feed replaces this set; the node contract does not change.
_REFERENCE_DOCUMENTS: List[Dict[str, str]] = [
    {
        "ministry": "厚労省",
        "title": "労働安全衛生法施行規則改正通達",
        "date": "2026-06-25",
        "content": (
            "2026年9月1日を施行日として労働安全衛生法施行規則の一部が改正されます。"
            "主な変更点: 作業環境測定頻度の見直し、健康診断項目の追加。"
            "事業者は2026年8月15日までに対応計画を提出することが求められます。"
        ),
    },
    {
        "ministry": "国交省",
        "title": "建設業法施行規則一部改正（財産的基礎要件強化）",
        "date": "2026-06-24",
        "content": (
            "建設業の許可要件が変更されます。施行日は2026年10月1日。"
            "財産的基礎要件の強化として自己資本額基準が引き上げられます。"
            "既存許可業者は2026年9月30日までに更新申請が必要です。"
        ),
    },
    {
        "ministry": "経産省",
        "title": "省エネ法特定事業者報告義務拡大に関する運用指針",
        "date": "2026-06-23",
        "content": (
            "省エネ法に基づく特定事業者の報告義務が拡大されます。"
            "対象: エネルギー使用量1,500kl以上の事業者。"
            "2026年7月31日が第一回提出期限です。"
        ),
    },
    {
        "ministry": "金融庁",
        "title": "金融サービス仲介業監督指針改正",
        "date": "2026-06-22",
        "content": (
            "金融サービス仲介業者に対して新たな情報提供義務が設けられます。"
            "施行日: 2026年8月1日。"
            "対象業者は2026年7月15日までに対応を完了してください。"
        ),
    },
]


def reference_documents() -> List[Dict[str, str]]:
    """A copy of the built-in reference corpus."""
    return [dict(entry) for entry in _REFERENCE_DOCUMENTS]


class DocumentFetchNode(FunctionNode):
    """Select the documents this run summarises.

    Caller-supplied documents win when present — they have already passed the
    request boundary's per-field bounds, so what arrives here is bounded text
    from the closed ministry taxonomy. Otherwise the reference corpus is used,
    which is what keeps a request with no data on the same code path as a
    request with data instead of a separate, less-exercised one.
    """

    required_trust_level: ClassVar[TrustLevel] = TrustLevel.ANONYMOUS

    def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        contract: Dict[str, Any] = from_json(state.get("request_contract"), {}) or {}
        ministries = from_json(state.get("ministries"), []) or []
        max_documents = state.get("max_documents") or len(_REFERENCE_DOCUMENTS)

        supplied = contract.get("documents")
        if isinstance(supplied, list) and supplied:
            source = "caller_supplied"
            candidates: List[Dict[str, str]] = [dict(entry) for entry in supplied]
        else:
            source = "reference_set"
            candidates = reference_documents()

        if ministries:
            candidates = [doc for doc in candidates if doc.get("ministry") in ministries]

        documents = candidates[: int(max_documents)]

        emit_trace_event(
            "documents_selected",
            {
                "source": source,
                "ministry_count": len({doc.get("ministry") for doc in documents}),
                "document_count": len(documents),
                "max_documents": int(max_documents),
            },
            state,
        )

        return {
            "fetched_documents": to_json(documents),
            "document_source": source,
            "status": AgentStatus.SUCCESS.value,
        }
