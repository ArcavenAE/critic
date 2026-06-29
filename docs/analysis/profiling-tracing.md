# Direction: profiling & tracing Claude Code factories (frontier)

> Pre-implementation. Captured session-052 (2026-06-29) from a user direction:
> "investigate techniques for conducting performance profiling and tracing of
> Claude Code-based plugins, skills, commands, etc — including research."
> This is the instrumentation half of critic's measurement mandate: §global-telemetry
> says *what* to pool across a team; this says *how* to capture per-component
> timing/token/cost data from a Claude Code factory in the first place.
>
> Two parallel research strands fed this (both primary-sourced, gaps flagged):
> (A) Claude Code's native instrumentation surface; (B) the SOTA in LLM-agent
> profiling/tracing methodology. Every load-bearing claim carries its source.
> Stability caveats are inline — most of this surface is pre-stable and moving.

## Why this is critic's, not beadle's

Profiling is measurement across runs and components — the finding-008 tell
(beadle finding-010 §0). beadle classifies per-artifact and surfaces gaps (it
already surfaced the attribution gap, finding-007 / #324); critic owns capturing
and aggregating timing/token/cost. This doc is the instrumentation design critic
builds against. It composes onto `global-telemetry.md` (the team-pooling
direction) and `boundary-beadle.md` (the class-weighting coupling).

---

## Part A — Claude Code's native instrumentation surface (what we can actually tap)

Source of record: the official docs at `code.claude.com/docs/en/` —
`monitoring-usage`, `hooks`, `statusline`, `sessions`, `skills`, `sub-agents`,
`mcp`, `commands`. **Stability caveat carried throughout:** several of the
richest surfaces (enhanced-telemetry spans, the JSONL transcript schema) are
explicitly version-internal or beta-gated and *will* break across releases.
Isolate every parser/mapping behind an adapter.

### A1. OpenTelemetry — the primary always-on tap

`CLAUDE_CODE_ENABLE_TELEMETRY=1` turns on three signal classes:

**Metrics** (60 s export default, `OTEL_METRIC_EXPORT_INTERVAL`; exporters
`otlp`/`prometheus`/`console`/`none`):
- `claude_code.session.count`, `claude_code.active_time.total`,
  `claude_code.lines_of_code.count`, `claude_code.commit.count`,
  `claude_code.pull_request.count`, `claude_code.code_edit_tool.decision`
- `claude_code.cost.usage` (USD) and `claude_code.token.usage` — **and these
  carry the per-component attribution we need**: attributes include `model`,
  `query_source` (main / subagent / auxiliary), `agent.name`, **`skill.name`**,
  `mcp_server.name`, `mcp_tool.name`, plus `type` (input/output/cacheRead/
  cacheCreation) on token.usage.

**Logs / events** (5 s export): `user_prompt`, `tool_call`, `tool_result`,
`api_request`/`api_request_body`, `api_response_body`, `gen_ai.request.attempt`
(per retry). Content fields are gated behind opt-in env vars
(`OTEL_LOG_USER_PROMPTS`, `OTEL_LOG_TOOL_CONTENT`, `OTEL_LOG_TOOL_DETAILS`).

**Distributed traces / spans** — **BETA, requires `CLAUDE_CODE_ENHANCED_TELEMETRY_BETA=1`** (5 s export). This is the single most valuable surface for
profiling, and it is the one most likely to change. Span tree:
```
claude_code.interaction            (root, per user prompt; duration_ms)
├── claude_code.llm_request         ttft_ms, duration_ms, input/output/
│                                    cache_read/cache_creation tokens,
│                                    request_id, stop_reason, success, attempt,
│                                    query_source (main thread | subagent name)
├── claude_code.hook                (detailed-beta only)
└── claude_code.tool                tool_name, duration_ms (perm+exec),
    │                               result_tokens, skill_name (gated),
    │                               subagent_type (gated)
    ├── claude_code.tool.blocked_on_user   duration_ms, decision, source
    └── claude_code.tool.execution         duration_ms, success, error
```
The `blocked_on_user` vs `execution` split is exactly the permission-wait /
execution-time decomposition critic's time-budget needs (finding-010 §7
"blocked-on-human" bucket is directly observable here). `agent_id` +
`parent_agent_id` on `llm_request` spans give the subagent hierarchy.

