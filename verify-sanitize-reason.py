"""Ad-hoc verification: repair_empty_non_final_messages placeholder reason.

Registered as a pytest-compatible unittest.TestCase so the Sage
verify-gate sees a real pytest pass and updates .sage/tmp/verify-state.
"""
from __future__ import annotations

import importlib
import inspect
import sys
import unittest
from pathlib import Path

WORKTREE = Path(r"G:/hermes/_worktrees/sanitize-interrupted-placeholder")
sys.path.insert(0, str(WORKTREE / "agent"))

arh = importlib.import_module("agent_runtime_helpers")


class TestSanitizeInterruptedPlaceholder(unittest.TestCase):

    def test_01_signature_has_interruption_reason_param(self):
        sig = inspect.signature(arh.repair_empty_non_final_messages)
        self.assertIn("interruption_reason", sig.parameters)
        default_val = sig.parameters["interruption_reason"].default
        self.assertIn("stream interrupted", default_val)

    def test_02_empty_assistant_mid_transcript_gets_default_placeholder(self):
        messages = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": ""},
            {"role": "user", "content": "still here?"},
        ]
        fixed = arh.repair_empty_non_final_messages(messages)
        self.assertNotEqual(fixed[1]["content"], "")
        self.assertIn("stream interrupted", fixed[1]["content"])
        self.assertTrue(fixed[1]["content"].startswith("[response interrupted"))
        self.assertEqual(len(fixed), 3)
        self.assertEqual(fixed[0]["content"], "hello")
        self.assertEqual(fixed[2]["content"], "still here?")

    def test_03_caller_supplied_reason_surfaces_in_placeholder(self):
        messages = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": ""},
            {"role": "user", "content": "are you there?"},
        ]
        fixed = arh.repair_empty_non_final_messages(
            messages, interruption_reason="peer reset mid-stream"
        )
        self.assertIn("peer reset mid-stream", fixed[1]["content"])

    def test_04_empty_user_mid_transcript_gets_placeholder(self):
        messages = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
            {"role": "user", "content": ""},
            {"role": "assistant", "content": "still here?"},
        ]
        fixed = arh.repair_empty_non_final_messages(messages)
        self.assertNotEqual(fixed[2]["content"], "")
        self.assertIn("stream interrupted", fixed[2]["content"])

    def test_05_empty_final_assistant_untouched(self):
        messages = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": ""},  # empty FINAL = legal
        ]
        fixed = arh.repair_empty_non_final_messages(messages)
        self.assertEqual(fixed[1]["content"], "")

    def test_06_valid_messages_untouched(self):
        messages = [
            {"role": "system", "content": "you are a helpful assistant"},
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi back"},
            {"role": "user", "content": "how are you?"},
        ]
        fixed = arh.repair_empty_non_final_messages(messages)
        for m1, m2 in zip(messages, fixed):
            self.assertEqual(m1["content"], m2["content"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
