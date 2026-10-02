"""AgentCore Platform v1.0"""

# State must be a flat TypedDict — never a Pydantic model. Graph checkpoints are
# msgpack-serialized, and objects that are not plain data corrupt silently on the
# way back out. Extend AgentState with agent-specific fields only, and never put
# credentials or secrets in state.
#
# Serialization rule: dict/list fields are typed Optional[str] and travel as JSON
# text — producers call to_json(), consumers call from_json().

import json
from typing import Any, Optional

from framework.schemas.agent_state import AgentState


def to_json(value: Any) -> str:
    """Serialize a structured value for a string-typed state field."""
    return json.dumps(value, ensure_ascii=False)


def from_json(raw: Any, default: Any) -> Any:
    """Read a structured value back out of a string-typed state field.

    Returns `default` for an absent, empty or unparsable field, so a consumer
    never has to guard the read at every call site.
    """
    if not raw:
        return default
    if not isinstance(raw, str):
        return raw
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError, ValueError):
        return default


class State(AgentState):
    """GOV-C2-018 Government Policy Document Summarization state.

    All shared fields (user_input, status, session_id, node_history,
    error_log, hitl_*, etc.) are inherited from AgentState.

    Every dict/list field is typed Optional[str]; producers write to_json(value),
    consumers read from_json(value, default).
    """

    # --- outer backbone ---
    validated_input: Optional[str]  # validated user_input from PreProcessNode
    enriched_context: Optional[str]  # JSON-str dict: {"source": ..., "channel": ...}
    request_contract: Optional[str]  # JSON-str dict: the validated caller request

    # --- runtime configuration forwarded into the inner graph ---
    digest_config: Optional[str]  # JSON-str dict: the live `digest` block of config/config.yaml

    # --- parsed request (QueryParseNode) ---
    ministries: Optional[str]  # JSON-str list of ministry names
    reporting_period: Optional[str]  # validated period label, e.g. "2026-06-23/2026-06-30"
    max_documents: Optional[int]  # document cap (int — JSON-safe primitive)
    output_format: Optional[str]  # "markdown" | "email"
    document_source: Optional[str]  # "caller_supplied" | "reference_set"

    # --- document fetch (DocumentFetchNode) ---
    fetched_documents: Optional[str]  # JSON-str list of {ministry, title, date, content}

    # --- summarization (SummarizeGenerateNode) ---
    per_ministry_summaries: Optional[str]  # JSON-str dict {ministry: summary}
    regulatory_changes: Optional[str]  # JSON-str list of {ministry, change, effective_date, impact}
    operational_flags: Optional[str]  # JSON-str list of {flag, description, ministries}

    # --- deadline gate (DeadlineGateNode) ---
    deadline_highlights: Optional[str]  # JSON-str list of {change, effective_date, required_action}

    # --- digest assembly (DigestFormatNode) ---
    assembled_digest: Optional[str]  # assembled email-ready digest (markdown string)
    cross_ministry_dependencies: Optional[str]  # JSON-str list of {dependency, ministries}

    # --- output ---
    result: Optional[str]  # gated digest (set by merge_output from the inner graph)
    formatted_output: Optional[str]  # gated output from PostProcessNode
