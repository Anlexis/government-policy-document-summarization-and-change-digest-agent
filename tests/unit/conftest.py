# Unit-test fixtures.
#
# Mutes the domain audit emitter in every src.nodes module. The framework
# imports its own security package at load time, so stubbing that package in
# sys.modules would break collection — instead each node module's already
# imported emit_trace_event reference is monkeypatched to a no-op. A test that
# asserts on the audit payload re-patches the same module attribute with its
# own spy, and the later patch wins for that test.
#
# The framework's OWN lifecycle events are left untouched — they are
# fire-and-forget log lines and part of the behaviour under test.
#
# Scope: this fixture only applies to tests collected under tests/unit/ —
# tests/proof_of_boundary/ is a sibling directory and is unaffected.

import pytest

import src.nodes.deadline_gate_node
import src.nodes.digest_format_node
import src.nodes.document_fetch_node
import src.nodes.output_format_node
import src.nodes.post_process_node
import src.nodes.pre_process_node
import src.nodes.query_parse_node
import src.nodes.summarize_generate_node

_AUDITED_NODE_MODULES = (
    src.nodes.deadline_gate_node,
    src.nodes.digest_format_node,
    src.nodes.document_fetch_node,
    src.nodes.output_format_node,
    src.nodes.post_process_node,
    src.nodes.pre_process_node,
    src.nodes.query_parse_node,
    src.nodes.summarize_generate_node,
)


@pytest.fixture(autouse=True)
def mute_domain_audit(monkeypatch):
    """Silence the domain audit emitter in every node module."""
    for module in _AUDITED_NODE_MODULES:
        monkeypatch.setattr(module, "emit_trace_event", lambda *args, **kwargs: None)
