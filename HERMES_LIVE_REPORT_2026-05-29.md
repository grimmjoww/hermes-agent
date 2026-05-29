# Self-Evolving Hermes — Live Program Report (2026-05-29)

Honest per-component status. DONE = real evidence captured. STAGED = built/ready
but not exercised end-to-end live. BLOCKED = could not complete (with reason).

Branch: `feat/self-evolving-harness` on `grimmjoww/hermes-agent`
(HEAD `c7accb3b2`, based on upstream HEAD `1c53d39e`). Pushed. PR **not** opened
(Willie submits).

---

## 1. Foundation (harness_core + plugin packaging) — DONE

- 139 tests pass in the fork plugin (`plugins/self-evolving-harness/`), 138 in the
  working repo. `ruff check .` clean in both.
- Plugin rewritten/verified against the **canonical Hermes v0.15.1 plugin API**
  (read from `hermes_cli/plugins.py` + dispatch sites, not assumed):
  `register(ctx) -> None`, `ctx.register_hook(name, cb)`,
  `ctx.register_command(name, handler, description)`.
  - `on_session_start(session_id, model, platform)`
  - `pre_tool_call(tool_name, args, task_id, session_id, tool_call_id)` →
    `{"action":"block","message":...}` blocks (confirmed via the host's
    `get_pre_tool_call_block_message`).
  - `post_tool_call(tool_name, args, result, task_id, session_id, tool_call_id, duration_ms)` → observer.
  - `on_session_end(session_id, completed, interrupted)`.
- The plugin keeps its **own per-session ToolCall buffer** for H4, because the host
  hook only passes the current call. Verified.
- **Evidence:** `pytest -q` → `139 passed`; `ruff check .` → `All checks passed!`

## 2. Plugin loads LIVE on the real host — DONE

Loaded through the real `PluginManager.discover_and_load()` on a sideways
`HERMES_HOME` (never the daily gateway). All six checks green:

| check | result |
|-------|--------|
| discovered by real PluginManager (with 33 bundled plugins) | pass |
| enabled, error=null, 4 hooks, 1 command | pass |
| H4 loop correction via real `invoke_hook("post_tool_call")` | pass |
| skill PF blocks via real `get_pre_tool_call_block_message` (TDD) | pass |
| `/harness` runs from real command registry | pass |
| visible `harness.log` written | pass |

- **Evidence:** `plugins/self-evolving-harness/benchmark/live_plugin_load_proof.json`
  (`"ok": true`), driver `benchmark/_live_plugin_load.py`. Real log line:
  `[pf_fired] H4 loop detected on \`search_files\` — You have called ...`.

## 3. Ten skills → HASP — DONE

All ten converted, registry-managed, one test each + integration test:
`skillpf_tdd_red_before_green (TDDGuardPF, H2)`,
`skillpf_systematic_debugging_iron_law (RootCauseGuardPF, H2)`,
`skillpf_precommit_review_required (PreCommitReviewPF, H2)`,
`skillpf_github_auth_first (GithubAuthGuardPF, H3)`,
`skillpf_pr_merge_requires_green_ci (PRMergeChecksPF, H2)`,
`skillpf_plan_mode_read_only (PlanModeGuardPF, H2)`,
`skillpf_write_plan_before_delegate (WritePlanBeforeDelegatePF, H5)`,
`skillpf_arxiv_keyless_api (ArxivApiGuardPF, H3, MODIFY_ACTION/ActionOverride)`,
`skillpf_email_review_before_send (EmailSendReviewPF, H2)`,
`skillpf_x_post_confirm (XPostConfirmPF, H2)`.

- **Evidence:** `tests/test_skill_program_library.py` (11 tests pass); one of them
  fired live in the plugin-load proof (TDD blocked a `write_file`).

## 4. Benchmark — agentic suite OFF/ON — DONE (regression, reported honestly)

Live MiniMax-M2.7, 48 tasks, temp 0, streak_threshold=4:

