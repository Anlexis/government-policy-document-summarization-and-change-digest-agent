# GOV-C2-018 Design Specification

## Position in the AgentCore architecture

| Field | Value |
|---|---|
| **Agent Class** | `GovernmentPolicyDigestAgent` |
| L1 Base (framework base class) | `AgentBaseGraph` — direct framework inheritance |
| **Pattern** | Cat 2 — nested graph (outer backbone + inner `DomainWorkflowGraph`) |
| **Industry** | GOV — government / municipal policy analysis |
| **Template ID** | `GOV-C2-018` |

## Architecture overview

```
Outer (AgentBaseGraph — src/graph/graph.py):
  InitializeNode          [framework default]
  PreProcessNode          [VERIFIED_EXTERNAL — trust boundary + request contract]
  PolicyDigestGraphNode   [GraphNode — main slot, wraps the inner graph]
  PostProcessNode         [ANONYMOUS — output boundary, produces formatted_output]
  FinalizeNode            [framework default]

Inner (BaseGraph — src/graph/domain_workflow_graph.py):
  QueryParseNode          [ANONYMOUS — resolves the digest parameters]
  DocumentFetchNode       [ANONYMOUS — selects the document set, bounded]
  SummarizeGenerateNode   [ANONYMOUS — per-ministry summaries + dated changes]
  DeadlineGateNode        [ANONYMOUS — compliance-deadline collection]
  DigestFormatNode        [ANONYMOUS — digest assembly + cross-ministry links]
  OutputFormatNode        [ANONYMOUS — rendering + output boundary]
```

### Node configuration

| Node | Slot | Location | required_trust_level | Responsibility |
|---|---|---|---|---|
| InitializeNode | initialize | framework | — | schema version, session id, trust level |
| PreProcessNode | pre_process | src/nodes/ | **VERIFIED_EXTERNAL** | trust boundary; validates the caller contract; emits `request_contract` |
| PolicyDigestGraphNode | main | src/graph/graph.py | (GraphNode default) | forwards runtime config, bridges the contract, merges the inner result |
| PostProcessNode | post_process | src/nodes/ | ANONYMOUS | output boundary; releases or withholds |
| FinalizeNode | finalize | framework | — | response metadata, total elapsed time |
| QueryParseNode | query_parse | src/nodes/ | **ANONYMOUS** | ministries, period label, document cap, output format |
| DocumentFetchNode | document_fetch | src/nodes/ | **ANONYMOUS** | caller documents when supplied, reference corpus otherwise; bounded |
| SummarizeGenerateNode | summarize_generate | src/nodes/ | **ANONYMOUS** | per-ministry summaries; regulatory changes with effective dates; flags |
| DeadlineGateNode | deadline_gate | src/nodes/ | **ANONYMOUS** | every compliance deadline, always an explicit list |
| DigestFormatNode | digest_format | src/nodes/ | **ANONYMOUS** | digest assembly; cross-ministry dependencies |
| OutputFormatNode | output_format | src/nodes/ | **ANONYMOUS** | rendering per output format; output boundary |

> **Inner nodes declare ANONYMOUS, not INTERNAL.** `GraphNode` passes the outer
> `InvocationContext` into the subgraph unchanged. A real external caller arrives
> `VERIFIED_EXTERNAL`; an inner node demanding `INTERNAL` would deny it, the nested graph would
> raise, and the backbone would skip the output slot. `ANONYMOUS` admits the caller the entry
> node already vetted.

### Data flow

```
POST /invoke  { input, session_id, input_context }
  → adapter: Bearer-token trust promotion, size cap, credential screen on input_context
  → InitializeNode
  → PreProcessNode (VERIFIED_EXTERNAL)
       validated_input   = the request string
       request_contract  = the validated caller contract (JSON text)
       enriched_context  = {source, channel}
  → PolicyDigestGraphNode
       _parent_config()  → the live `digest` block from config/config.yaml
       extract_input()   → stashes request_contract on the bridge, returns the request string
       [inner: DomainWorkflowGraph]
         _extra_initial_state() → seeds digest_config + request_contract into inner state
         QueryParseNode        → ministries, reporting_period, max_documents, output_format
         DocumentFetchNode     → fetched_documents, document_source
         SummarizeGenerateNode → per_ministry_summaries, regulatory_changes, operational_flags
         DeadlineGateNode      → deadline_highlights  (always an explicit list)
         DigestFormatNode      → assembled_digest, cross_ministry_dependencies
         OutputFormatNode      → result               (gated)
       merge_output()    → result, status → outer state
  → PostProcessNode (ANONYMOUS)
       result → formatted_output  (gated a second time)
  → FinalizeNode
```

