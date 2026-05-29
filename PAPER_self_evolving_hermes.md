# A Self-Evolving Runtime Harness for Hermes: Gate-Free Loop Correction, HASP Skill Guardrails, and a Revertable Persistence Layer

*Measured on live MiniMax-M2.7. Built against Hermes v0.15.1. 2026-05-29.*

## Abstract

We add a **self-evolving runtime harness** to the Hermes agent: a plugin that
watches the live tool-call trajectory, surfaces gate-free corrections when the
agent loops, expresses ten real Hermes skills as executable runtime guardrails
(HASP Program Functions), and persists evolved guardrails across process
restarts behind a revertable regression gate. The harness loads through the real
Hermes v0.15.1 plugin host and fires on real agent turns. We benchmark it
on live `MiniMax-M2.7-highspeed` over two suites: a controlled agentic tool-use
ablation (48 tasks, 384 live calls) and a mini-SWE subset with a real `pytest`
oracle (10 runs, 49 live calls). We report the numbers honestly, including a
**regression** the H4 streak monitor causes on this particular model, the
ceiling effect on mini-SWE, and a deterministic offline persistence result that
survives a process boundary.

This is an engineering paper with an honest results section, not a
state-of-the-art claim. The harness is a working seam; whether a given monitor
*helps* is model- and threshold-dependent, and we show one case where it hurts.

---

## 1. What we built

Four runtime layers, each behind a master switch, mapped onto the Hermes agent
turn via the canonical v0.15.1 plugin hook API (`register(ctx)` +
`ctx.register_hook(...)`):

| Layer | Hook | Role |
|------|------|------|
| H3 (env contract) | `on_session_start` | tool-contract anchor (system-prompt time) |
| H5 (procedural skill) | `on_session_start` | procedural-skill injection anchor |
| H2 (action gate) | `pre_tool_call` | block / surface-guidance before a tool runs |
| H4 (trajectory monitor) | `post_tool_call` | detect loops / streaks, inject correction |

The plugin carries its **own per-session trajectory buffer**, because the host's
`post_tool_call` hook hands a plugin only the *current* call — not the running
history. H4 needs the trajectory, so we accumulate `ToolCall`s keyed by
`session_id`, run the detector over the trailing window, and drop the buffer on
`on_session_end`.

### 1.1 Continual-Harness proposer (gate-free)

The H4 monitor is the **Continual-Harness (CH)** surface. It is **gate-free**:
when it detects a loop it injects its correction **unconditionally** and never
rolls back. There is no admission test on the CH path. We are explicit about
this because it is a faithfulness point: CH proposes, it does not gate.

Two detectors:

- `detect_repeat_loop` — the trailing *N* calls are *identical* (same tool **and**
  same args). Catches literal thrash.
- `detect_unproductive_streak` — the trailing *N* calls hit the *same tool* and
  *all failed to make progress*, even with *different* arguments. This is a
  small, faithful extension motivated by calibration (Section 3): a strong model
  rarely repeats verbatim but routinely perseverates on one dead-end tool with
  reworded arguments.

### 1.2 HASP gate + revertable persistence

Separately from CH, a **HASP** composition layer admits evolved Program
Functions through a **regression gate** (`try_admit`) that runs in a post-turn
evolve pass — *not* inside any per-tool-call hook. Admitted PFs are written to a
`FileRuleStore` and reloaded on the next process start; a PF that regresses the
score is **reverted** (rolled back). The gate and the CH proposer are different
layers with different semantics, and the code keeps them apart.

### 1.3 Ten skills → HASP Program Functions

We converted ten real, existing Hermes skills into managed HASP Program
Functions. Each is a `(should_activate, intervene)` pair satisfying the
`ProgramFunction` Protocol and held by the same `PFRegistry` that holds evolved
PFs — no new infrastructure. Each links back to its source `SKILL.md`.

| # | Program Function | Source skill | Layer | Intervention |
|---|------------------|--------------|-------|--------------|
| 1 | `skillpf_tdd_red_before_green` (TDDGuardPF) | software-development/test-driven-development | H2 | INJECT_CONTEXT |
| 2 | `skillpf_systematic_debugging_iron_law` (RootCauseGuardPF) | software-development/systematic-debugging | H2 | INJECT_CONTEXT |
| 3 | `skillpf_precommit_review_required` (PreCommitReviewPF) | software-development/requesting-code-review | H2 | INJECT_CONTEXT |
| 4 | `skillpf_github_auth_first` (GithubAuthGuardPF) | github/github-auth | H3 | INJECT_CONTEXT |
| 5 | `skillpf_pr_merge_requires_green_ci` (PRMergeChecksPF) | github/github-pr-workflow | H2 | INJECT_CONTEXT |
| 6 | `skillpf_plan_mode_read_only` (PlanModeGuardPF) | software-development/plan | H2 | INJECT_CONTEXT |
| 7 | `skillpf_write_plan_before_delegate` (WritePlanBeforeDelegatePF) | software-development/writing-plans | H5 | INJECT_CONTEXT |
| 8 | `skillpf_arxiv_keyless_api` (ArxivApiGuardPF) | research/arxiv | H3 | **MODIFY_ACTION** (ActionOverride) |
| 9 | `skillpf_email_review_before_send` (EmailSendReviewPF) | email/himalaya | H2 | INJECT_CONTEXT |
| 10 | `skillpf_x_post_confirm` (XPostConfirmPF) | social-media/xurl | H2 | INJECT_CONTEXT |

