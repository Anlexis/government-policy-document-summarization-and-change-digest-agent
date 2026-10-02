# The manifest and the runtime config are two different files with two different
# jobs, and the failure they used to share was silent: a reader pointed at the
# wrong one gets an empty mapping, every declared value degrades to a default,
# and nothing anywhere reports it.

import pathlib

import pytest

yaml = pytest.importorskip("yaml")

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_MANIFEST = _REPO_ROOT / "config" / "agent.yaml"
_CONFIG = _REPO_ROOT / "config" / "config.yaml"


def _load(path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


class TestManifest:
    def test_every_key_is_at_the_root(self):
        """The registry reads each key at root level; a nested block reads as
        absent."""
        manifest = _load(_MANIFEST)
        assert "agent" not in manifest
        for key in ("id", "name", "namespace", "version", "category", "industry", "class"):
            assert key in manifest

    def test_the_entry_point_is_a_dotted_path_that_resolves(self):
        """The published entry point has to import. A module-plus-class pair
        that names a module which does not re-export the class resolves to
        nothing, and the container never starts."""
        import importlib

        dotted = _load(_MANIFEST)["class"]
        module_path, _, class_name = dotted.rpartition(".")
        module = importlib.import_module(module_path)
        assert isinstance(getattr(module, class_name), type)

    def test_the_declared_trust_level_is_the_one_the_entry_node_requires(self):
        from framework.schemas.trust_level import TrustLevel
        from src.nodes.pre_process_node import PreProcessNode

        declared = _load(_MANIFEST)["required_trust_level"]
        assert TrustLevel[declared] == PreProcessNode.required_trust_level

    def test_no_secret_or_extra_is_declared_that_the_code_does_not_use(self):
        """A declared secret that is not provisioned fails the agent at compile
        time, so the declaration has to track the code."""
        manifest = _load(_MANIFEST)
        assert manifest["requires"]["secrets"] == []
        assert manifest["requires"]["extras"] == []
        sources = "\n".join(path.read_text(encoding="utf-8") for path in (_REPO_ROOT / "src").rglob("*.py"))
        assert "secrets.require(" not in sources


class TestRuntimeConfig:
    def test_the_runtime_loader_reads_the_runtime_file(self):
        from src.graph.graph import runtime_config

        assert runtime_config() == _load(_CONFIG)

    def test_the_declared_values_are_present_and_typed(self):
        config = _load(_CONFIG)
        assert isinstance(config["max_retry"], int)
        assert isinstance(config["timeout_s"], int)
        assert isinstance(config["digest"]["max_documents_limit"], int)
        assert config["digest"]["default_output_format"] in ("markdown", "email")

    def test_the_digest_block_is_forwarded_to_the_inner_graph(self):
        from src.graph.graph import PolicyDigestGraphNode

        forwarded = PolicyDigestGraphNode()._parent_config()["configurable"]["digest"]
        assert forwarded == _load(_CONFIG)["digest"]

    def test_the_inner_graph_seeds_the_forwarded_block_into_state(self):
        """Node execute() methods take no config parameter, so seeded state is
        the only route runtime config can reach them."""
        import json

        from src.graph.domain_workflow_graph import DomainWorkflowGraph

        graph = DomainWorkflowGraph(config={"configurable": {"digest": {"max_documents_limit": 7}}})
        seeded = graph._extra_initial_state()
        assert json.loads(seeded["digest_config"])["max_documents_limit"] == 7

    def test_the_backbone_receives_the_retry_budget(self):
        from src.graph.graph import GovernmentPolicyDigestAgent, runtime_config

        agent = GovernmentPolicyDigestAgent(config=runtime_config())
        assert agent.config["max_retry"] == _load(_CONFIG)["max_retry"]


class TestGraphComposition:
    def test_the_backbone_slots_are_filled(self):
        from src.graph.graph import GovernmentPolicyDigestAgent, PolicyDigestGraphNode
        from src.nodes.post_process_node import PostProcessNode
        from src.nodes.pre_process_node import PreProcessNode

        agent = GovernmentPolicyDigestAgent()
        agent.register_nodes()
        assert isinstance(agent._nodes["pre_process"], PreProcessNode)
        assert isinstance(agent._nodes["main"], PolicyDigestGraphNode)
        assert isinstance(agent._nodes["post_process"], PostProcessNode)
        assert agent._nodes["initialize"] is not None
        assert agent._nodes["finalize"] is not None

    def test_the_inner_output_never_falls_back_to_the_pre_gate_assembly(self):
        """The assembly field holds ungated text. A fallback to it publishes
        exactly what the boundary withheld, on the path where the answer was
        already no."""
        from src.graph.domain_workflow_graph import DomainWorkflowGraph

        graph = DomainWorkflowGraph()
        output = graph.get_output({"assembled_digest": "UNGATED ASSEMBLY", "status": "error"})
        assert output["output"] is None

    def test_the_route_callable_is_annotated_with_this_graphs_own_state(self):
        """A path callable's annotation is read as its input schema and every
        field outside it is projected away before the callable sees it."""
        import typing

        from src.graph.domain_workflow_graph import DomainWorkflowGraph
        from src.schemas.state import State

        hints = typing.get_type_hints(DomainWorkflowGraph.route)
        assert hints["state"] is State

    def test_the_bridge_carries_the_validated_contract_across_the_boundary(self):
        """The framework hands only a string to a nested graph, so nothing
        structured crosses on its own."""
        import json

        from src.graph.context_bridge import get_request_contract
        from src.graph.graph import PolicyDigestGraphNode

        node = PolicyDigestGraphNode()
        contract = {"ministries": ["厚労省"], "reporting_period": "past_week"}
        request = node.extract_input(
            {"validated_input": "digest please", "request_contract": json.dumps(contract, ensure_ascii=False)}
        )
        assert request == "digest please"
        assert get_request_contract() == contract
