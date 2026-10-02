"""DomainWorkflowGraph — GOV-C2-018 Government Policy Digest Agent.

The inner graph of the two-layer nested design. It encapsulates the whole
policy-digest workflow:

    START -> query_parse -> document_fetch -> summarize_generate
          -> deadline_gate -> digest_format -> output_format -> END

Called by PolicyDigestGraphNode.get_subgraph() in src/graph/graph.py.
get_output() shapes the sub_result dict consumed by merge_output() there.
"""

from typing import Any, Dict

from langgraph.graph import END, START

from framework.graph.base_graph import BaseGraph
from framework.schemas.agent_state import AgentState
from framework.schemas.agent_status import AgentStatus
from src.graph.context_bridge import get_request_contract
from src.nodes.deadline_gate_node import DeadlineGateNode
from src.nodes.digest_format_node import DigestFormatNode
from src.nodes.document_fetch_node import DocumentFetchNode
from src.nodes.output_format_node import OutputFormatNode
from src.nodes.query_parse_node import QueryParseNode
from src.nodes.summarize_generate_node import SummarizeGenerateNode
from src.schemas.state import State, to_json


class DomainWorkflowGraph(BaseGraph):
    """Inner domain workflow graph for GOV-C2-018.

    Inherits BaseGraph for a fully custom 6-node linear topology.
    Nodes are instantiated with no constructor arguments; config reaches them
    through seeded state (_extra_initial_state below).
    """

    # ── Identity ──────────────────────────────────────────────────────────────

    @property
    def name(self) -> str:
        return "gov_c2_018_domain_workflow"

    @property
    def state_schema(self) -> type:
        return State

    # ── Config validation ─────────────────────────────────────────────────────

    def _validate_config(self) -> None:
        """Validate the forwarded config before compilation.

        The `digest` block is read per call by the parse node with bounded
        fallbacks, so absence is non-fatal and this hook stays permissive rather
        than raising.
        """

    # ── Config and request forwarding into inner state ────────────────────────

    def _extra_initial_state(self) -> Dict[str, Any]:
        """Seed the inner state with everything that cannot travel as a string.

        The framework passes only the request string into a nested graph, so two
        things are seeded here instead:

        `digest_config` — the live tuning block forwarded by
        PolicyDigestGraphNode._parent_config(). Domain nodes take no config
        parameter, so state seeding is the only route runtime config can reach
        QueryParseNode.

        `request_contract` — the validated contract stashed on the bridge by
        PolicyDigestGraphNode.extract_input() one step earlier. It carries the
        caller's ministry selection, period label and their own policy
        documents, already bounds-checked at the request boundary.

        Both travel as JSON strings, matching the state schema's rule for
        structured fields.
        """
        digest = (self.config or {}).get("configurable", {}).get("digest") or {}
        return {
            "digest_config": to_json(digest),
            "request_contract": to_json(get_request_contract()),
        }

    # ── Node registration ─────────────────────────────────────────────────────

    def register_nodes(self) -> None:
        """Register all 6 domain nodes.

        No super() call — BaseGraph.register_nodes() is abstract. initialize and
        finalize are outer backbone concerns and are not registered here.
        """
        self._nodes["query_parse"] = QueryParseNode()
        self._nodes["document_fetch"] = DocumentFetchNode()
        self._nodes["summarize_generate"] = SummarizeGenerateNode()
        self._nodes["deadline_gate"] = DeadlineGateNode()
        self._nodes["digest_format"] = DigestFormatNode()
        self._nodes["output_format"] = OutputFormatNode()

    # ── Edge wiring ───────────────────────────────────────────────────────────

    def add_edges(self) -> None:
        """Wire the linear 6-node domain pipeline."""
        self._sg.add_edge(START, "query_parse")
        self._sg.add_edge("query_parse", "document_fetch")
        self._sg.add_edge("document_fetch", "summarize_generate")
        self._sg.add_edge("summarize_generate", "deadline_gate")
        self._sg.add_edge("deadline_gate", "digest_format")
        self._sg.add_edge("digest_format", "output_format")
        self._sg.add_edge("output_format", END)

    # ── Routing ───────────────────────────────────────────────────────────────

    def route(self, state: State) -> str:
        """Conditional routing — required by the BaseGraph contract.

        Annotated with this graph's OWN State, not the framework base state. A
        path callable's annotation is read as its input schema and every field
        outside that schema is projected away before the callable sees it, so a
        base-state annotation would hide the domain fields a future branch would
        route on — and the unit suite would still pass, because a directly
        called function receives whatever it is handed.

        The topology is linear today: add_conditional_edges() is not used, so
        this is never called at runtime. It returns END on error so an
        unexpected call cannot re-enter a processing node.
        """
        if state.get("status") in (AgentStatus.ERROR, AgentStatus.ERROR.value):
            return END
        return "output_format"

    # ── Output shape ──────────────────────────────────────────────────────────

    def get_output(self, state: AgentState) -> Dict[str, Any]:
        """Shape the output dict returned to the outer graph as sub_result.

        `output` is the GATED report and nothing else. It deliberately does NOT
        fall back to `assembled_digest`: that field holds the pre-gate assembly,
        and a fallback to it would publish exactly the text the output boundary
        exists to withhold — silently, and on the path where the gate had
        already decided the answer was no. When no gated report exists there is
        nothing to release, and this returns nothing.
        """
        return {
            "output": state.get("result"),
            "status": state.get("status"),
            "trace_id": state.get("trace_id"),
            "correlation_id": state.get("correlation_id"),
            "node_history": state.get("node_history", []),
        }
