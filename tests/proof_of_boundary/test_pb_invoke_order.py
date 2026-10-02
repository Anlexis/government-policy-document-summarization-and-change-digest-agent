# Backbone invoke order + per-node call order.
#
# Part 1 (TestBackboneInvokeOrder): a full agent.invoke() asserting the 5-node
#   backbone order [InitializeNode, PreProcessNode, PolicyDigestGraphNode,
#   PostProcessNode, FinalizeNode] with a request that succeeds.
#   The caller arrives VERIFIED_EXTERNAL — never through the internal-context
#   shortcut, which would mask an inner-node trust misdeclaration.
#
# Part 2 (TestInvokeOrder): verifies the framework's node wrapper enforces the
#   per-node order — trust gate -> node_start -> input gate -> execute ->
#   output gate -> node_complete — for every concrete node under src/nodes/.

import importlib
import inspect
import pkgutil

import pytest

from framework.schemas.invocation_context import InvocationContext
from framework.schemas.trust_level import TrustLevel
from src.services.output_gate import DEADLINE_SECTION_HEADING

# Template-specific: the main-slot GraphNode class from src/graph/graph.py
_MAIN_SLOT_NODE = "PolicyDigestGraphNode"

# Template-specific: a request that produces a digest. Identical to the payload
# in deploy/invoke_payload.json, so the deployment check and this test exercise
# the same path.
_VALID_PAYLOAD = "厚労省と国交省の今週の政策文書ダイジェストを作成してください。"


# ── Part 1: Backbone order ────────────────────────────────────────────────────


def _run(payload: str) -> dict:
    """Compile the agent and invoke it with a VERIFIED_EXTERNAL caller.

    An external caller arrives VERIFIED_EXTERNAL. Using the internal-context
    shortcut here would admit every node regardless of what it declares, which
    is exactly the misdeclaration this file exists to catch.
    """
    from src.graph.graph import GovernmentPolicyDigestAgent, runtime_config

    agent = GovernmentPolicyDigestAgent(config=runtime_config())
    agent.compile()

    ctx = InvocationContext(
        session_id="pb6-test-session",
        caller_trust_level=TrustLevel.VERIFIED_EXTERNAL,
        caller_id="pb6-test",
    )
    return agent.invoke(payload, ctx=ctx)


class TestBackboneInvokeOrder:
    def test_success_path_returns_status_success(self):
        from framework.schemas.agent_status import AgentStatus

        result = _run(_VALID_PAYLOAD)
        assert (
            result.get("status") == AgentStatus.SUCCESS
        ), f"Expected SUCCESS but got {result.get('status')}; error_log={result.get('error_log')}"

    def test_backbone_node_history_order(self):
        """initialize -> pre_process -> main -> post_process -> finalize."""
        result = _run(_VALID_PAYLOAD)
        node_history = result.get("node_history", [])

        def _name(entry):
            if isinstance(entry, dict):
                return entry.get("node", "") or entry.get("name", "") or str(entry)
            return str(entry)

        names = [_name(entry) for entry in node_history]
        backbone = ["InitializeNode", "PreProcessNode", _MAIN_SLOT_NODE, "PostProcessNode", "FinalizeNode"]
        positions = []
        for expected in backbone:
            matches = [index for index, name in enumerate(names) if expected in name]
            assert matches, f"Backbone node '{expected}' not found in node_history: {names}"
            positions.append(matches[0])
        assert positions == sorted(positions), f"Backbone visited out of order: {names}"

    def test_output_is_non_empty(self):
        """A successful run surfaces the report under the envelope's output key,
        not under an internal state field name."""
        result = _run(_VALID_PAYLOAD)
        assert result.get("output"), f"result['output'] is empty; result keys: {list(result.keys())}"

    def test_the_deadline_section_is_never_suppressed(self):
        """The section this agent exists for. It is emitted even when the period
        held no deadlines, so its presence is an invariant of every released
        digest rather than a property of this particular request."""
        result = _run(_VALID_PAYLOAD)
        assert DEADLINE_SECTION_HEADING in result.get("output", "")

    def test_an_external_caller_is_admitted_through_the_whole_graph(self):
        """The inner nodes admit the caller the entry node already vetted. If an
        inner node demanded a higher trust level than an external caller can
        hold, the nested graph would raise and this would fail."""
        from framework.schemas.agent_status import AgentStatus

        result = _run(_VALID_PAYLOAD)
        assert result.get("status") != AgentStatus.ERROR, (
            f"a verified external caller was denied — likely an inner-node trust misdeclaration: "
            f"error_log={result.get('error_log')}"
        )


# ── Part 2: Per-node call order ───────────────────────────────────────────────


def _discover_node_classes() -> list:
    """Import every module under src/nodes/ and collect concrete node classes."""
    from framework.nodes.base_node import BaseNode

    try:
        pkg = importlib.import_module("src.nodes")
    except ImportError:
        return []

    discovered = []
    for _, modname, _ in pkgutil.walk_packages(pkg.__path__, prefix="src.nodes."):
        module = importlib.import_module(modname)
        for attr in vars(module).values():
            if (
                isinstance(attr, type)
                and issubclass(attr, BaseNode)
                and attr is not BaseNode
                and attr.__module__ == modname
                and not inspect.isabstract(attr)
            ):
                discovered.append(attr)
    return discovered


class TestInvokeOrder:
    """The framework's node wrapper enforces the per-node order for every node."""

    def test_call_order_for_every_node(self, monkeypatch):
        node_classes = _discover_node_classes()
        if not node_classes:
            pytest.skip("no concrete node classes found under src/nodes/")

        import framework.nodes.base_node as base_node_module

        failures: list = []
        for node_cls in node_classes:
            order: list = []
            monkeypatch.setattr(
                base_node_module,
                "emit_trace_event",
                lambda event_type, _payload, _state, _o=order: _o.append(f"event:{event_type}"),
            )

            for method_name, label in (
                ("_security_gate_input", "security_gate_input"),
                ("execute", "execute"),
                ("_security_gate_output", "security_gate_output"),
            ):
                original = getattr(node_cls, method_name)

                def spy(self, arg, _o=order, _label=label, _orig=original):
                    _o.append(_label)
                    return _orig(self, arg)

                monkeypatch.setattr(node_cls, method_name, spy)

            instance = node_cls()
            state = {
                "caller_trust_level": node_cls.required_trust_level.value,
                "correlation_id": "pb6-invoke-order-test",
            }
            instance(state)

            expected = [
                "event:node_start",
                "security_gate_input",
                "execute",
                "security_gate_output",
                "event:node_complete",
            ]
            if order != expected:
                failures.append(
                    f"{node_cls.__name__}: invoke order violation.\nexpected: {expected}\nactual:   {order}"
                )

        assert not failures, "\n\n".join(failures)
