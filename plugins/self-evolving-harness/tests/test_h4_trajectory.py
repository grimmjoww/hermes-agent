"""H4 Trajectory Monitor — loop/stagnation detection (the layer Rei lacks).

Detects the count-based, content-agnostic failure pattern from Life-Harness
Harness.md: repeated identical tool calls = a self-reinforcing trajectory
failure, detectable without understanding the call's semantics.
"""
from harness_core.layers.h4_trajectory import ToolCall, Correction, detect_repeat_loop


def test_three_identical_consecutive_calls_trigger_correction():
    calls = [ToolCall("search_flights", {"origin": "JFK", "dest": "SFO"})] * 3
    result = detect_repeat_loop(calls, threshold=3)
    assert isinstance(result, Correction)
    assert result.tool_name == "search_flights"
    assert "loop" in result.guidance.lower() or "repeat" in result.guidance.lower()


def test_two_identical_calls_under_threshold_no_correction():
    calls = [ToolCall("search_flights", {"origin": "JFK", "dest": "SFO"})] * 2
    assert detect_repeat_loop(calls, threshold=3) is None


def test_three_distinct_calls_no_correction():
    calls = [
        ToolCall("search_flights", {"origin": "JFK", "dest": "SFO"}),
        ToolCall("search_flights", {"origin": "JFK", "dest": "LAX"}),
        ToolCall("book_flight", {"flight_id": "UA123"}),
    ]
    assert detect_repeat_loop(calls, threshold=3) is None


def test_only_trailing_run_counts_not_earlier_repeats():
    # earlier repeats that were broken by a different call must not trigger
    calls = [
        ToolCall("get_user", {"id": "u1"}),
        ToolCall("get_user", {"id": "u1"}),
        ToolCall("book_flight", {"flight_id": "UA123"}),  # breaks the run
        ToolCall("get_user", {"id": "u1"}),
    ]
    assert detect_repeat_loop(calls, threshold=3) is None