- **OFF overall = 0.875 (42/48)**
- **ON overall = 0.7708 (37/48)**  → **−0.104**
- streak family: OFF 0.722 → ON 0.444 (−0.278). 9 ON interventions: 0 rescued, 7
  derailed a near-recovery. Other 5 families at ceiling, harness neutral (no harm).
- **Verdict: the H4 streak monitor as tuned REGRESSED M2.7 this run.** Not a win.
  Reported as measured. Mechanism works; default threshold is wrong for a model
  this strong.
- **Evidence:** `benchmark/phase3_results.json`, `phase3_tables.txt`,
  `results_live.{off,on}.json` (in the working repo); calibration in
  `CALIBRATION_NOTES.md`.

## 5. Persistence — DONE (positive)

Offline deterministic evolution suite: baseline 0.25 → parent learn+admit (5 PFs)
1.00 → **fresh process reloading only from disk = 1.00**. 5 admitted PFs kept
across the process boundary. **persistence = 1.**

- **Evidence:** `benchmark/_persistence_parent.py` + `_fresh_session.py`,
  `phase3_results.json::persistence`.

## 6. mini-SWE — DONE (ran, ceiling, no separation)

5 tasks × 2 modes, **real `pytest` exit-code oracle**, real bash via Hermes
`LocalEnvironment`. OFF 5/5, ON 5/5, 0 interventions. RAN, not blocked. M2.7 at
ceiling; harness correctly neutral. Subset too small for separation.

- **Evidence:** `benchmark/swe_results.{off,on}.json`, runner `swe_runner.py` +
  `swe_subset.py`.

## 7. Sage P1 seam — DONE

Phase-1 `MemoryProvider` (Mimir) with **independently-swappable**
`MemoryWriter` / `MemoryReader` Protocols modelling SAGE at the interface level
(triple-carrying records, TopK + empty subgraph/paths fields). Deterministic
stubs, no ML deps. **Sage P1 seam = true.**

- **Evidence:** `harness_core/memory/provider.py`, `tests/test_memory_provider.py`.

## 8. Sage P2 (GPU training) — DEFERRED

GRPO writer + GFM reader are interface-compatible but **not implemented**;
require GPU training (RTX 5080, 16 GB) not run this program. Deferred on-GPU per
charter. Box not crashed (not attempted).

## 9. Paper — DONE

`PAPER_self_evolving_hermes.md`: real implementation, method, two result tables,
honest limitations + faithfulness flags (CH gate-free, efficacy/streak labeled
extension, sim-vs-live scope, mini-SWE subset size, Sage P2 deferred).

## 10. PR draft — DONE (pushed; not submitted)

`PR_DRAFT.md`: humanized title + summary + what-changed + measured-results tables +
test evidence + caveats. Two humanized commits on `feat/self-evolving-harness`,
lint+tests green, pushed to `grimmjoww/hermes-agent`. **DRAFT only — not opened
upstream.**

## 11. UI / dashboard — N/A (no surface changed)

The plugin adds no web-dashboard surface; its visible surface is the event stream
→ `agent.log` + `$HERMES_HOME/self-evolving-harness/harness.log`. No screenshot
required or claimed. The visible-log line was captured in the live proof instead.

---

## Bottom line

The harness is **real and loads live on Hermes v0.15.1** — proven through the
actual plugin host, with H4 corrections, skill-PF blocks, the `/harness` command,
and a visible log all firing on real calls. The honest measured story: **the
persistence loop works and survives a restart (rate 1.0)**, but **the agentic
streak monitor regressed live M2.7 this run (OFF 0.875 → ON 0.771)** — a strong
reasoning model recovers on its own and the nudge interrupts it. mini-SWE ran at
ceiling. Sage Phase-1 seam done, Phase-2 deferred on GPU.

**Two key rates: agentic OFF = 0.875, ON = 0.7708.**
