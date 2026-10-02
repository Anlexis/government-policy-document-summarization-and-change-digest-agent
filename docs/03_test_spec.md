# Test Specification — GOV-C2-018

## Strategy

| Attribute | Value |
|---|---|
| Test types | unit (contract, gate, per-node, configuration) + boundary (backbone order, real HTTP entry point) |
| Trust level for boundary invokes | `TrustLevel.VERIFIED_EXTERNAL` — never the internal-context shortcut |
| Domain audit emitter | muted per node module by `tests/unit/conftest.py`; framework lifecycle events left alone |

Two rules shape what is asserted:

- **Security tests call the node directly.** A test that asserts "the request was refused" while a
  framework gate sits in front of the node proves the deployment's behaviour, not the template's.
  Where the framework's gate is absent or configured off, the payload would reach the answer path
  and return success — fail-open. So refusal is asserted on `execute()` with nothing in front.
- **Assertions are behavioural.** Status, what was withheld, what was cleared — never a gate's
  exact wording, which changes across framework versions without the behaviour changing.

## Test files

| File | Covers |
|---|---|
| `tests/unit/test_caller_contract.py` | the request contract: accepted shapes, undeclared fields, bounded numbers, injection screen, personal-data screen, request-string parsing |
| `tests/unit/test_output_gate.py` | detector parity with the framework, the digest invariant, the shape of a withheld result |
| `tests/unit/test_nodes.py` | every node's own behaviour, called directly |
| `tests/unit/test_config_manifest.py` | manifest shape and entry-point resolution; runtime config reaching the graph; graph composition |
| `tests/unit/test_framework_compliance_tc06_tc07.py` | the framework's `@final` gate methods cannot be overridden |
| `tests/proof_of_boundary/test_pb_invoke_order.py` | backbone order on a full invoke; per-node call order for every node |
| `tests/proof_of_boundary/test_pb_invoke_endpoint.py` | the real ASGI `/invoke` end to end |
| `tests/proof_of_boundary/test_pb7_hitl_interrupt_propagation.py` | human-review interrupt propagation (skipped: this template does not interrupt) |
| `tests/proof_of_boundary/test_import_isolation.py` | no platform-SDK imports under `src/` |
| `tests/proof_of_boundary/test_state_safety.py` | no credential fields or non-serializable types in State |

## Framework compliance

| Test | Expected |
|---|---|
| State contract | `State` extends `AgentState`; primitives and `Optional[str]` only |
| No credential fields in State | the state-safety scan finds none |
| `InvocationContext` not stored in state | no such field in the State definition |
| No duplicate lifecycle events in `execute()` | `node_start` / `node_complete` / `node_error` are the framework's to emit |
| Input gate not overridden | overriding it raises at class definition |
| Output gate not overridden | overriding it raises at class definition |
| `required_trust_level` declared per node | entry node `VERIFIED_EXTERNAL`; every inner node `ANONYMOUS` |
| External caller admitted end to end | a `VERIFIED_EXTERNAL` invoke completes without the nested graph raising |

## Request contract

| Area | Cases |
|---|---|
| Accepted shapes | empty request; full request; taxonomy ordering independent of caller order; ordinary Japanese policy prose not refused |
| Undeclared fields | refused rather than ignored; the offending name never echoed |
| Field bounds | channel alphabet and length; ministry taxonomy; period alphabet and length; output format enum; document entry cap; per-document field rules |
| Numbers | `NaN`, `Infinity`, `-Infinity` as strings and as floats; `0`; `-1`; `10^9`; `True`; non-numeric strings; `None` — all refused. `1`, `20`, `200`, `"12"`, `12.0` accepted |
| Non-finite via the wire format | the JSON parser accepts the bare literals, so the parsed value is exercised too |
| Injection | `<\|im_start\|>`, `<\|endoftext\|>`, `[INST]`, `<<SYS>>`, directive phrases, executable markup; a directive spliced across tags; a hostile key; an escaped payload; nested structures |
| Injection, other direction | ordinary Japanese and English administrative prose is not flagged |
| Personal data | individual number adjacent to a Japanese label and after an ASCII space; national-id and telephone forms; email; the detected value never echoed |
| Personal data, other direction | Japanese dates, ISO dates, quantities and article numbers carry none |

## Output boundary

| Area | Cases |
|---|---|
| Detector parity | every framework credential shape is blocked; the gate may catch more, never less |
| Local addition | a secret written as an assignment is caught; ordinary prose mentioning the same words is not |
| Digest invariant | the deadline section is recognised in both renderings; a digest without it is not releasable |
| Withholding shape | the replacement notice is non-empty and does not itself trip the gate; clearing covers every report-bearing field |

## Per-node

| Node | Cases |
|---|---|
| PreProcessNode | trust level; a valid request produces a contract; empty and oversized requests refused; injection refused by this node directly; a refusal names the field, not the value; the structured channel wins over the request string; a JSON request string is validated by the same rules |
| QueryParseNode | trust level; contract-selected ministries; ministries named in the request text; unspecified request covers the taxonomy; declared ceiling clamps a larger request; a smaller request honoured; a mis-edited config cannot widen the bounds; declared default rendering; the period label never comes from free text; empty request refused |
| DocumentFetchNode | caller documents used when supplied; absent caller data degrades to the reference corpus; the cap bounds the set; ministry selection filters it; the corpus is handed out as a copy |
| SummarizeGenerateNode | a summary per ministry; changes carry effective dates; action flags; empty document set is an error; structured outputs travel as JSON text |
| DeadlineGateNode | deadlines extracted with their required action; no deadlines is an explicit empty list; one date reported once |
| DigestFormatNode | the deadline section is always present, with and without deadlines; the period label is rendered; a malformed upstream field is an error; cross-ministry dependencies |
| OutputFormatNode | markdown passthrough; plain-text rendering drops decoration but keeps the section; empty assembly releases nothing; a leaking digest is withheld and every carrier field cleared; a digest missing the section is withheld; the error label carries no content |
| PostProcessNode | a clean report is released; an absent report releases nothing; a leaking report is withheld with a non-empty replacement; a report missing the section is withheld; withholding clears the upstream assembly fields |

## Boundary tests through the real entry point

| Area | Cases |
|---|---|
| The public path does real work | health; an authenticated request returns a real digest; the digest depends on the request; the shipped sign-off payload is the one the suite drives |
| Caller data reaches the inner graph | a caller document is digested and appears in the report; absent documents degrade to the reference corpus; a caller cap visibly narrows the digest; the plain-text rendering is reachable; a declared runtime value bounds the digest |
| Authentication | missing token and wrong token both 401 with the same generic body |
| Contract refusals | unusable document caps; a period outside the inert alphabet, not echoed; an undeclared field; a malformed document; injection in the request string and inside a document; an escaped payload; a hostile field name; personal data in a document |
| Adapter guards | oversized structured parameters (413); a credential-shaped value refused by field name (400) without echoing it; ordinary domain text on the same field still passes |
| Output containment | no credential-shaped string anywhere in a response; a violating digest releases nothing — no secret, no digest body, no traceback, no source path; a secret in a title is withheld the same way; and a clean control run that proves the containment assertions are not passing vacuously |

## Backbone order

| Test | Expected |
|---|---|
| Full invoke | status success |
| Backbone order | initialize → pre_process → main → post_process → finalize, in order |
| Output present | the envelope's output key carries the digest |
| Deadline section | present in the released output |
| External caller | admitted through the whole graph |
| Per-node call order | trust gate → node_start → input gate → execute → output gate → node_complete, for every node under `src/nodes/` |
