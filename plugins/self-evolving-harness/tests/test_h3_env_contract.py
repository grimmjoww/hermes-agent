"""H3 Environment Contract — augment tool descriptions at episode init.

Per Life-Harness: the agent's tool call may be syntactically valid but
semantically wrong for THIS environment. H3 embeds environment-specific
constraints directly into the tool descriptions the agent reads, calibrating
the tool contract once at the start. It fixes contract misunderstanding, not
reasoning.
"""
from harness_core.layers.h3_env_contract import ToolDoc, augment_tool_descriptions


def test_appends_contract_to_matching_tool():
    tools = [ToolDoc("book_flight", "Books a flight.")]
    out = augment_tool_descriptions(tools, {"book_flight": "Always confirm the price with the user first."})
    assert "confirm the price" in out[0].description
    assert "Books a flight." in out[0].description  # original preserved


def test_tool_without_contract_is_unchanged():
    tools = [ToolDoc("search_flights", "Search for flights.")]
    out = augment_tool_descriptions(tools, {"book_flight": "irrelevant"})
    assert out[0].description == "Search for flights."


def test_idempotent_no_duplicate_when_already_present():
    doc = "Books a flight. Always confirm the price with the user first."
    tools = [ToolDoc("book_flight", doc)]
    out = augment_tool_descriptions(tools, {"book_flight": "Always confirm the price with the user first."})
    assert out[0].description.count("confirm the price") == 1
