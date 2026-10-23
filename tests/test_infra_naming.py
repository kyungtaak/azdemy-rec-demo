import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class InfrastructureNamingTests(unittest.TestCase):
    def test_bicep_has_no_retired_project_names(self):
        for path in (ROOT / "infra").glob("*.bicep"):
            with self.subTest(template=path.name):
                self.assertIsNone(re.search(
                    r"genius|\bkt\b|\bkt[-_]", path.read_text(encoding="utf-8"), re.IGNORECASE))

    def test_operator_scripts_do_not_target_retired_azure_resources(self):
        for folder in ("infra", "agent"):
            for path in (ROOT / folder).glob("*.ps1"):
                with self.subTest(script=path.name):
                    self.assertNotIn("genius", path.read_text(encoding="utf-8").lower())


if __name__ == "__main__":
    unittest.main()