**Cardinality controls** (the field warns against exactly the high-cardinality
trap in §A-of-research-strand-B): `OTEL_METRICS_INCLUDE_SESSION_ID` (default
true), `OTEL_METRICS_INCLUDE_ACCOUNT_UUID` (true), `_INCLUDE_VERSION` (false),
`_INCLUDE_ENTRYPOINT` (false). **Rule for critic: keep session/agent/run IDs on
spans, NOT as metric labels** (see Part B §6).

### A2. The session transcript (JSONL) — rich but version-internal

`~/.claude/projects/<project-hash>/<session-id>.jsonl`. Records: `user`,
`assistant` (with `model`), `tool_use` (tool_name, tool_input), `tool_result`
(is_error), and `usage` entries (input/output/cache_read/cache_creation tokens,
sometimes cost_usd). Timestamps on every record → **per-tool and per-turn
latency is *derivable* by differencing tool_use→tool_result and turn
boundaries, but there is NO explicit `duration_ms` field.** The docs state the
schema is "internal to Claude Code and changes between versions" — **do not make
it a primary dependency; prefer OTel or hooks, use the transcript for offline
backfill only** (the same posture finding-007 took for the dispatcher-log join).

One transcript record type is uniquely valuable and has no OTel/hook equivalent:
**`system` records with `subtype=compact_boundary`**, carrying a `compactMetadata`
object (`trigger` auto/manual, `preTokens`, `postTokens`, `durationMs`,
`preCompactDiscoveredTools`, plus preserved-segment UUIDs). This is the only
surface that exposes the cost and effect of auto-compaction — a real factory
expense (observed 80–116 s wall-clock per event, ~one event per ~2 h of dense
work in a 20 h session) that no other tap reports. See Q7.

### A3. Hooks — synchronous instrumentation points

Every hook gets JSON on stdin: `session_id`, `transcript_path`, `cwd`,
`permission_mode`, `hook_event_name`, `effort`, plus `agent_id`/`agent_type`
where relevant. Events usable as timing brackets: `SessionStart`,
`UserPromptSubmit`, `PreToolUse`, `PostToolUse` (+ failure variant),
`SubagentStart`, `SubagentStop`, `PermissionRequest`/`PermissionDenied`, `Stop`,
`PreCompact`/`PostCompact`, `Notification`.

**The hook profiling technique:** stamp wall-clock at `PreToolUse` and
`PostToolUse` → total tool wall-clock (includes permission wait; subtract the
permission-decision interval for execution-only). **Caveat the strand flagged:
no native duration field is passed to PostToolUse, timestamp precision is
platform-dependent, and the hook process itself injects ~ms of overhead into
the measurement.** Hooks are the fallback when the beta span surface isn't
enabled — and the only way to get a synchronous, same-process timing signal.

### A4. Statusline stdin — a zero-cost coarse tap

The statusline script receives a JSON blob on stdin every render:
`cost.total_cost_usd`, `cost.total_duration_ms` (wall-clock),
`cost.total_api_duration_ms` (API-only — **the wall vs API split is the
inference-vs-everything-else cut for free**), lines added/removed,
`context_window.*` (input/output/cache tokens, used_percentage,
exceeds-200k), `rate_limits.{five_hour,seven_day}.used_percentage`, `model`,
`session_id`, `transcript_path`, `version`. No per-tool/per-skill breakdown, but
a viable low-overhead session-level heartbeat — and `total_duration_ms −
total_api_duration_ms` is a usable orchestration+tool-overhead proxy.

### A5. MCP, debug, and read-only commands
- **MCP:** `mcp_server.name`/`mcp_tool.name` on cost/token metrics; per-call
  latency only on `claude_code.tool` spans (beta). No native MCP health metric.
  `/mcp` shows per-server tool-definition *size* (context cost), not latency.
