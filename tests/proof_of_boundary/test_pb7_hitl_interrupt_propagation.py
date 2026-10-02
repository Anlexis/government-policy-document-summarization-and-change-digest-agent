# PB-7: human-review interrupt propagation.
#
# A human-review interrupt raised inside the graph must reach the caller intact,
# so an orchestrator can pause the run, collect a decision, and resume it. That
# behaviour only exists for templates that opt into it: the run has to be
# checkpointed, which is what `hitl.enabled: true` in config/config.yaml turns on.
#
# This template does not opt in. It produces a digest in one pass, with no point
# at which a human decision is required mid-run, and its main-slot graph node
# declares that interrupts are handled inside the inner graph rather than
# propagated. So there is no propagation behaviour to assert here.
#
# The module still ships, importable and keyed on the configuration rather than
# on a comment: enable checkpointing and these tests stop skipping, which is the
# signal to implement the real assertions.

from __future__ import annotations

import pathlib
import warnings

import pytest

_CONFIG_PATH = pathlib.Path(__file__).parents[2] / "config" / "config.yaml"


def _hitl_enabled() -> bool:
    """Return True when config/config.yaml declares hitl.enabled: true.

    An absent or unreadable config file warns instead of skipping silently —
    either case is ambiguous (never shipped / broken vs. genuinely not
    applicable) and should not look like a clean auto-waiver.
    """
    if not _CONFIG_PATH.exists():
        warnings.warn(
            f"{_CONFIG_PATH} not found — PB-7 skipped without verifying hitl.enabled. "
            "If this template suspends for human review, ship config/config.yaml before release.",
            stacklevel=2,
        )
        return False
    try:
        import yaml

        data = yaml.safe_load(_CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        warnings.warn(
            f"{_CONFIG_PATH} could not be read as YAML ({exc}) — PB-7 skipped without "
            "verifying hitl.enabled. If this template suspends for human review, fix "
            "config/config.yaml before release.",
            stacklevel=2,
        )
        return False
    hitl = (data or {}).get("hitl", {}) if isinstance(data, dict) else None
    if not isinstance(hitl, dict):
        warnings.warn(
            f"{_CONFIG_PATH} does not have the expected 'hitl:' mapping shape — PB-7 skipped "
            "without verifying hitl.enabled. If this template suspends for human review, fix "
            "config/config.yaml before release.",
            stacklevel=2,
        )
        return False
    return bool(hitl.get("enabled", False))


_SKIP_REASON = (
    "config/config.yaml does not enable human-review checkpointing — this template "
    "runs to completion in one pass, so there is no interrupt to propagate"
)

pytestmark = pytest.mark.skipif(not _hitl_enabled(), reason=_SKIP_REASON)


def test_hitl_interrupt_propagates_to_the_caller() -> None:
    """The interrupt reaches the runtime rather than being caught as an error.

    Reached only once checkpointing is enabled: drive the node that suspends
    through its call wrapper and assert the interrupt surfaces, with the run's
    status left un-errored.
    """
    pytest.fail("PB-7 is enabled in configuration but its assertion has not been implemented")


def test_a_run_that_disallows_human_review_does_not_suspend() -> None:
    """The guard direction: with human review disallowed, the same trigger runs
    to completion instead of suspending, so a caller that cannot answer an
    interrupt never deadlocks.
    """
    pytest.fail("PB-7 is enabled in configuration but its assertion has not been implemented")
