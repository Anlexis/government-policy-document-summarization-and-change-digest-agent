"""QueryParseNode — GOV-C2-018 Government Policy Digest Agent.

Turns the validated request contract into the parameters the rest of the
pipeline reads: which ministries, which period label, how many documents, and
which output format.
"""

from typing import Any, ClassVar, Dict, List, Tuple

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event
from src.schemas.state import from_json, to_json
from src.services.caller_contract import MINISTRY_TAXONOMY, OUTPUT_FORMATS

_DEFAULT_PERIOD = "past_week"
_DEFAULT_MAX_DOCUMENTS = 20
_DEFAULT_OUTPUT_FORMAT = "markdown"

# Bounds applied to the runtime `digest` block itself, so a mis-edited config
# file cannot widen the request bounds the contract enforces.
_CONFIG_DOCUMENT_LIMIT_FLOOR = 1
_CONFIG_DOCUMENT_LIMIT_CEILING = 200


class QueryParseNode(FunctionNode):
    """Resolve the digest parameters from the validated contract and runtime config.

    Every value this node emits is either taken from the validated contract, or
    a default from configuration — never parsed out of free text. Free-text
    parsing used to set the period label directly from the request, which put
    caller-written text into the rendered report; the ministry scan below is the
    one free-text read that survives, and it can only ever produce names that
    are already in the closed taxonomy.
    """

    required_trust_level: ClassVar[TrustLevel] = TrustLevel.ANONYMOUS

    def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        request_text = state.get("validated_input") or state.get("user_input") or ""
        if not request_text.strip():
            return {
                "status": AgentStatus.ERROR.value,
                "error_log": ["QueryParseNode: the request carried no text"],
                # The runner surfaces `formatted_output or result` as `output`. A reason left only in
                # error_log reaches no one: the terminal result carries just `status`, and get_output()
                # does not copy error_log out of the graph -- the caller sees a blank spinner.
                "formatted_output": "Request could not be completed. "
                + ("QueryParseNode: the request carried no text"),
            }

        contract: Dict[str, Any] = from_json(state.get("request_contract"), {}) or {}
        limit, default_format = _digest_config(state)

        ministries = _resolve_ministries(contract, request_text)
        period = str(contract.get("reporting_period") or _DEFAULT_PERIOD)
        output_format = str(contract.get("output_format") or default_format)
        if output_format not in OUTPUT_FORMATS:
            output_format = _DEFAULT_OUTPUT_FORMAT

        requested = contract.get("max_documents")
        max_documents = min(requested, limit) if isinstance(requested, int) else limit

        documents = contract.get("documents")
        document_source = "caller_supplied" if documents else "reference_set"

        emit_trace_event(
            "request_parsed",
            {
                "ministries": ministries,
                "period": period,
                "max_documents": max_documents,
                "max_documents_limit": limit,
                "output_format": output_format,
                "document_source": document_source,
            },
            state,
        )

        return {
            "ministries": to_json(ministries),
            "reporting_period": period,
            "max_documents": max_documents,
            "output_format": output_format,
            "document_source": document_source,
            "status": AgentStatus.SUCCESS.value,
        }


def _digest_config(state: Dict[str, Any]) -> Tuple[int, str]:
    """Read the live `digest` block seeded into inner state, with bounded fallbacks."""
    raw = from_json(state.get("digest_config"), {}) or {}
    block = raw if isinstance(raw, dict) else {}

    limit = block.get("max_documents_limit")
    if not isinstance(limit, int) or isinstance(limit, bool):
        limit = _DEFAULT_MAX_DOCUMENTS
    limit = max(_CONFIG_DOCUMENT_LIMIT_FLOOR, min(int(limit), _CONFIG_DOCUMENT_LIMIT_CEILING))

    default_format = block.get("default_output_format")
    if default_format not in OUTPUT_FORMATS:
        default_format = _DEFAULT_OUTPUT_FORMAT

    return limit, str(default_format)


def _resolve_ministries(contract: Dict[str, Any], request_text: str) -> List[str]:
    """Pick the ministries for this run.

    Order of preference: the contract's explicit selection; then the ministries
    named in the request text; then the whole taxonomy. The text scan matches
    taxonomy entries only, so what comes out of it is always a known code and
    never caller-written text.
    """
    declared = contract.get("ministries")
    if isinstance(declared, list) and declared:
        return [name for name in MINISTRY_TAXONOMY if name in declared]

    documents = contract.get("documents")
    if isinstance(documents, list) and documents:
        supplied = {str(entry.get("ministry")) for entry in documents if isinstance(entry, dict)}
        matched = [name for name in MINISTRY_TAXONOMY if name in supplied]
        if matched:
            return matched

    mentioned = [name for name in MINISTRY_TAXONOMY if name in request_text]
    return mentioned or list(MINISTRY_TAXONOMY)