- **Debug:** `claude --debug` / `ANTHROPIC_LOG=debug` → stderr logs, not
  telemetry; no structured per-request latency outside OTel traces.
- **`/usage` `/cost` `/context`** are human-display only — no machine-readable
  output. Not instrumentation surfaces.

### A6. The native-attribution verdict (blunt)

| Unit | Timing | Tokens | Cost | Native per-unit attribution? |
|---|---|---|---|---|
| Session | ✅ statusline/metrics | ✅ | ✅ | n/a |
| Turn (prompt→resp) | ✅ `interaction` span | ✅ | ✅ | ✅ query_source |
| API call | ✅ `ttft_ms`/`duration_ms` span | ✅ span | derived | ✅ query_source |
| Tool call | ✅ span / ⚠️ hook-reconstruct | ⚠️ `result_tokens` approx | ✖ amortized | ✅ tool_name |
| **Skill** | ✖ reconstruct | ✅ metric `skill.name` | ✅ metric `skill.name` | ✅ **but** all tokens while active attributed to it (incl. subagent/hook) |
| **Slash command** | ✖ unless it's a skill | ✖ unless skill | ✖ unless skill | ⚠️ only if it maps to a skill |
| Subagent | ✅ span tree | ✅ per-agent spans | ✅ per-agent spans | ✅ agent_id/parent_agent_id |
| MCP tool | ✅ span | ✖ amortized | ✖ amortized | ✅ mcp_tool.name |

**The gaps critic must reconstruct, stated plainly:**
1. **Slash commands have no native attribution unless they are skills.** Built-in
   commands (`/context` etc.) emit nothing.
2. **Skill attribution is "everything while active," not causal** — a subagent or
   hook firing inside a skill's window bills to the skill.
3. **Per-tool *tokens* and *cost* are amortized**, not exact (only `result_tokens`
   approx on the span).
4. **The richest timing (spans) is beta-gated and the transcript schema is
   version-internal** — both will break; both need adapter isolation.
5. **No native per-skill *latency*** — reconstruct from hook brackets or by
   integrating tool-span durations over the skill's active window.

This is the same shape as finding-007: the data largely exists at the call site;
what's missing is stable, causal *labelling* of which unit caused which cost.

---

## Part B — the methodology to apply (SOTA in LLM-agent profiling/tracing)

Provenance tags: **[STD]** = OTel spec / peer-reviewed; **[VENDOR]** = shipped
product doc; **[EMERGING]** = preprint/blog, not settled; **[UNVERIFIED]** =
could not confirm against a primary source — do not present as fact.

### B1. OpenTelemetry GenAI conventions — the backbone (and a moving one)

- **The conventions MOVED repos.** As of semconv **v1.42.0 (2026-06-12)** the
  `gen_ai.*` conventions left `open-telemetry/semantic-conventions` for the
  dedicated `open-telemetry/semantic-conventions-genai`; old
  `opentelemetry.io/.../gen-ai/*` URLs are redirect stubs. **Cite the new repo.**
  [STD]
- **Nothing in `gen_ai.*` is Stable — all "Development" tier**, i.e. breaking
  changes MAY occur (OTel versioning spec). **Pin a spec version; isolate the
  mapping.** [STD]
- **`gen_ai.system` → `gen_ai.provider.name`** rename CONFIRMED, landed v1.37.0
  (2025-08-25); old name deprecated. [STD]
- **Token attrs renamed:** `gen_ai.usage.prompt_tokens`/`completion_tokens` are
  DEPRECATED → use `gen_ai.usage.input_tokens`/`output_tokens`. [STD]
- **Operation enum** (`gen_ai.operation.name`): `chat`, `execute_tool`,
  `invoke_agent`, `create_agent`, `invoke_workflow`, `plan`, `embeddings`,
  `retrieval`, memory ops, … . **Span names:** `chat {model}`,
  `execute_tool {tool}`, `invoke_agent {agent}`. [STD]
