"""H2 Action Gate — pre-execution validity check.

Per Life-Harness: detect action-interface errors BEFORE execution using prior
information (the tool contract). Some are blocked with corrective feedback;
the agent then self-corrects. This is the deterministic, judge-before-execute
layer.
"""
from harness_core.layers.h2_action_gate import ToolSpec, GateDecision, check_tool_call
from harness_core.layers.h4_trajectory import ToolCall

SPECS = {
    "book_flight": ToolSpec(name="book_flight", required=["flight_id", "user_id"]),
    "get_user": ToolSpec(name="get_user", required=["user_id"]),
}


def test_unknown_tool_is_blocked():
    d = check_tool_call(ToolCall("teleport", {}), SPECS)
    assert d.action == "block"
    assert "unknown" in d.reason.lower()


def test_missing_required_arg_is_blocked_and_names_the_arg():
    d = check_tool_call(ToolCall("book_flight", {"flight_id": "UA1"}), SPECS)
    assert d.action == "block"
    assert "user_id" in d.reason


def test_valid_call_is_allowed():
    d = check_tool_call(ToolCall("book_flight", {"flight_id": "UA1", "user_id": "u1"}), SPECS)
    assert d.action == "allow"


def test_block_decision_carries_corrective_guidance():
    d = check_tool_call(ToolCall("get_user", {}), SPECS)
    assert d.action == "block"
    assert d.guidance  # non-empty, so the agent can self-correct
