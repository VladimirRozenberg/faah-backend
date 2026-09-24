import asyncio
import unittest
from unittest.mock import AsyncMock

from models import AssetNiche, ClassificationAsset, PortfolioStrategistRun
from prompt.recording import record_prompt, render_prompt_snapshot


class FakeSession:
    def __init__(self):
        self.added = []
        self.flush = AsyncMock()

    def add(self, item):
        self.added.append(item)


class PromptRecordingTests(unittest.TestCase):
    def test_snapshot_contains_both_exact_message_parts(self):
        snapshot = render_prompt_snapshot(
            "System rule with spacing.  ",
            "  User input and context.",
        )

        self.assertEqual(
            snapshot,
            "SYSTEM INSTRUCTIONS\nSystem rule with spacing.  \n\n"
            "USER PROMPT\n  User input and context.",
        )

    def test_record_prompt_adds_and_flushes_one_snapshot(self):
        db = FakeSession()

        prompt = asyncio.run(
            record_prompt(
                db,
                name="Asset detection",
                prompt_type="asset_detection",
                system_instructions="System",
                user_prompt="User",
            )
        )

        self.assertEqual(db.added, [prompt])
        db.flush.assert_awaited_once()
        self.assertEqual(prompt.prm_type, "asset_detection")
        self.assertIn("SYSTEM INSTRUCTIONS\nSystem", prompt.prm_prompt_text)
        self.assertIn("USER PROMPT\nUser", prompt.prm_prompt_text)

    def test_ai_generated_link_tables_expose_prompt_references(self):
        self.assertIn("ani_prm_id", AssetNiche.__table__.c)
        self.assertIn("cla_prm_id", ClassificationAsset.__table__.c)
        self.assertIn("psr_prm_id", PortfolioStrategistRun.__table__.c)


if __name__ == "__main__":
    unittest.main()
