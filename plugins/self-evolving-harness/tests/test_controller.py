"""HarnessController — runs the 4 layers behind a master + per-layer switch.

Mirrors Life-Harness's `--enabled` master switch: if the master is off, no
layer fires even if its individual flag is on (README: "If --enabled is not
passed, H2/H3/H4/H5 do not take effect even if their individual flags are
passed").
"""
from harness_core.controller import HarnessController
from harness_core.layers.h4_trajectory import ToolCall


def _looping_calls():
    return [ToolCall("search_flights", {"q": "JFK-SFO"})] * 3


def test_h4_enabled_detects_loop_post_execution():
    c = HarnessController(enabled=True, h4=True)
    corr = c.monitor_post_execution(_looping_calls())
    assert corr is not None
    assert corr.tool_name == "search_flights"


def test_master_disabled_suppresses_all_layers():
    c = HarnessController(enabled=False, h4=True)
    assert c.monitor_post_execution(_looping_calls()) is None


def test_layer_flag_off_suppresses_only_that_layer():
    c = HarnessController(enabled=True, h4=False)
    assert c.monitor_post_execution(_looping_calls()) is None


def test_defaults_all_layers_off_until_enabled():
    # a bare controller does nothing (safe default / off-by-default)
    c = HarnessController()
    assert c.monitor_post_execution(_looping_calls()) is None
