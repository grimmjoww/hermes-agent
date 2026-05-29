# Live MiniMax-M2.7 benchmark — calibration notes (2026-05-29)

Real measured numbers from live `MiniMax-M2.7-highspeed` calls via
`benchmark/minimax_client.py` (Anthropic Messages API, temp 0). ~600 live calls
total spent on calibration; rate-limit budget (15k / 5h) never approached.

## Suite
`benchmark/live_tasks.py::build_suite()` → 48 tasks:
`streak 18 · clean 3 · loop 8 · missing_arg 8 · unknown_tool 6 · exploration 5`.

Each task is a deterministic simulated tool world; the POLICY is real M2.7 over
the Anthropic tool-use API. Scoring is exact (env goal predicate within budget).

## What calibration found (honest)
MiniMax-M2.7 is a strong reasoning model. Because the Anthropic tool-use API
hands it the full tool **input_schema**, the classic harness traps are mostly
**near-ceiling** for it unaided:

| family        | OFF behaviour (live) | harness relevance |
|---------------|----------------------|-------------------|
| clean         | ~100%                | control, must not regress |
| missing_arg   | ~100% (schema names required args) | near-ceiling / neutral |
| unknown_tool  | ~100% (schema lists the one real tool) | near-ceiling / neutral |
| loop (literal)| ~100% (M2.7 rarely repeats verbatim) | near-ceiling / neutral |
| exploration   | ~100% (reasons through list→open→submit) | near-ceiling / neutral |
| **streak**    | **33% (6/18)** — thrashes a dead-end tool with reworded args | **headline: genuine failure** |

The one failure mode M2.7 genuinely exhibits is **semantic thrash**: it keeps
calling one dead-end tool with *different* arguments instead of switching to a
provided alternative. Its literal repeats are rare, so the existing
`detect_repeat_loop` (identical tool+args) never fires. Calibration motivated a
small, faithful H4 extension — `detect_unproductive_streak` (same tool, N
consecutive no-progress calls, args may differ) — now in
`harness_core/layers/h4_trajectory.py` with unit tests.

### streak OFF baseline (all 18, single live pass)
`6/18 = 33.3%` — squarely in the calibration band (not 0%, not 100%). 12 of 18
exhausted the budget thrashing `search`; 6 discovered `list_topics` unaided.

## Important caveat for Phase 3 (do not overstate)
- M2.7 over the live API is **not deterministic at temp 0** (provider-side
  variance); single-pass OFF-vs-ON deltas on the hard family are noisy. Phase 3
  should run **multiple seeds / repeats per task** and report mean±spread.
