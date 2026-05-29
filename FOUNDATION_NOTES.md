# Foundation notes — self-evolving-harness Hermes plugin

Date: 2026-05-29. Hermes v0.15.1. Fork: grimmjoww/hermes-agent, branch
`feat/self-evolving-harness` (cut from origin/main `1c53d39ea`).

## What landed

`plugins/self-evolving-harness/` — the 4-layer Life-Harness program-function
runtime (H2 action gate, H3 env contract, H4 trajectory/loop monitor, H5
procedural-skill injection) packaged as a standard Hermes plugin, plus its
`harness_core` package and the full pytest suite.

## Canonical v0.15.1 plugin API (read from source, not assumed)

Plugin host: `hermes_cli/plugins.py`. The contract:

- Entry point is `def register(ctx)`. `ctx` is a `PluginContext`.
- `ctx.register_hook(hook_name, callback)` — binds a lifecycle hook.
- `ctx.register_command(name, handler, description="", args_hint="")` — slash
  command; handler is `fn(raw_args: str) -> str | None`.
- `VALID_HOOKS` includes `pre_tool_call`, `post_tool_call`, `on_session_start`,
  `on_session_end` (plus llm/api/approval/gateway hooks we don't use).
- Hooks are dispatched via `invoke_hook(name, **kwargs)`; each callback is
  wrapped in try/except so a misbehaving plugin can't crash the loop.

Real dispatch signatures (from the call sites):

- `on_session_start(session_id, model, platform)` — `agent/conversation_loop.py:295`
- `on_session_end(session_id, completed, interrupted, model, platform)` —
  `agent/conversation_loop.py:4596` (and `cli.py:14875` on interrupt)
- `pre_tool_call(tool_name, args, task_id, session_id, tool_call_id)` —
  `hermes_cli/plugins.py:1689`. Return `{"action": "block", "message": "..."}`
  to block a tool; first block directive wins; other returns ignored.
- `post_tool_call(tool_name, args, result, task_id, session_id, tool_call_id,
  duration_ms)` — `model_tools.py:995`. **Return value is discarded** (observer
  hook), so corrections are surfaced via the event stream + log, not by mutating
  the tool result.

### Why the plugin keeps its OWN trajectory buffer

`post_tool_call` hands the handler only the *current* call — no history. H4 loop
detection needs the trailing run, so `HarnessPlugin` accumulates a per-session
`list[ToolCall]` keyed by `session_id` (thread-locked; capped at 256), appends
the current call, and runs `detect_repeat_loop` over the buffer. The buffer is
seeded on `on_session_start` and dropped on `on_session_end`.

### Paper-faithfulness

H4 is GATE-FREE: it emits its correction event unconditionally and never calls
`try_admit` / `snapshot` / `restore`. The HASP regression gate lives in the
separate post-turn evolve pass (`harness_core.evolution_loop`), not in any
per-tool-call hook. A test asserts the gate is never touched on the H4 path.

## Lint + tests (real output)

- `ruff check plugins/self-evolving-harness` → **All checks passed!** (repo ruff
  0.15.10; only `PLW1514` enforced, and `plugins/**` is NOT ignored, so every
  file read/write specifies `encoding=`).
- `pytest` in the plugin dir → **128 passed**. The plugin dir has an
  `__init__.py` (it IS the plugin package), so the suite runs with
  `--import-mode=importlib` + `pythonpath=["."]` and a `conftest.py` that ignores
  the package `__init__.py`. The package's `harness_core` import has a relative
  (host) / top-level (tooling) fallback so it loads both ways.

## Live load proof (sideways instance)

Sideways `HERMES_HOME=G:\hermes-sideways` (copied `config.yaml` + `auth.json`
from the live `G:\hermes`; live gateway untouched). Plugin installed as a user
plugin and added to `plugins.enabled`. Model `MiniMax-M2.7-highspeed` via
`minimax-oauth` (static Bearer in auth.json, valid to 2027).

1. **Loads**: `hermes plugins list` shows
   `self-evolving-harness | enabled | 0.2.0 | user`. Programmatic load confirms
   `error=None`, the 4 hooks bound to `HarnessPlugin` methods, `/harness`
   registered, and the INFO line:
   `[self-evolving-harness] registered: 4 hooks (...) + /harness command`.

2. **Hook fires live**: drove a real one-shot M2.7 turn
   (`cli.py --query ... --toolsets terminal`) that ran the identical command
   `echo LOOPTEST` three times. Session `20260529_082826_ba6f41`. The H4
   `post_tool_call` hook accumulated the trajectory and emitted a real event:

   ```
   [pf_fired] H4 loop detected on `terminal` — You have called `terminal` with
   identical arguments 3 times in a row. This is a loop and it is not making
   progress. ...
   ```

   Captured in both `G:\hermes-sideways\self-evolving-harness\harness.log` (the
   event-stream surface) and `agent.log` at INFO, tagged with the real session
   id. `on_session_start` / `on_session_end` events fired on the same turn.

No web-dashboard surface was added (the plugin surfaces via the event stream,
the harness log, and the `/harness` command), so no dashboard screenshot is
applicable.

## Gate

green = true: plugin loads AND the post_tool_call hook fires live with captured
evidence (real MiniMax-M2.7 tool calls → real H4 loop-detection event).
