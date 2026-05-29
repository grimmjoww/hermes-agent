"""Hermes plugin packaging tests — canonical v0.15.1 plugin API.

Asserts the packaging + wiring contract that is provable without a running
Hermes process:
  * plugin.yaml parses and declares the four lifecycle hooks;
  * register(ctx) calls ctx.register_hook(...) for exactly those four events
    and registers the /harness slash command;
  * the hook handlers accept the REAL v0.15.1 dispatch signatures (named
    kwargs from model_tools.py / conversation_loop.py);
  * the H4 post_tool_call path is GATE-FREE (no try_admit / snapshot / restore)
    and keeps its OWN per-session trajectory buffer;
  * paper-faithfulness guard: the source states CH is gate-free.

Live cross-process load + a real hook firing in a real turn is proven separately
on the sideways Hermes instance (see FOUNDATION_NOTES.md), not here.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

from harness_core.events import EventKind

PLUGIN_DIR = Path(__file__).resolve().parent.parent
MANIFEST = PLUGIN_DIR / "plugin.yaml"
INIT = PLUGIN_DIR / "__init__.py"


def _load_plugin_module():
    """Import the plugin __init__.py as a standalone package module.

    The plugin uses ``from .harness_core ...`` relative imports. In the test
    venv ``harness_core`` is already importable top-level (plugin dir on
    sys.path); we give the loaded module a package context and bind the
    top-level ``harness_core`` submodules under that package so the relative
    import resolves to the same objects.
    """
    import sys
    import types

    pkg_name = "selfevolving_harness_pkg"
    if pkg_name not in sys.modules:
        pkg = types.ModuleType(pkg_name)
        pkg.__path__ = [str(PLUGIN_DIR)]
        sys.modules[pkg_name] = pkg

    import harness_core  # noqa: F401
    import harness_core.controller  # noqa: F401
    import harness_core.events  # noqa: F401
    import harness_core.layers.h4_trajectory  # noqa: F401
    for sub in ("", ".controller", ".events", ".layers", ".layers.h4_trajectory"):
        modname = "harness_core" + sub
        sys.modules[f"{pkg_name}.harness_core{sub}"] = sys.modules[modname]

    spec = importlib.util.spec_from_file_location(f"{pkg_name}.__init__", INIT)
    module = importlib.util.module_from_spec(spec)
    module.__package__ = pkg_name
    sys.modules[f"{pkg_name}.__init__"] = module
    spec.loader.exec_module(module)
    return module


plugin = _load_plugin_module()


class _FakeCtx:
    """Minimal stand-in for hermes_cli.plugins.PluginContext."""

    def __init__(self) -> None:
        self.hooks: dict = {}
        self.commands: dict = {}

    def register_hook(self, hook_name, callback):
        self.hooks.setdefault(hook_name, []).append(callback)

    def register_command(self, name, handler, description="", args_hint=""):
        self.commands[name] = {
            "handler": handler,
            "description": description,
            "args_hint": args_hint,
        }


def _parse_manifest() -> dict:
    text = MANIFEST.read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore
        return yaml.safe_load(text)
    except Exception:
        data: dict = {"hooks": []}
        in_hooks = False
        for line in text.splitlines():
            if line.startswith("hooks:"):
                in_hooks = True
                continue
            if in_hooks:
                stripped = line.strip()
                if stripped.startswith("- "):
                    data["hooks"].append(stripped[2:].strip())
                elif stripped and not line.startswith(" "):
                    in_hooks = False
            elif ":" in line and not line.startswith(" "):
                key, _, val = line.partition(":")
                data[key.strip()] = val.strip().strip('"')
        return data


# --- manifest parse + hook declaration ---------------------------------------

def test_manifest_parses_and_declares_four_hooks():
    manifest = _parse_manifest()
    assert manifest["name"] == "self-evolving-harness"
    assert "version" in manifest
    assert set(manifest["hooks"]) == {
        "on_session_start",
        "pre_tool_call",
        "post_tool_call",
        "on_session_end",
    }


# --- register(ctx) wires the canonical API -----------------------------------

def test_register_binds_four_hooks_and_one_command():
    ctx = _FakeCtx()
    plugin.register(ctx)
    assert set(ctx.hooks) == set(plugin.VALID_HOOK_EVENTS)
    for _event, cbs in ctx.hooks.items():
        assert len(cbs) == 1
        assert callable(cbs[0])
    assert "harness" in ctx.commands
    assert callable(ctx.commands["harness"]["handler"])


def test_manifest_hooks_match_registered_hooks():
    manifest = _parse_manifest()
    ctx = _FakeCtx()
    plugin.register(ctx)
    assert set(manifest["hooks"]) == set(ctx.hooks)


def test_hook_handlers_accept_real_v0151_signatures():
    """Handlers must accept the exact named kwargs the host dispatches."""
    p = plugin.HarnessPlugin()
    p.on_session_start(session_id="s1", model="m", platform="cli")
    blk = p.pre_tool_call(
        tool_name="terminal", args={}, task_id="t", session_id="s1", tool_call_id="c"
    )
    assert blk is None  # H2 off by default -> allow
    p.post_tool_call(
        tool_name="terminal", args={"command": "ls"}, result="ok",
        task_id="t", session_id="s1", tool_call_id="c", duration_ms=12.3,
    )
    p.on_session_end(
        session_id="s1", completed=True, interrupted=False, model="m", platform="cli"
    )


# --- H4 keeps its OWN per-session buffer --------------------------------------

def test_h4_accumulates_trajectory_and_detects_loop():
    p = plugin.HarnessPlugin()
    p.on_session_start(session_id="s")
    args = {"command": "ls"}
    assert p.post_tool_call(tool_name="terminal", args=args, session_id="s") is None
    assert p.post_tool_call(tool_name="terminal", args=args, session_id="s") is None
    corr = p.post_tool_call(tool_name="terminal", args=args, session_id="s")
    assert corr is not None
    assert corr.tool_name == "terminal"


def test_h4_per_session_isolation():
    p = plugin.HarnessPlugin()
    args = {"command": "ls"}
    p.post_tool_call(tool_name="terminal", args=args, session_id="a")
    p.post_tool_call(tool_name="terminal", args=args, session_id="b")
    assert p.post_tool_call(tool_name="terminal", args=args, session_id="b") is None


def test_h4_is_gate_free():
    import harness_core.evolution_loop as el

    calls = {"try_admit": 0, "snapshot": 0, "restore": 0}
    orig = {
        "try_admit": el.try_admit,
        "snapshot": getattr(el.SkillLibrary, "snapshot", None),
        "restore": getattr(el.SkillLibrary, "restore", None),
    }

    def _wrap(name, fn):
        def inner(*a, **k):
            calls[name] += 1
            return fn(*a, **k)
        return inner

    el.try_admit = _wrap("try_admit", orig["try_admit"])
    if orig["snapshot"]:
        el.SkillLibrary.snapshot = _wrap("snapshot", orig["snapshot"])
    if orig["restore"]:
        el.SkillLibrary.restore = _wrap("restore", orig["restore"])
    try:
        p = plugin.HarnessPlugin()
        corr = None
        for _ in range(3):
            corr = p.post_tool_call(tool_name="search", args={}, session_id="s")
        assert corr is not None
        assert calls == {"try_admit": 0, "snapshot": 0, "restore": 0}
    finally:
        el.try_admit = orig["try_admit"]
        if orig["snapshot"]:
            el.SkillLibrary.snapshot = orig["snapshot"]
        if orig["restore"]:
            el.SkillLibrary.restore = orig["restore"]


def test_h4_emits_visible_event_on_correction():
    p = plugin.HarnessPlugin()
    seen: list = []
    p.events.subscribe(seen.append)
    for _ in range(3):
        p.post_tool_call(tool_name="loop_tool", args={}, session_id="s")
    assert any(e.kind == EventKind.PF_FIRED for e in seen)


def test_no_loop_no_correction():
    p = plugin.HarnessPlugin()
    assert p.post_tool_call(tool_name="a", args={}, session_id="s") is None
    assert p.post_tool_call(tool_name="b", args={}, session_id="s") is None


def test_session_lifecycle_emits_events():
    p = plugin.HarnessPlugin()
    seen: list = []
    p.events.subscribe(seen.append)
    p.on_session_start(session_id="s", model="m", platform="cli")
    p.on_session_end(session_id="s", completed=True, interrupted=False)
    kinds = {e.kind for e in seen}
    assert EventKind.SESSION_START in kinds
    assert EventKind.SESSION_END in kinds


def test_slash_command_status_renders():
    p = plugin.HarnessPlugin()
    out = p.handle_command("status")
    assert "self-evolving-harness" in out
    assert "H4" in out


# --- faithfulness guard ------------------------------------------------------

def test_plugin_makes_no_ch_rollback_claim():
    src = INIT.read_text(encoding="utf-8").lower()
    assert "gate-free" in src
    assert "continual-harness is gate-free" in src
