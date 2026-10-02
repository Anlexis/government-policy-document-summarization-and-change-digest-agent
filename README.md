# GOV-C2-018 — GovernmentPolicyDigestAgent

> **Category**: Cat 2 (domain-specific document-generation pipeline)
> **Industry**: GOV

## Overview

Turns a week of ministry policy documents into one email-ready digest.

The agent takes a set of ministries and a reporting period, works through the documents for that
period — the caller's own, or the built-in reference set — and produces a per-ministry summary,
the regulatory changes with their effective dates, the operational-impact flags, and the
dependencies that span more than one ministry.

Its defining behaviour is the compliance-deadline section: every released digest carries it, even
when the period held no deadlines, in which case it says so explicitly. A deadline can never be
summarised away quietly, and a reader never has to work out whether an absent section means
"nothing happened" or "the step did not run". The output boundary enforces that as an invariant —
a digest that reaches it without the section is withheld rather than released.

This is an agent template built with the **AGENTIC STAR** development platform and the
**AgentCore Framework**. It is intended to be taken as a starting point: fork it, adapt it to
your own data and policies, and run it inside your own AGENTIC STAR deployment.

## Requirements

**This template does not run standalone.** It requires:

| Requirement | Notes |
|---|---|
| **AGENTIC STAR platform** | The agent connects to the platform at start-up. Without it, start-up fails immediately (see *Behaviour without the platform* below). Deployment guides and API documentation: [AGENTIC STAR Developers](https://developers.fd.agenticstar.tm.softbank.jp/) |
| **AgentCore Framework** (`agenticstar-agentcore`) | Installed from PyPI as a dependency. |
| Python | >=3.11 |

```bash
pip install -e .
```

### Behaviour without the platform

The framework is designed to run **only** on AGENTIC STAR. There is no fallback or degraded
mode. If the platform is unreachable or the SDK version does not match, the agent fails at graph
compile / start-up preflight rather than starting in a partially working state. This is
intentional — a half-running agent is worse than one that refuses to start.

## Quick Start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
python -m pytest tests/ -v
```

Tests run without a platform connection. Running the agent itself does not.

## Sending a request

The standalone entry point exposes `POST /invoke`. The request string carries the request in
prose; the structured parameters travel on `input_context`:

```json
{
  "input": "厚労省と国交省の今週の政策文書ダイジェストを作成してください。",
  "input_context": {
    "ministries": ["厚労省", "国交省"],
    "reporting_period": "2026-06-23/2026-06-30",
    "output_format": "markdown",
    "max_documents": 4,
    "documents": [
      {
        "ministry": "厚労省",
        "title": "労働安全衛生法施行規則改正通達",
        "date": "2026-06-25",
        "content": "2026年9月1日を施行日として…"
      }
    ]
  }
}
```

Every field is optional. Send no documents and the built-in reference set is digested instead, so
a request with no data still returns a complete, fully shaped digest rather than an empty one.

Each field is bounds-checked before anything downstream reads it: ministries against the closed
taxonomy, `reporting_period` against an inert alphabet because it is printed in the report,
`max_documents` through a finite range check, and document bodies against instruction-injection
forms and personal data. A value outside the contract is refused with the field named and the
value never repeated back.

When `INVOKE_AUTH_TOKEN` is set on the server environment, callers that no upstream middleware
vouched for must present it as `Authorization: Bearer <token>`.

## Project Structure

```
src/          agent implementation (nodes, services, schemas)
tests/        unit and boundary tests
config/       agent manifest (agent.yaml) and runtime parameters (config.yaml)
docs/         design and test documentation
```

See `docs/02_design.md` for the architecture and `docs/03_test_spec.md` for the test coverage.

## Customising

1. Adjust `config/config.yaml` for your own environment — the document ceiling and the default
   rendering are read from it at run time.
2. Replace the reference document set in `src/nodes/document_fetch_node.py` with your own source,
   or send documents on `input_context`.
3. Adapt the ministry taxonomy and the request bounds in `src/services/caller_contract.py`.
4. Re-run the test suite.

## License

MIT — see [LICENSE](LICENSE).

## Status of this repository

This template is published **as is**, by its individual author, under the MIT license. It carries
**no warranty and no support commitment**, and no organisation stands behind its behaviour or
fitness for any purpose. Issues and pull requests may or may not receive a response; that is at
the sole discretion of the repository owner.