- **First-class duration metrics exist:** `gen_ai.workflow.duration`,
  `gen_ai.invoke_agent.duration`, `gen_ai.execute_tool.duration`, plus
  `gen_ai.client.token.usage`, `gen_ai.client.operation.duration`, streaming
  `time_to_first_chunk`/`time_per_output_chunk`. [STD]
- **Multi-agent mapping for a Claude Code factory** (clean fit): slash-command /
  skill run → `invoke_workflow`; subagent → `invoke_agent`; MCP/tool → `execute_tool`; each model turn → `chat`. The workflow-span rule: only emit it when
  you can reliably tell a workflow (groups agent invocations) from a single agent.
  [STD]
- **No USD cost attribute in OTel** (confirmed; carried from global-telemetry.md)
  — cost is vendor-only; define a documented `*.cost.usd` extension. [STD]
- *[UNVERIFIED: no stable-promotion roadmap in any primary source.]*

### B2. The trace-tree model (and the field-name reality)

Every major LLM-observability tool models **session → trace → spans (nested) →
generations**, but names diverge: Langfuse `Trace`/`Observation`
(SPAN/GENERATION/AGENT/TOOL/…), Phoenix/OpenInference OTel spans with
`openinference.span.kind`, Braintrust auto-nesting `wrapTraced`, LangSmith
`run`/`run_type` + `dotted_order`, Weave `call`/`op` (only tool with an explicit
`start_subagent` → nested `invoke_agent` span). Helicone is the outlier — builds
the tree from a slash-delimited `Helicone-Session-Path` header, not parent
pointers. [VENDOR]

**Roll-up:** descendants sum into ancestors — clearest authoritative statement is
Weave's `CallsUsageReq` ("sum of its own usage plus all descendants'"); LangSmith
and Phoenix roll token/cost to trace+project level. [VENDOR]

**Load-bearing caution for critic's ingestion layer — TTFT is the most
inconsistently captured field across tools.** Explicit: Langfuse
(`timeToFirstToken`), Helicone (`time_to_first_token`), LangSmith
(`first_token_time`). Partial: Braintrust. **Undefined in the OpenInference
spec / UI-computed: Phoenix.** Absent (only `latency_ms`): Weave. **Do not assume
TTFT exists in any given trace export.** Cache-token field names also differ per
tool (table preserved in the session research record); OpenInference notably
defines a full `llm.cost.*` USD family and an Anthropic-specific
`prompt_details.cache_write`. [VENDOR, some cells UNVERIFIED]

### B3. Latency decomposition — definitions and the one live disagreement

- **TTFT** = prompt-processing + first token (incl. scheduling/queue delay; OTel
  folds queue into TTFT; only vLLM exposes queue separately as
  `vllm:request_queue_time_seconds`). **ITL/TBT/TPOT** = inter-token time.
  **e2e = TTFT + generation_time**; composite `TTFT + TPOT × output_tokens`
  (Databricks). [STD]