## Runtime configuration

Two files, two jobs:

| File | Read by | Carries |
|---|---|---|
| `config/agent.yaml` | the agent registry, at discovery | identity, entry point, required trust level, compile-time requirements |
| `config/config.yaml` | the registry and `src/api/server.py`, at construction | `max_retry`, `timeout_s`, and the `digest` block |

The `digest` block reaches the domain nodes by being forwarded through
`PolicyDigestGraphNode._parent_config()` and republished into inner state by
`DomainWorkflowGraph._extra_initial_state()`. Node `execute()` methods take no config parameter,
so seeded state is the only route runtime configuration can travel.

| Key | Effect |
|---|---|
| `digest.max_documents_limit` | ceiling on how many documents one digest covers; a larger caller request is clamped to it |
| `digest.default_output_format` | rendering used when the caller names none |

A reader pointed at `config/agent.yaml` for these values would get an empty mapping and degrade
silently to defaults, which is why the loader reads the runtime file explicitly.

## Request contract

`src/services/caller_contract.py` owns everything a caller may send.

| Field | Rule |
|---|---|
| `channel` | inert identifier, `[a-z0-9_]{1,32}` |
| `ministries` | subset of the closed taxonomy; re-ordered to the taxonomy's own order |
| `reporting_period` | inert alphabet `[0-9A-Za-z_/-]{1,32}` — it is printed in the report |
| `output_format` | `markdown` or `email` |
| `max_documents` | finite integer, 1–200, through a bounded parser |
| `documents` | ≤ 40 entries; each `{ministry, title, date, content}` bounded and screened |

Rules that are easy to get wrong and are therefore explicit:

- **An undeclared field is refused, not ignored.** Ignoring a key still carries it into the run.
- **Numbers go through a finite, bounded parser.** NaN and Infinity both survive `float()`, and
  every comparison against NaN is False, so a range check written the obvious way stops applying
  exactly when a hostile value arrives. A bool is not a number either — a bool IS an int in
  Python, so `max_documents: true` would otherwise be read as 1.
- **Instruction-injection screening covers chat-template control tokens as a class** — `<|…|>`,
  `[INST]`, `<<SYS>>` — and runs on the raw string and the markup-stripped string, so a directive
  spliced across tags is caught after the strip re-assembles it. Keys are screened as well as
  values, after parsing.
- **Personal-data screening is written without a word-boundary assertion.** That assertion is
  computed from the word-character class, which includes Kanji and Kana, so a guarded pattern
  finds nothing between a Japanese label and the digits that follow it. Explicit "not a digit"
  lookarounds hold on both alphabets.
- **A refusal names the field and a fixed reason label**, never the value and never the matched
  text.

The HTTP adapter additionally screens `input_context` for credential shapes with the framework's
own detector before `invoke()`. The reason is mechanical: the backbone's first node copies the
structured parameters verbatim into its own result, and the framework's output gate scans every
value of every result — so a credential-shaped string there fails the FIRST node with nothing the
caller can act on. The request cannot succeed either way; refusing it at the adapter turns an
opaque failure into a named one.

## Output boundary

Two gate points — `OutputFormatNode` inside the pipeline and `PostProcessNode` on the backbone —
both calling the one implementation in `src/services/output_gate.py`. One implementation rather
than two rule sets, because a local set narrower than the framework's is not a smaller gate: the
value reaches a node whose own gate then raises, and a raising node's whole result is discarded
along with any clearing it performed.

The gate checks two things:

1. **Leakage** — credential shapes via the framework's own `detect_credentials`, plus a
   written-down-secret form (`password: …`) that value-shaped patterns do not recognise, plus the
   personal-data categories above.
2. **The digest invariant** — the compliance-deadline section is present. It is emitted for every
   period, with an explicit "none this period" line when there are none, so its absence means the
   digest is malformed rather than that the period was quiet.

On a violation the node returns an error status, replaces the report with a **non-empty** notice,
and **clears every state field that carries report text**. All three matter together: the output
envelope reads the gated field first and falls back to the ungated one, so an error that leaves
the digest in state ships it anyway, and a falsy replacement re-opens the same fallback.

A withheld run reaching the caller carries an error status and no digest text: the nested graph's
result is discarded wholesale on a non-success status, so nothing from the inner pipeline —
including the notice — crosses the boundary.

### On the numeric-precision grid

Some templates in this family enforce a rounding grid on monetary aggregates at the output
boundary. **This template renders no monetary aggregates** — the digest carries ministry names,
document titles, effective dates, required actions and counts — so that grid is not applicable
here, and adding it would be actively harmful: its grammar reads any standalone three-letter
uppercase word as a currency marker and would rewrite document identifiers and quantities such as
`1,500kl` in ministry notices. The invariant this template enforces instead is the deadline
section above.