These are genuine runtime behaviours, not keyword echoes: each activation
predicate inspects the candidate action **and** the agent state (e.g. "no failing
test observed yet", "in plan mode", "2+ files edited and about to commit").
Number 8 is the one MODIFY_ACTION conversion — it repairs an arXiv query that
carries a bogus `api_key` back to the documented keyless endpoint.

On the live `pre_tool_call` hook we keep the surface **block-only** for paper
faithfulness: a ContextInjection PF surfaces its guidance as the host block
message; the MODIFY_ACTION extension is *reported* as guidance rather than
silently rewriting the host's tool call.

### 1.4 Sage P1 memory seam

We ship a Phase-1 `MemoryProvider` (Mimir seam) with **independently-swappable**
`MemoryWriter` and `MemoryReader` Protocols modelling SAGE (arXiv 2605.12061) at
the *interface* level: the writer emits records that can carry SAGE-style
`(subject, relation, object)` triples with source anchors; the reader returns a
TopK hit distribution plus empty `subgraph` / `relational_paths` fields the GFM
populates later with no interface change. The Phase-1 stubs do deterministic
extraction and substring ranking — **no GRPO, no GFM, no GPU**. Phase-2 (GRPO
writer + Graph Foundation Model reader, on-GPU) is **deferred** (Section 5).
**Sage P1 seam = true.**

---

## 2. Live plugin-load proof

The plugin loads through the **real** Hermes v0.15.1 plugin host
(`hermes_cli/plugins.py::PluginManager`) on a sideways profile (isolated
`HERMES_HOME`, never the daily gateway). All checks green:

```
plugin_discovered           : pass  (loaded alongside 33 bundled plugins)
plugin_enabled              : pass  (enabled=true, error=null, 4 hooks, 1 command)
h4_loop_correction_via_real_hook : pass  (3x identical search_files → Correction)
pre_tool_call_skill_pf_blocks    : pass  (TDD PF blocked write_file: "RED before GREEN")
harness_command_runs        : pass  (/harness status from the real command registry)
visible_log_written         : pass  (harness.log: session_start, pf_fired x2, session_end)
```

Real `harness.log` tail (the visible self-evolution surface):

```
[session_start] harness session start (model=MiniMax-M2.7 platform=cli)
[pf_fired] H4 loop detected on `search_files` — You have called `search_files`
           with identical arguments 3 times in a row. This is a loop ...
[pf_fired] H2 skillpf_tdd_red_before_green on `write_file`
[session_end] harness session end (completed=True interrupted=False)
```

The harness fires through the same `invoke_hook` / `get_pre_tool_call_block_message`
paths the gateway uses — not a mock. (Proof object:
`benchmark/live_plugin_load_proof.json`.)

---

## 3. Method (benchmarks)

All policy calls are **live** `MiniMax-M2.7-highspeed` over the Anthropic
Messages API (`api.minimax.io/anthropic`), temperature 0. M2.7 is a reasoning
model (thinking + text blocks); we give max_tokens headroom. Rate limit is
15,000 calls / 5h with no token cap; we kept the whole program well under that.

**Suite A — agentic tool-use ablation (headline).** 48 tasks across 6 trap
families (`streak 18 · clean 3 · loop 8 · missing_arg 8 · unknown_tool 6 ·
exploration 5`). Each task is a deterministic simulated tool world; the **policy
is real M2.7** over the real tool-use API. Scoring is an exact env goal
predicate within budget. We run OFF vs ON (H4 streak monitor, threshold = 4).

**Suite B — mini-SWE subset (credibility).** 5 small bug-fix tasks run twice
(OFF/ON). The oracle is the **real `pytest` exit code** (not model self-report),
with real `bash` executed through Hermes' `LocalEnvironment`.

**Persistence.** A deterministic offline evolution suite: a parent process
learns and admits PFs through the `try_admit` gate, persists them to a
`FileRuleStore`; a **separate** process reloads only from disk and re-measures.

Calibration (~600 earlier live calls) found that M2.7 is **near-ceiling unaided**
on five of the six families because the tool-use API hands it the full
`input_schema`. The one genuine failure mode is **semantic streak thrash** on the
`streak` family — which is exactly why that family is the headline.

---

## 4. Results

### Table 1 — Agentic suite (live M2.7, 48 tasks, temp 0, streak_threshold = 4)

| family | OFF | ON | delta |
|--------|-----|----|-------|
| clean | 3/3 — 1.000 | 3/3 — 1.000 | +0.000 |
| exploration | 5/5 — 1.000 | 5/5 — 1.000 | +0.000 |
| loop | 8/8 — 1.000 | 8/8 — 1.000 | +0.000 |
| missing_arg | 8/8 — 1.000 | 8/8 — 1.000 | +0.000 |
| **streak** | **13/18 — 0.722** | **8/18 — 0.444** | **−0.278** |
| unknown_tool | 5/6 — 0.833 | 5/6 — 0.833 | +0.000 |
| **OVERALL** | **42/48 — 0.875** | **37/48 — 0.771** | **−0.104** |

ON interventions: 9 (all on `streak`). Of those 9 nudges: **0 rescued a loser,
7 derailed a near-recovery.** Calls: OFF 192, ON 192.

**Honest verdict: the H4 streak monitor as tuned (threshold = 4) is a NET
NEGATIVE on live M2.7 this run.** Injecting a `tool_result` correction disrupts
M2.7's own near-recovery reasoning. The other five families sit at ceiling and
the harness is correctly neutral there (no harm). This is a single-pass,
non-deterministic provider; the OFF streak rate swung from a calibrated ~0.333 to
0.722 this run, confirming the documented variance. **We do not claim an
improvement on Suite A.** The honest finding is a measured *regression* plus a
clear lesson: for a strong reasoning model, a trajectory monitor must be far more
conservative (higher threshold, or "advise, don't interrupt"), or it does more
harm than good.

### Table 2 — mini-SWE subset (real pytest oracle, real bash via Hermes LocalEnvironment)

| metric | OFF | ON |
|--------|-----|----|
| resolve rate | 5/5 — 1.00 | 5/5 — 1.00 |
| interventions | 0 | 0 |

mini-SWE **RAN** (not blocked). M2.7 is at ceiling: 5/5 both modes, 0
interventions (it never thrashes — read source → edit → re-test). The harness is
correctly neutral: no false-positive nudges, no harm. **No separation at this
subset size** — the subset is too small and too easy to discriminate; this is a
credibility/wiring check, not a power test. Calls: OFF 24, ON 25.

### Persistence (deterministic offline evolution suite)

| stage | resolve rate |
|-------|-------------|
| baseline (no learned PFs) | 0.25 |
| parent after learn + admit (5 PFs) | 1.00 |
| **fresh process, reload from disk only** | **1.00** |

Delta +0.75 pp; **5 admitted PFs kept across the process boundary** (gain
retained after restart). **persistence = 1.** This is the cleanest positive
result: the learn → gate → persist → reload loop works and survives a restart.

### Call budget

| phase | calls |
|-------|-------|
| agentic OFF / ON | 192 / 192 |
| mini-SWE OFF / ON | 24 / 25 |
| streak probe (t6) | 114 |
| **Phase-3 session total** | **547** |
| + earlier calibration | ~600 |
| cumulative | ~1147 (under the 2500 ceiling) |

---

## 5. Honest limitations & faithfulness flags

- **Suite A is a regression, not a win.** The headline ablation shows the H4
  streak monitor hurting M2.7 (−0.104 overall, −0.278 on streak). We report it
  as measured. The harness *mechanism* works; the *default threshold is wrong*
  for a model this strong.
- **Sim vs live scope.** Suite A's tool *worlds* are deterministic simulations;
  the *policy* is live M2.7. mini-SWE uses a real `pytest` oracle and real bash.
  Neither suite is a full agentic benchmark.
- **mini-SWE subset is tiny.** 5 tasks, both modes at ceiling. It demonstrates
  wiring and non-harm, not improvement.
- **Persistence is offline/deterministic.** The +0.75 result is from the offline
  evolution suite (`agent_env`), not a live-LLM loop.
- **Sage P2 deferred (on-GPU).** Only the Phase-1 seam ships. GRPO writer + GFM
  reader are interface-compatible but not implemented; they need GPU training we
  did not run (RTX 5080, 16 GB; not crashed, not attempted for P2).
- **CH is gate-free** — by design and stated explicitly; no rollback on the CH
  path. The revertable gate is the *separate* HASP layer.
- **`detect_unproductive_streak` is a labeled extension** of the
  `detect_repeat_loop` paper rule (same tool, N no-progress calls, args may
  differ). It is motivated by calibration and clearly marked as an extension,
  not a paper-verbatim rule.
- **Non-determinism.** M2.7 is sampled (even at temp 0 the provider is not bit-
  reproducible); single-pass numbers carry run-to-run variance, documented in
  `benchmark/CALIBRATION_NOTES.md`.

## 6. Reproduction

- Plugin: `plugins/self-evolving-harness/` (loads on Hermes v0.15.1).
- Live-load proof: `benchmark/_live_plugin_load.py` → `live_plugin_load_proof.json`.
- Suite A: `benchmark/live_runner.py` + `live_tasks.py` → `phase3_results.json`,
  `phase3_tables.txt`.
- Suite B: `benchmark/swe_runner.py` + `swe_subset.py` → `swe_results.{off,on}.json`.
- Persistence: `benchmark/_persistence_parent.py` + `_fresh_session.py`.
- Tests: `pytest` in the plugin dir → 139 passed. Lint: `ruff check .` clean.
