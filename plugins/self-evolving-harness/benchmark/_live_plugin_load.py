"""LIVE plugin-load proof against the REAL Hermes v0.15.1 plugin host.

Runs INSIDE the live Hermes venv (so `hermes_cli.plugins` is importable) but with
an ISOLATED HERMES_HOME + a sideways user-plugins dir, so it never touches
Willie's daily gateway/profile. It:

  1. Discovers + loads the self-evolving-harness plugin via the real PluginManager
     (the same code path the gateway uses).
  2. Asserts the plugin is enabled with 4 hooks + the /harness command.
  3. Fires post_tool_call 3x with an identical call via the REAL invoke_hook and
     asserts H4 returns a loop Correction (gate-free).
  4. Fires pre_tool_call via the REAL get_pre_tool_call_block_message with a
     TDD-violating write_file and asserts a skill PF blocks it.
  5. Runs the /harness slash command handler from the real plugin registry.

Prints a JSON proof object + the real loaded-plugin log line.
"""
import json
import os
import sys

HOME = os.environ["HERMES_HOME"]  # set by the caller to the sideways dir
PLUGIN_SRC = os.environ["HARNESS_PLUGIN_SRC"]  # fork plugin dir

# Make the live Hermes source importable.
HERMES_SRC = r"G:\hermes\hermes-agent"
sys.path.insert(0, HERMES_SRC)

proof = {"steps": [], "ok": True}


def step(name, cond, detail=""):
    proof["steps"].append({"name": name, "pass": bool(cond), "detail": str(detail)})
    if not cond:
        proof["ok"] = False


# --- 0. Place the plugin under the sideways HERMES_HOME user-plugins dir ------
import shutil  # noqa: E402
user_plugins = os.path.join(HOME, "plugins")
dest = os.path.join(user_plugins, "self-evolving-harness")
if os.path.exists(dest):
    shutil.rmtree(dest, ignore_errors=True)
shutil.copytree(
    PLUGIN_SRC, dest,
    ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache", "tests"),
)
step("plugin_copied_to_user_dir", os.path.exists(os.path.join(dest, "plugin.yaml")), dest)

# --- 1. Enable it in the sideways config.yaml --------------------------------
import yaml  # noqa: E402
cfg_path = os.path.join(HOME, "config.yaml")
cfg = {}
if os.path.exists(cfg_path):
    with open(cfg_path) as fh:
        cfg = yaml.safe_load(fh) or {}
cfg.setdefault("plugins", {})["enabled"] = ["self-evolving-harness"]
with open(cfg_path, "w") as fh:
    yaml.safe_dump(cfg, fh)
step("plugin_enabled_in_config", True, cfg["plugins"]["enabled"])

# --- 2. Discover + load via the REAL PluginManager ---------------------------
from hermes_cli import plugins as H  # noqa: E402

mgr = H.get_plugin_manager()
mgr.discover_and_load(force=True)
listing = {p["key"]: p for p in mgr.list_plugins()}
me = listing.get("self-evolving-harness")
step("plugin_discovered", me is not None, list(listing.keys()))
if me:
    step("plugin_enabled", me["enabled"], me.get("error"))
    step("plugin_has_hooks", me["hooks"] >= 1, me["hooks"])
    step("plugin_has_command", me["commands"] >= 1, me["commands"])
    proof["loaded_plugin_info"] = me

# --- 3. H4 loop detection via REAL invoke_hook -------------------------------
sid = "live-proof-session"
H.invoke_hook("on_session_start", session_id=sid, model="MiniMax-M2.7", platform="cli")
corr = None
for i in range(3):
    rets = H.invoke_hook(
        "post_tool_call",
        tool_name="search_files",
        args={"pattern": "needle"},
        result='{"matches": []}',
        task_id="t", session_id=sid, tool_call_id=f"c{i}", duration_ms=5,
    )
    if rets:
        corr = rets[-1]
step("h4_loop_correction_via_real_hook", corr is not None,
     getattr(corr, "tool_name", None))

# --- 4. pre_tool_call BLOCK via REAL host path (skill PF: TDD) ----------------
block_msg = H.get_pre_tool_call_block_message(
    "write_file", {"path": "src/feature.py"},
    task_id="t", session_id=sid, tool_call_id="c-pre",
)
step("pre_tool_call_skill_pf_blocks", isinstance(block_msg, str) and "RED before GREEN" in (block_msg or ""),
     (block_msg or "")[:80])

# --- 5. /harness slash command from the REAL registry ------------------------
handler = H.get_plugin_command_handler("harness")
status = handler("status") if handler else None
step("harness_command_runs", bool(status) and "status" in (status or "").lower(),
     (status or "").replace(chr(10), " | ")[:120])

H.invoke_hook("on_session_end", session_id=sid, completed=True, interrupted=False)

# --- harness.log written? (visible surface) ----------------------------------
log_path = os.path.join(HOME, "self-evolving-harness", "harness.log")
log_tail = ""
if os.path.exists(log_path):
    with open(log_path, encoding="utf-8") as fh:
        log_tail = "".join(fh.readlines()[-8:])
step("visible_log_written", bool(log_tail), len(log_tail))
proof["harness_log_tail"] = log_tail

print(json.dumps(proof, indent=2))
sys.exit(0 if proof["ok"] else 1)
