"""AgentCore Platform v1.0"""

# Backbone entry node: the trust boundary and the owner of the caller contract.
#
# Node contract:
#  - Extend FunctionNode; implement execute(state) -> dict
#  - Return ONLY the fields this node changes (never full state)
#  - Return AgentStatus enum constants — never plain strings
#  - Structured invocation parameters arrive via state["input_context"] and are
#    read-only; what travels onward is the validated contract, not the raw body
#  - Never import from mediator/, api/, or other agents

from typing import Any, ClassVar, Dict

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event
from src.schemas.state import to_json
from src.services.caller_contract import (
    ContractError,
    contains_injection,
    structured_fields_from_request_string,
    validate_request_context,
)


# The Marketplace runner seeds input_context with its own conversation history on every
# invocation (shared/bootstrap/marketplace_app.py); the caller neither sends that key nor can
# suppress it, and the build_input_context hook can only overwrite its value, never remove it.
# It is platform plumbing rather than caller data, so it is dropped here, before the caller
# contract runs: the unknown-field guard below stays strict for everything a caller can
# actually send, and no value screen is ever asked to judge a transcript that contains this
# agent's own earlier answers. The value may also be None, which this tolerates.
_PLATFORM_CONTEXT_KEYS = frozenset({"conversation_history"})


def _without_platform_context(raw: Any) -> Any:
    """The caller-supplied half of input_context, platform-injected keys removed."""
    if not isinstance(raw, dict):
        return raw
    return {k: v for k, v in raw.items() if k not in _PLATFORM_CONTEXT_KEYS}


MAX_REQUEST_CHARS = 10_000


class PreProcessNode(FunctionNode):
    """Validate the incoming digest request and produce the caller contract.

    This node owns the template's own input guarantees. The platform runs an
    input gate of its own in front of it, but that gate is a property of the
    deployment, not of this template: where it is absent or configured off, a
    request refused here must still be refused. So the checks below are
    enforced here and proven by calling this node directly, with no platform
    wrapper in front of it.
    """

    required_trust_level: ClassVar[TrustLevel] = TrustLevel.VERIFIED_EXTERNAL

    def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        user_input = state.get("user_input") or ""
        request_context = _without_platform_context(state.get("input_context")) or {}

        if not user_input.strip():
            return self._refused(state, "request_body_empty")

        if len(user_input) > MAX_REQUEST_CHARS:
            return self._refused(state, "request_body_too_long")

        if contains_injection(user_input):
            return self._refused(state, "instruction_like_content_rejected")

        # A request can arrive two ways: as a JSON object inside the request
        # string, or on the structured channel. Both go through one validator,
        # so neither spelling has weaker rules than the other. The structured
        # channel wins on a conflict — it is the explicit one.
        merged_request = {
            **structured_fields_from_request_string(user_input),
            **(request_context if isinstance(request_context, dict) else {}),
        }

        try:
            contract = validate_request_context(merged_request)
        except ContractError as refusal:
            return self._refused(state, refusal.reason, field=refusal.field)

        emit_trace_event(
            "request_accepted",
            {
                "declared_fields": sorted(contract.keys()),
                "document_count": len(contract.get("documents", [])),
                "channel": contract.get("channel", "unspecified"),
            },
            state,
        )

        return {
            "validated_input": user_input.strip(),
            "request_contract": to_json(contract),
            "enriched_context": to_json(
                {
                    "source": "GovernmentPolicyDigestAgent",
                    "channel": contract.get("channel", "unspecified"),
                }
            ),
            "status": AgentStatus.SUCCESS.value,
        }

    def _refused(self, state: Dict[str, Any], reason: str, field: str = "request_body") -> Dict[str, Any]:
        """Refuse the request, naming the field and the reason but never the value."""
        emit_trace_event("request_refused", {"field": field, "reason": reason}, state)
        return {
            "status": AgentStatus.ERROR.value,
            "error_log": [f"PreProcessNode: {field}: {reason}"],
            # The runner surfaces `formatted_output or result` as `output`. A reason left only in
            # error_log reaches no one: the terminal result carries just `status`, and get_output()
            # does not copy error_log out of the graph -- the caller sees a blank spinner.
            "formatted_output": "Request could not be completed. " + (f"PreProcessNode: {field}: {reason}"),
        }