## State definition

`src/schemas/state.py` extends `AgentState` (flat TypedDict). Dict and list fields are typed
`Optional[str]` and travel as JSON text via `to_json()` / `from_json()`.

| Field | Type | Producer | Consumer |
|---|---|---|---|
| `validated_input` | `Optional[str]` | PreProcessNode | PolicyDigestGraphNode.extract_input |
| `request_contract` | `Optional[str]` | PreProcessNode | QueryParseNode, DocumentFetchNode |
| `enriched_context` | `Optional[str]` | PreProcessNode | — |
| `digest_config` | `Optional[str]` | DomainWorkflowGraph._extra_initial_state | QueryParseNode |
| `ministries` | `Optional[str]` | QueryParseNode | DocumentFetchNode, DigestFormatNode |
| `reporting_period` | `Optional[str]` | QueryParseNode | DigestFormatNode |
| `max_documents` | `Optional[int]` | QueryParseNode | DocumentFetchNode |
| `output_format` | `Optional[str]` | QueryParseNode | OutputFormatNode |
| `document_source` | `Optional[str]` | QueryParseNode, DocumentFetchNode | — |
| `fetched_documents` | `Optional[str]` | DocumentFetchNode | SummarizeGenerateNode, DeadlineGateNode |
| `per_ministry_summaries` | `Optional[str]` | SummarizeGenerateNode | DigestFormatNode |
| `regulatory_changes` | `Optional[str]` | SummarizeGenerateNode | DeadlineGateNode, DigestFormatNode |
| `operational_flags` | `Optional[str]` | SummarizeGenerateNode | DigestFormatNode |
| `deadline_highlights` | `Optional[str]` | DeadlineGateNode | DigestFormatNode |
| `assembled_digest` | `Optional[str]` | DigestFormatNode | OutputFormatNode |
| `cross_ministry_dependencies` | `Optional[str]` | DigestFormatNode | — |
| `result` | `Optional[str]` | OutputFormatNode → merge_output | PostProcessNode |
| `formatted_output` | `Optional[str]` | PostProcessNode | caller |

> **State constraints:** flat TypedDict only — no Pydantic, dataclass or arbitrary objects;
> no credentials or secrets in state; `InvocationContext` via `config["configurable"]`, never
> stored in state.

## Graph contracts

### PolicyDigestGraphNode

| Method | Implementation |
|---|---|
| `_parent_config()` | `{"configurable": {"digest": runtime_config()["digest"]}}` — never an empty mapping |
| `get_subgraph()` | `DomainWorkflowGraph(config=self._parent_config())` |
| `extract_input(state)` | stashes `request_contract` on the bridge; returns `validated_input` |
| `merge_output(state, sub_result)` | `{"result": sub_result["output"], "status": sub_result["status"]}` |

### DomainWorkflowGraph.get_output(state)

```python
return {
    "output":         state.get("result"),   # the GATED report, with no fallback
    "status":         state.get("status"),
    "trace_id":       state.get("trace_id"),
    "correlation_id": state.get("correlation_id"),
    "node_history":   state.get("node_history", []),
}
```

`output` deliberately does not fall back to `assembled_digest`. That field holds the pre-gate
assembly, and a fallback to it would publish exactly the text the boundary withheld — on the path
where the gate had already decided the answer was no.

`route()` is annotated with this graph's own `State`. A path callable's annotation is read as its
input schema and every field outside it is projected away before the callable sees it, so a
base-state annotation would hide the domain fields a future branch would route on while the unit
suite stayed green.

## Ministry taxonomy

| Code | Ministry |
|---|---|
| 厚労省 | 厚生労働省 — Ministry of Health, Labour and Welfare |
| 国交省 | 国土交通省 — Ministry of Land, Infrastructure, Transport and Tourism |
| 経産省 | 経済産業省 — Ministry of Economy, Trade and Industry |
| 金融庁 | 金融庁 — Financial Services Agency |

## Import isolation

- The template does not import the platform SDK.
- Import targets are `framework.*` and `shared.*` only.
- No imports from other agents.

## Class-name consistency

| Artifact | Value |
|---|---|
| `src/graph/graph.py` | `class GovernmentPolicyDigestAgent(AgentBaseGraph)` |
| `config/agent.yaml` | `class: "src.graph.graph.GovernmentPolicyDigestAgent"` |
| `src/api/server.py` | `from src.graph.graph import GovernmentPolicyDigestAgent` |