- In the small live ON sample, firing the streak monitor at threshold=3 sometimes
  **preempted M2.7's own recovery** (it self-recovers around turn 4–5) and the
  injected tool_result occasionally derailed it. Threshold tuning (fire only
  *after* the model's natural recovery window, e.g. ≥4–5) is an open Phase-3
  calibration knob, not yet a settled win. The harness is **not** claimed to
  improve M2.7 here until Phase 3 measures it over repeats. This file records the
  honest state: a hard, in-band baseline + a runnable ablation, no green-on-fiction.

## Budget math (full pass)
Per task ≤ `budget` LLM turns (one call/turn). 48 tasks × ~6 avg turns ≈ ~290
calls per pass; OFF+ON ≈ ~580; +persistence re-run ≈ ~870 — all well under the
1500/pass ceiling.

---

# Phase 3 — measured OFF vs ON (live, 2026-05-29)

Full ablation run, 48 tasks, temp 0, `streak_threshold=4` (raised from the
calibration's 3 to clear M2.7's self-recovery window per the caveat above).
Results in `phase3_results.json` / `results_live.{off,on}.json`.

## Agentic suite — OFF vs ON (48 tasks)
| family       | OFF       | ON        | delta   |
|--------------|-----------|-----------|---------|
| clean        | 3/3 1.000 | 3/3 1.000 | +0.000  |
| missing_arg  | 8/8 1.000 | 8/8 1.000 | +0.000  |
| loop         | 8/8 1.000 | 8/8 1.000 | +0.000  |
| exploration  | 5/5 1.000 | 5/5 1.000 | +0.000  |
| unknown_tool | 5/6 0.833 | 5/6 0.833 | +0.000  |
| **streak**   | **13/18 0.722** | **8/18 0.444** | **-0.278** |
| OVERALL      | 42/48 0.875 | 37/48 0.771 | -0.104 |

Calls: 192 OFF + 192 ON = 384. ON interventions: 9 (all on streak).

### Honest verdict (no green-on-fiction)
**The harness REGRESSED M2.7 on this run.** Per-task diagnosis of the 9 streak
nudges: **0 rescued a loser, 7 derailed a winner** (True→False with interv=1).
The three OFF→ON rescues (sk1, sk10, sk16) all had **0 interventions** — they are
M2.7's own run-to-run variance, not the harness.

Root causes, both already flagged in the calibration caveat:
1. **Provider non-determinism dominates.** M2.7's *unaided* streak rate swung from
   the calibrated **0.333** to **0.722** between sessions at temp 0. A single OFF
   vs ON pass cannot resolve a ~0.1 harness effect against a ~0.4 noise band.
2. **The injection disrupts near-recovery reasoning.** When the streak monitor
   replaces a real tool_result with "stop, switch tools," it knocks M2.7 off a
   chain it was about to complete (it self-recovers ~turn 5-6). Firing at
   threshold=4 still preempts that.

The other 5 families confirm the harness does **no harm** at ceiling (no
false-positive interventions, identical rates).

### Threshold-sweep probe (ON-only, `streak_threshold=6`)
To test the "fire later" hypothesis, an ON-only run at threshold=6: streak
**9/18 = 0.500** but the monitor fired only **2 times** in the whole family (vs 9
at t=4). At budget=8 a threshold of 6 leaves almost no trajectory long enough to
trip — the monitor degenerates to a near-no-op. **Conclusion: there is no
threshold sweet spot inside budget=8.** Fire early (t=4) → derails M2.7's own
recovery; fire late (t=6) → barely engages. A real win needs a longer budget AND
a non-destructive hint channel, both Phase-3+ work. (The t=6 run's near-ceiling
TAIL was cut short by an unrelated MiniMax HTTP 400 "tool call and result not
match" — a provider-side strictness hiccup; the signal-bearing streak family had
already completed. The OFF and the t=4 ON runs completed cleanly end-to-end.)

## mini-SWE subset — OFF vs ON (5 real-oracle repair tasks)
Real bash via Hermes `LocalEnvironment`; "resolved" = the task's own `pytest`
exit code (not the model's self-report). M2.7 over the OpenAI-compatible v1
endpoint.

| metric        | OFF   | ON    |
|---------------|-------|-------|
| resolve rate  | 5/5 1.000 | 5/5 1.000 |
| interventions | 0     | 0     |

**RAN (not blocked).** M2.7 is at ceiling on these small repairs — it reads the
source, edits, re-runs the test, done (4-6 calls). It never thrashes, so the H4
streak monitor never fires: the harness is correctly **neutral** (no
false-positive nudges, no harm), but there is no separation to measure at this
scale.

## Persistence (offline deterministic evolution suite)
Parent process: baseline OFF **0.25** → learns + gate-admits **5 EvolvedPFs**
(`try_admit`) → persists to `FileRuleStore`. A **separate process**
(`_fresh_session.py`) reloads ONLY from disk and re-measures **1.0**. The +0.75
gain is **retained across a real process boundary** — not re-learned, not
in-memory. This is the one clean, deterministic improvement-and-persistence
proof; it is on the controlled evolution suite, NOT on live M2.7.

## Bottom line for the PR
- **Persistence loop: proven** (deterministic, cross-process, +0.75pp kept).
- **Live M2.7 agentic improvement: NOT proven — regressed this run.** The H4
  semantic-streak monitor is a net negative on M2.7 as currently tuned because
  the model recovers on its own and the injection interrupts it. Honest status:
  the harness is **safe at ceiling** (does no harm to the 5 near-ceiling
  families) but is **not yet a measured win** on the one hard family. Making it a
  win needs (a) multi-seed repeats to beat the provider noise band and (b) a
  later/smarter firing rule (fire only on budget-terminal stuck trajectories, or
  a weaker side-channel hint that doesn't replace the tool_result).
