import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from zipfile import ZipFile

from infra.package_api import main


class ApiPackagingTests(unittest.TestCase):
    def test_api_archive_contains_importable_shared_package_and_synthetic_data(self):
        with TemporaryDirectory() as directory:
            package = Path(directory) / "azdemy-api.zip"
            with patch.object(sys, "argv", ["package_api", "--output", str(package)]), patch(
                "infra.package_api.subprocess.run"
            ) as install:
                main()
            install.assert_called_once()
            with ZipFile(package) as archive:
                self.assertIsNone(archive.testzip())
                self.assertIn("api/main.py", archive.namelist())
                self.assertIn("azdemy_recommendations/eligibility.py", archive.namelist())
                self.assertIn("azdemy_recommendations/reasons.py", archive.namelist())
                self.assertIn("data/courses.synthetic.json", archive.namelist())
                self.assertFalse(any("__pycache__" in name for name in archive.namelist()))
            subprocess.run([
                sys.executable, "-I", "-c",
                "import sys; sys.path.insert(0, sys.argv[1]); "
                "from api.main import create_app; "
                "assert create_app().openapi()['info']['title'] == "
                "'Azdemy Read-only Education API'",
                str(package),
            ], check=True, capture_output=True, text=True)


if __name__ == "__main__":
    unittest.main()
