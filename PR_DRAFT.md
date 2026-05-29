# feat(plugins): self-evolving-harness — gate-free loop correction + HASP skill guardrails

**Branch:** `feat/self-evolving-harness` → (draft; not yet for upstream)
**Status:** DRAFT. Lint + tests green. Loads live on Hermes v0.15.1.

## What this adds

A new bundled-style plugin, `plugins/self-evolving-harness/`, that gives a Hermes
agent a small self-evolving runtime harness:

- **H4 trajectory monitor** (`post_tool_call`): watches the tool-call trajectory
  and, when the agent loops, injects a gate-free correction. The plugin keeps its
  own per-session buffer because the host hook only passes the current call.
- **Ten real Hermes skills as runtime guardrails** (`pre_tool_call`): each skill
  (TDD, systematic-debugging, code-review, github-auth, pr-workflow, plan,
  writing-plans, arxiv, himalaya, xurl) is converted into a HASP Program Function
  — a `(should_activate, intervene)` pair held by the same registry that holds
  evolved PFs. No new infra. Nine inject guidance; one (arxiv) is a MODIFY_ACTION
  repair.
- **Revertable persistence**: a HASP regression gate admits evolved PFs in a
  post-turn pass and writes them to a `FileRuleStore`; they reload on the next
  process start, and a regressing PF is rolled back.
- **Visible event stream**: every firing emits a typed event to `agent.log` and
  `$HERMES_HOME/self-evolving-harness/harness.log`, so the loop is observable, not
  a silent background mutation.
- **`/harness`** slash command for status + recent events.
- A **Phase-1 SAGE memory seam** (`MemoryProvider` with independently-swappable
  writer/reader Protocols) — interface only; no GPU.

The plugin binds against the canonical v0.15.1 plugin API
(`register(ctx)` + `ctx.register_hook(...)` + `ctx.register_command(...)`), with
hook handler signatures matching the real dispatch sites in
`agent/conversation_loop.py` and `model_tools.py`.

## Design notes / faithfulness

- The H4 (Continual-Harness) path is **gate-free** — it injects corrections
  unconditionally and never rolls back. The revertable regression gate is a
  *separate* HASP layer that runs post-turn, not inside any tool-call hook. The
  code and tests keep them apart.
- On the live `pre_tool_call` hook the guardrail surface is **block-only**: an
  inject-context PF surfaces its guidance as the host's block message; the
  MODIFY_ACTION extension is reported as guidance rather than silently rewriting
  the host's tool call.
- `detect_unproductive_streak` (same tool, N no-progress calls, args may differ)
  is a clearly-labeled extension of the verbatim `detect_repeat_loop` rule,
  motivated by what live MiniMax-M2.7 actually does (it perseverates on a
  dead-end tool with reworded args; it rarely repeats verbatim).

## Live-load proof (real plugin host, sideways profile)

Loaded through the real `PluginManager` on an isolated `HERMES_HOME` (not the
daily gateway). All checks green:

| check | result |
|-------|--------|
| discovered by real PluginManager | pass (alongside 33 bundled plugins) |
| enabled, no error | pass (4 hooks, 1 command, error=null) |
| H4 loop correction via real `invoke_hook` | pass (3× identical call → Correction) |
| skill PF blocks via real `get_pre_tool_call_block_message` | pass (TDD: "RED before GREEN") |
| `/harness` runs from real command registry | pass |
| visible `harness.log` written | pass |

Proof object: `plugins/self-evolving-harness/benchmark/live_plugin_load_proof.json`.

## Measured results (live MiniMax-M2.7-highspeed, temp 0)

**Table 1 — Agentic ablation (48 tasks, streak_threshold = 4).**

| family | OFF | ON | delta |
|--------|-----|----|-------|
| clean / exploration / loop / missing_arg | 1.000 | 1.000 | +0.000 |
| unknown_tool | 0.833 | 0.833 | +0.000 |
| **streak** | **0.722** | **0.444** | **−0.278** |
| **OVERALL** | **0.875 (42/48)** | **0.771 (37/48)** | **−0.104** |

**Honest:** this is a **regression**, not a win. On this strong reasoning model
the streak monitor (threshold 4) interrupts M2.7's own near-recovery: of 9
nudges, 0 rescued a loser, 7 derailed a winner. Five families are at ceiling and
the harness is correctly neutral there. The mechanism works; the default
threshold is wrong for a model this capable. We report it as measured.

**Table 2 — mini-SWE subset (real pytest oracle, real bash).** 5/5 resolve both
OFF and ON, 0 interventions. RAN, at ceiling, harness neutral — a wiring/non-harm
check, not a power test (subset too small).

**Persistence (offline deterministic evolution suite):** baseline 0.25 → parent
after learn+admit 1.00 → **fresh process reloading only from disk 1.00**. 5
admitted PFs survive the process boundary. **persistence = 1.** Cleanest positive
result.

Total live calls this program: 547 (Phase-3) + ~600 calibration ≈ 1147,
comfortably under the 15k/5h limit.

## Test + lint evidence

```
$ ruff check .
All checks passed!

$ pytest -q          # in plugins/self-evolving-harness/
139 passed
```

## Caveats (read before merging)

- The headline agentic ablation is a **measured regression** on M2.7 — the
  monitor needs a higher threshold or an advise-don't-interrupt mode before it's
  a net positive on strong models. This PR ships the harness disabled-by-default
  for every layer except H4, and H4 is conservative; reviewers should decide
  whether to ship H4 on at all given Table 1.
- mini-SWE separation is null at this subset size.
- Sage is Phase-1 seam only (no GRPO/GFM, no GPU).
- M2.7 is non-deterministic; single-pass numbers carry run-to-run variance
  (documented in `CALIBRATION_NOTES.md`).
- No web-dashboard surface is added, so there is no UI screenshot — the visible
  surface is the event stream / `harness.log`.

## Files

- `plugins/self-evolving-harness/` — the plugin (`__init__.py`,
  `skill_program_library.py`, `harness_core/`, `tests/`).
- `PAPER_self_evolving_hermes.md` — the full write-up with both result tables and
  the honest limitations section.
- `plugins/self-evolving-harness/benchmark/` — the live proof + result JSON.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
