"""AgentCore Platform v1.0"""

# GOV-C2-018 — Government Policy Document Summarization & Change Digest Agent
#
# Two-layer nested design:
#
#   Outer backbone (fixed — add_edges() is NOT overridden):
#     initialize -> pre_process -> main -> {route} -> post_process -> finalize
#
#   The `main` slot is PolicyDigestGraphNode, which delegates the whole domain
#   workflow to DomainWorkflowGraph:
#     query_parse -> document_fetch -> summarize_generate
#                 -> deadline_gate -> digest_format -> output_format
#
# Directory layout:
#   src/graph/graph.py                 <- outer graph (this file)
#   src/graph/domain_workflow_graph.py <- inner graph (the domain pipeline)
#   src/graph/context_bridge.py        <- validated request contract across the boundary
#
# Class-name contract:
#   graph.py class:           GovernmentPolicyDigestAgent (this file)
#   config/agent.yaml class:  "src.graph.graph.GovernmentPolicyDigestAgent"
#   src/api/server.py import: from src.graph.graph import GovernmentPolicyDigestAgent

from pathlib import Path
from typing import Any, ClassVar, Dict

from framework.graph.agent_base_graph import AgentBaseGraph
from framework.nodes.graph_node import GraphNode
from framework.schemas.trust_level import TrustLevel
from framework.schemas.agent_state import AgentState
from framework.utils.config_loader import load_agent_config
from src.graph.context_bridge import set_request_contract
from src.nodes.post_process_node import PostProcessNode
from src.nodes.pre_process_node import PreProcessNode
from src.schemas.state import State, from_json

# Repo root: src/graph/graph.py -> parents[2].
_REPO_ROOT = Path(__file__).resolve().parents[2]

# Mirrors config/config.yaml so the digest tuning is never empty even where the
# config file is unreadable in an exotic deployment layout.
_FALLBACK_DIGEST: Dict[str, Any] = {
    "max_documents_limit": 20,
    "default_output_format": "markdown",
}


def runtime_config() -> Dict[str, Any]:
    """Load config/config.yaml — the live runtime parameters.

    The registry loads this file and passes it to the graph constructor; the
    standalone HTTP entry point does the same, so the retry budget and the
    digest tuning are live in both deployments rather than declared and ignored.

    Reading the static manifest (config/agent.yaml) here instead would return
    nothing: the manifest carries identity and compile-time requirements only,
    and a reader pointed at it degrades silently to defaults.
    """
    loaded = load_agent_config(_REPO_ROOT)
    return dict(loaded) if isinstance(loaded, dict) else {}


class PolicyDigestGraphNode(GraphNode):
    """The `main` slot: wraps the inner policy-digest workflow.

    Contracts:
      get_subgraph()  - instantiate DomainWorkflowGraph with the forwarded
                        runtime config (_parent_config())
      extract_input() - hand the request string to the inner graph and stash the
                        validated contract on the bridge
      merge_output()  - map sub_result fields into the outer state delta
      error_strategy  - "propagate": re-raise inner errors (fail fast)
    """

    # S-1 declared on the wrapper too: the CI gate only AST-scans FunctionNode
    # subclasses, so a GraphNode main slot passes the pipeline without one and is
    # flagged at review. Same level the nodes in this repo already declare.
    required_trust_level: ClassVar[TrustLevel] = TrustLevel.VERIFIED_EXTERNAL

    error_strategy: ClassVar[str] = "propagate"

    # False: human-review interrupts are handled inside the inner graph only.
    propagate_hitl: ClassVar[bool] = False

    def _parent_config(self) -> Dict[str, Any]:
        """Forward the live `digest` tuning to the inner graph.

        Returns the tuning block under config["configurable"] — never an empty
        dict. The inner graph republishes it into inner state
        (DomainWorkflowGraph._extra_initial_state()) so the parse node reads the
        live document cap and default format: node execute() methods take no
        config parameter, so state seeding is the only route config can travel.
        """
        digest = runtime_config().get("digest")
        if not isinstance(digest, dict) or not digest:
            digest = dict(_FALLBACK_DIGEST)
        return {"configurable": {"digest": digest}}

    def get_subgraph(self) -> Any:
        """Instantiate and return the inner domain workflow graph.

        Imported inside the method to avoid circular-import risk at module load
        time. The inner graph receives the runtime-derived config through its
        constructor; its domain nodes still take no constructor arguments and
        read config per call from seeded state.
        """
        from src.graph.domain_workflow_graph import DomainWorkflowGraph

        return DomainWorkflowGraph(config=self._parent_config())

    def extract_input(self, state: AgentState) -> str:
        """Return the request string, and bridge the validated contract.

        The framework hands only a string to the inner graph, so the structured
        part of the request travels on the bridge instead — set here, one step
        before the inner invoke, and read by the inner graph's initial-state
        hook. Only the contract the pre_process node already validated crosses.
        """
        set_request_contract(from_json(state.get("request_contract"), {}) or {})
        return str(state.get("validated_input") or state.get("user_input", ""))

    def merge_output(self, state: AgentState, sub_result: Dict[str, Any]) -> Dict[str, Any]:
        """Map the inner result back into the outer state delta (changed keys only).

        Key coupling, designed together with DomainWorkflowGraph.get_output():

          Inner get_output() emits  -> "output", "status", ...
          This merge_output() reads -> the same two keys

        `output` carries the GATED report only. The inner graph deliberately
        does not fall back to its pre-gate assembly field, so there is no path
        by which ungated text can arrive here.
        """
        return {
            "result": sub_result.get("output"),
            "status": sub_result.get("status"),
        }


class GovernmentPolicyDigestAgent(AgentBaseGraph):
    """GOV-C2-018 Government Policy Document Summarization & Change Digest Agent.

    Inherits AgentBaseGraph directly. Domain logic is fully encapsulated in
    PolicyDigestGraphNode (main slot), which delegates to DomainWorkflowGraph.

    register_nodes() is the ONLY topology override:
      - super().register_nodes() fills: initialize, finalize (framework defaults)
      - pre_process:  PreProcessNode (trust boundary + caller-contract validation)
      - main:         PolicyDigestGraphNode (delegates to DomainWorkflowGraph)
      - post_process: PostProcessNode (output boundary)
    """

    @property
    def name(self) -> str:
        return "GovernmentPolicyDigestAgent"

    @property
    def state_schema(self) -> type:
        return State

    def register_nodes(self) -> None:
        """Fill all 5 backbone slots.

        super().register_nodes() MUST be called first — it injects the
        framework's default initialize node (schema version, session id, trust
        level) and finalize node (response metadata, total elapsed time).
        """
        super().register_nodes()  # fills: initialize, finalize
        self._nodes["pre_process"] = PreProcessNode()
        self._nodes["main"] = PolicyDigestGraphNode()
        self._nodes["post_process"] = PostProcessNode()

    # add_edges() is NOT overridden — backbone wiring belongs to the framework.


# The manifest names the class by dotted path and src/api/server.py imports it
# directly. Keep both names pointing at the agent.
Graph = GovernmentPolicyDigestAgent
