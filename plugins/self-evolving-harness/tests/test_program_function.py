"""HASP Program Functions — skills as executable state-action interventions.

Faithful to HASP (arXiv 2605.17734, Fig 1): a PF has should_activate(state,
action) and intervene(state, action) returning EITHER an ActionOverride
(modify the action) OR a ContextInjection (inject corrective text). A registry
retrieves PFs, evaluates predicates, executes the first valid intervention, and
emits a structured execution record (original action, intervention, layer).

This adds the MODIFY_ACTION capability we previously lacked (we only blocked).
"""
from harness_core.program_function import (
    ActionOverride,
    ContextInjection,
    AgentState,
    PFRegistry,
    PFExecution,
)
from harness_core.layers.h4_trajectory import ToolCall


class _BlockUnknownToolPF:
    name = "block_unknown_teleport"
    layer = "H2"

    def should_activate(self, state, action):
        return action.name == "teleport"

    def intervene(self, state, action):
        return ContextInjection("'teleport' is not an available tool; choose a valid one.")


class _RepairMissingUserIdPF:
    name = "repair_user_id"
    layer = "H2"

    def should_activate(self, state, action):
        return action.name == "get_user" and "user_id" not in action.args

    def intervene(self, state, action):
        repaired = ToolCall("get_user", {**action.args, "user_id": state.memory["current_user"]})
        return ActionOverride(repaired)


def _state():
    return AgentState(history=[], memory={"current_user": "u1"})


def test_context_injection_intervention():
    reg = PFRegistry([_BlockUnknownToolPF()])
    out = reg.apply(_state(), ToolCall("teleport", {}))
    assert isinstance(out, PFExecution)
    assert isinstance(out.intervention, ContextInjection)
    assert out.pf_name == "block_unknown_teleport"
    assert out.layer == "H2"


def test_action_override_repairs_the_action():
    reg = PFRegistry([_RepairMissingUserIdPF()])
    out = reg.apply(_state(), ToolCall("get_user", {}))
    assert isinstance(out.intervention, ActionOverride)
    assert out.intervention.action.args["user_id"] == "u1"  # MODIFY_ACTION


def test_no_pf_activates_returns_none():
    reg = PFRegistry([_BlockUnknownToolPF()])
    assert reg.apply(_state(), ToolCall("get_user", {"user_id": "u1"})) is None


def test_first_activating_pf_wins_and_record_keeps_original_action():
    reg = PFRegistry([_BlockUnknownToolPF(), _RepairMissingUserIdPF()])
    out = reg.apply(_state(), ToolCall("get_user", {}))
    assert out.pf_name == "repair_user_id"
    assert out.original_action.name == "get_user"
    assert out.original_action.args == {}
