import json
import unittest
from pathlib import Path

import _path  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]


class SmokeTests(unittest.TestCase):
    def test_core_modules_import(self):
        import app.agent.critic  # noqa: F401
        import app.agent.orchestrator  # noqa: F401
        import app.agent.router  # noqa: F401
        import app.delayed_queue  # noqa: F401
        import app.task_queue  # noqa: F401
        import app.ticket_client  # noqa: F401

    def test_env_example_placeholder_only(self):
        text = (ROOT / ".env.example").read_text(encoding="utf-8")
        self.assertIn("your-api-key", text)
        self.assertNotIn("sk-", text)

    def test_golden_has_200_cases(self):
        data = json.loads((ROOT / "docs" / "golden_set.json").read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(data["cases"]), 200)


if __name__ == "__main__":
    unittest.main()