- **The canonical convention disagreement to encode:** does the per-token metric
  exclude TTFT? **Majority EXCLUDE (decode-only): NVIDIA GenAI-Perf** —
  `ITL = (e2e − TTFT)/(output_tokens − 1)`, rationale "characteristic of the
  decoding part only" — plus vLLM, DistServe, OTel, Etalon. **Documented minority
  INCLUDES: Anyscale/LLMPerf** ("we've seen systems that start streaming very
  late"). The `−1` denominator and TTFT-exclusion are the same choice stated two
  ways. **Fix one convention before comparing across runs.** [STD]
- **The agent critical-path three-way split — Autellix (arXiv 2502.13965),
  verbatim:** end-to-end = (1) **waiting time** (queue on the engine) + (2)
  **execution time** (cumulative LLM feedforward) + (3) **interceptions** (waiting
  on tool calls / human input). Maps exactly to critic's harness-queue /
  model-inference / tool-execution / blocked-on-human buckets (finding-010 §7).
  Corroboration: Parrot — orchestration overhead is 30–50% (≤70% worst case) of
  API-call latency *outside* the engine; a SWE-Agent CPU study — Bash/Python tool
  execution is 43–79% of total latency, LLM inference ≤0.5 s. **In tool-heavy
  factories the critical path is dominated by tool execution, not inference** —
  which is why per-tool timing (Part A) is the highest-leverage measurand. [STD;
  the clean three-way pie is critic's synthesis, not one citation]
  *[FLAG: a "PASTE" paper, arXiv 2603.18897, surfaced future-dated — do not cite
  until the ID resolves.]*

### B4. Profiling techniques ported from systems performance

- **Flame graphs** (Gregg, 2011): x-axis = sample population sorted
  alphabetically, **NOT time**; width = sample count. This is the load-bearing
  distinction from a **trace waterfall** (x-axis IS wall-clock). Vendors who call
  a time-axis timeline a "flame graph" are colliding names. [STD]
- **USE method** (utilization/saturation/errors per resource) and **off-CPU
  analysis** (time blocked, not on-CPU) — off-CPU is the direct analogue of
  Autellix "interceptions": time the factory is blocked on tool/API/human. [STD]
- **Critical-path analysis on traces** — the technique critic most needs to find
  the bottleneck chain. Canonical: **CRISP** (USENIX ATC '22) — "the longest
  chain of dependent tasks … reducing it is necessary to reduce end-to-end
  latency"; second source: Google **"Distributed Latency Profiling through
  Critical Path Tracing"** (ACM Queue 2022 / CACM Jan 2023). **Grafana already
  ships a CRISP critical-path highlight on its trace view.** [STD/VENDOR]
- **The agent frontier — be precise about novelty:**
  - **"agent flamegraph" is essentially uncoined** in primary/peer-reviewed
    sources (only weeks-old hobby repos). Treat as critic's own term; cite no
    prior art. Do NOT conflate with Gregg's "AI Flame Graphs" (that's GPU/
    instruction profiling of an LLM, not agent-trace viz). [EMERGING]
  - **Trace-timeline views for agents ARE shipped** (Honeycomb "Agent Timeline"
    GA; LangSmith "run tree") — called timeline/tree, not flamegraph. [VENDOR]
  - **Critical-path analysis applied to *agent* traces is NOT shipped by any
    observability vendor** (confirmed absent: LangSmith, Langfuse, Phoenix,
    Braintrust, Helicone). **This is critic's clearest differentiation.**
    [EMERGING]

### B5. Cost & token profiling per component
- Mechanical decomposition: sum the token/cost fields over the nested spans
  belonging to each skill/subagent/tool. Helicone "Custom Properties" is the
  shipped pattern for arbitrary per-feature attribution. Cost computed per-span
  at ingestion against a price table (Langfuse: ingested-cost-wins precedence).
  [VENDOR]
- **Prompt-cache profiling — Anthropic fields are exact and primary-sourced:**
  `cache_creation_input_tokens` (1.25× at 5-min / 2× at 1-hr), `cache_read_input_tokens` (0.1× — 90% off), `input_tokens` (uncached);
  `total_input = read + creation + uncached`. **Anthropic exposes creation vs
  read separately → critic can compute true write-amplification / cache-churn**
  (paying 1.25× to write a cache that expires unread — the death-spiral
  finding-010 §8 names). OpenAI gives only `cached_tokens` (read), no write
  surcharge. [STD — vendor primary]
- **"Where did the tokens go" has NO turnkey detector in any primary source**
  [UNVERIFIED as shipped tool]. Anthropic's context-engineering guidance supplies
  the framing (context = finite resource with diminishing returns; "context rot";
  subagents return 1–2k-token distilled summaries; tool-result clearing) but not a
  tool. **Wasted-token analysis (unread tool outputs, redundant context, cache
  misses that should have hit) is a legitimate unfilled niche — critic's
  contribution**, supported by component-level token data, not a citable existing
  tool. [EMERGING]

### B6. Sampling, overhead, cardinality — keeping it always-on
- **Head vs tail sampling** [STD]: head is cheap/stateless but "cannot make a
  decision based on the entire trace" (can't guarantee capturing all errors);
  tail considers all spans (criteria-based) but is stateful, vendor-ish, needs
  all spans at one collector (`tailsamplingprocessor`, circular buffer bounded by
  `num_traces`). **For a factory — runs are rare, expensive, high-variance →
  tail-sample on outcome: keep all failed/expensive/long traces, sample cheap
  successes.** Head sampling cannot serve this.
- **Cardinality** [STD]: OTel SDK default per-metric limit 2000
  (`otel.metric.overflow=true` guardrail); Prometheus — "do not use labels for
  high-cardinality dimensions such as user IDs"; Grafana — cardinality spikes
  cause memory errors/crashes. **Hazard for critic: session/agent/task/run IDs
  are exactly the unbounded dimensions — keep them on spans/traces (fine there),
  NOT as metric labels.** This is why Part A's `OTEL_METRICS_INCLUDE_SESSION_ID`
  default matters. *[UNVERIFIED: no primary source gives a quantitative tracing-
  overhead figure — do not state an overhead %.]*

### B7. Eval/benchmark-time profiling (ties to global-telemetry.md)
- **SWE-bench** = binary % resolved (FAIL_TO_PASS + PASS_TO_PASS); **its harness
  tracks NO cost/steps/time/tokens.** The gap critic fills: profile *how* the
  answer was reached, not just whether. [STD]
- **τ-bench pass^k** = "all k i.i.d. trials succeed" — reliability, not discovery
  (vs pass@k). Best agents pass^8 < 25% in retail. **Adopt pass^k for factory
  reliability** (consistent with finding-010 §4). [STD]
- **"AI Agents That Matter" (Kapoor & Narayanan, arXiv 2407.01502)** — the
  normative case: cost in *dollars* (compute proxies mislead), "for similar
  accuracy cost differs by ~2 orders of magnitude," visualize as a **cost-accuracy
  Pareto frontier**, "agent evaluations must be cost-controlled." **The single
  most important methodological citation for critic's thesis.** [STD]

---

## What critic builds, in order (the instrumentation plan)

The precedence is: get a stable signal first, then attribute, then decompose,
then profile. Build order:

1. **Turn on OTel as the always-on base** (metrics + log-events; A1). Capture the
   per-component attribution that *is* native: `skill.name`, `agent.name`,
   `mcp_tool.name`, `query_source` on cost/token metrics. Keep IDs off metric
   labels (B6).
2. **Enable the beta span surface** (`CLAUDE_CODE_ENHANCED_TELEMETRY_BETA=1`)
   behind an adapter — it gives `ttft_ms`, per-tool `duration_ms`, and the
   `blocked_on_user`/`execution` split, which are the timing measurands nothing
   else provides. Treat the schema as unstable; version-pin the mapping.
3. **Map to OTel `gen_ai.*`** (B1) for forward-compat and team-pooling
   (global-telemetry.md): factory→`invoke_workflow`, subagent→`invoke_agent`,
   tool/MCP→`execute_tool`, turn→`chat`. Add the documented `*.cost.usd`
   extension.
4. **Reconstruct what's not native** (A6): per-skill latency from hook brackets
   (A3) or by integrating tool-span durations over the skill window; slash-command
   attribution where it maps to a skill; offline backfill from the JSONL
   transcript (A2) for runs that predate telemetry.
5. **Build the two differentiators no vendor ships** (B4, B5): **critical-path
   analysis on the agent trace tree** (the longest dependent-span chain through a
   run — CRISP method) and **wasted-token / cache-churn analysis** (Anthropic's
   creation-vs-read split makes write-amplification computable).
6. **Decompose the time budget** (B3, Autellix three-way) into queue /
   inference / tool-execution / blocked-on-human — the answer to the user's
   factory-time question (finding-010 §7), now grounded in observable signals
   (statusline wall-vs-API split A4 + span `blocked_on_user` A1).
7. **Profile at eval time** (B7): cost-per-resolved-task on a cost-accuracy
   Pareto frontier + pass^k reliability — the methodology global-telemetry.md
   already adopted, now fed by the per-component cost data above.

## Open questions (frontier)

1. **Beta-span dependency risk.** The richest timing is beta-gated and
   schema-unstable. Does critic depend on it, or stay on metrics+hooks until it
   stabilizes? (Adapter isolation either way.)
2. **Skill-attribution causality.** Native skill.name bills "everything while
   active." Can hook brackets + the span tree recover *causal* per-skill cost
   (excluding subagent/hook work that merely co-occurred)?
3. **Critical-path on agent traces** — the differentiator. What's the right
   dependency model when spans are partly sequential (turns) and partly nested
   (tool calls within a turn)? CRISP assumes a microservice DAG; an agent trace
   is a different shape.
4. **Wasted-token detection** — what's the signal that a tool output was never
   read by the model? Requires correlating a tool_result's tokens against whether
   subsequent turns referenced it; no primary-source technique exists.
5. **Sampling policy for a factory** — tail-sample on outcome (keep failed/
   expensive) is the clear direction, but the trigger thresholds and the
   F26-blocked shared store (global-telemetry.md §3) gate the team form.
6. **Cross-provider normalization** — the factory may run on Bedrock/Vertex/
   Anthropic-direct (finding-010 §9); span field names and TTFT availability
   differ (B2). The `gen_ai.*` mapping layer is where this reconciles.
7. **Compaction as a profiled factory event.** Auto-compaction is a recurring,
   unbudgeted cost in any long-running unit: each event spends 80–116 s of
   wall-clock and re-writes the cached prefix (a cache-creation premium — the
   write-amplification finding-007 chased, and finding-010 §8's death-spiral
   mechanism). The `compactMetadata` record (A2) is the only tap that exposes it.
   Two metrics worth deriving across runs: **compaction frequency** (events per
   token of useful work — a high rate signals context bloat or a too-low trigger)
   and **post-compaction headroom** (`trigger_threshold − postTokens`; when a
   compaction preserves a large recent segment, `postTokens` lands high — once
   observed at 54009 vs a ~12–25k floor — leaving little headroom so the *next*
   compaction can re-fire within minutes, observed 6.4 min apart). Open: is the
   headroom wrinkle a Claude Code efficiency defect worth reporting upstream, or
   benign tail behavior? **n=1 anecdotally; decide only after instrumenting
   `compactMetadata` across several long sessions** — filing from a single
   occurrence risks a false report. This is the critic-owned data collection that
   gates any anthropics/claude-code issue on the topic.

## kos note

Graduates to a kos frontier node alongside `global-telemetry.md` when the kos CLI
is available (it is not, session-052) — likely orc-level, cross-cutting (critic
infra + Claude Code's instrumentation surface + the external observability
landscape). Until then this doc is the capture. Cross-refs: beadle finding-010
(the metric canon this instruments), beadle finding-007 / #324 (the attribution
gap), `global-telemetry.md` (team pooling), `boundary-beadle.md`.

### Provenance

Two parallel research strands, session-052 (2026-06-29), both primary-sourced
with adversarial re-fetching; unverifiable claims flagged [UNVERIFIED] inline
rather than smoothed. Strand A (Claude Code surface) verified against
`code.claude.com/docs/en/` — monitoring-usage, hooks, statusline, sessions,
skills, sub-agents, mcp, commands. Strand B (methodology) verified against the
OTel semantic-conventions(-genai) repos, vendor docs (Langfuse, Phoenix/
OpenInference, Helicone, Braintrust, LangSmith, Weave), arXiv (Autellix
2502.13965, Parrot 2405.19888, Etalon 2407.07000, τ-bench 2406.12045,
"AI Agents That Matter" 2407.01502), CRISP (USENIX ATC '22), Google CPT (ACM
Queue 2022), and Brendan Gregg's site. Exact URLs in the session research record.
Known flags: OTel `gen_ai.*` is pre-stable and recently moved repos; the
"agent flamegraph" term is uncoined; no turnkey wasted-token detector exists; the
"PASTE" arXiv 2603.18897 is future-dated and unconfirmed; no quantitative
tracing-overhead figure was verifiable.
