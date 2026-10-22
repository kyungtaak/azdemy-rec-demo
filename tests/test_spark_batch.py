import base64
import io
import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock, patch
from zipfile import ZipFile

from fabric.run import ROOT
from fabric.spark_definition import package_code, spark_definition
from azdemy_recommendations.batch_entrypoint import decode_request, run_batch, runtime_context


class SparkBatchTests(unittest.TestCase):
    def setUp(self):
        self.workspace = "a9e11b86-dd2e-44ef-9454-461d89793045"
        self.lakehouse = "d1a58be0-d465-4ceb-b3d7-f4ae2df84d65"
        self.key = "59fce683-2fde-43e6-b30d-6b6ddc82e403"
        self.config = {"workspace_id": self.workspace, "lakehouse_id": self.lakehouse,
                       "approved_model": {"model_uri": "runs:/approved/model", "model_version": "1"}}
        self.encoded = base64.b64encode(json.dumps(self.config).encode()).decode()
        self.filesystem = Mock()
        self.filesystem.getUri.return_value = (
            f"abfss://{self.workspace}@onelake.dfs.fabric.microsoft.com")
        self.filesystem.getWorkingDirectory.return_value = (
            f"abfss://{self.workspace}@onelake.dfs.fabric.microsoft.com/{self.lakehouse}")

    def test_request_uses_pipeline_key_and_timezone_without_changing_model(self):
        request = decode_request(self.encoded, self.key, "2026-10-21T10:00:00Z")
        self.assertEqual(request["batch_key"], self.key)
        self.assertEqual(request["approved_model"], self.config["approved_model"])
        self.assertEqual(request["as_of"], "2026-10-21T10:00:00+00:00")
        self.assertNotIn("batch_key", self.config)

    def test_invalid_batch_path_and_naive_time_are_rejected(self):
        for key in ("../other", "a' OR 1=1", "", "not-a-guid"):
            with self.subTest(key=key), self.assertRaises(ValueError):
                decode_request(self.encoded, key, "2026-10-21T10:00:00Z")
        with self.assertRaises(ValueError):
            decode_request(self.encoded, self.key, "2026-10-21T10:00:00")

    def test_actual_default_filesystem_binding_supplies_context_not_notebook_metadata(self):
        context = runtime_context(self.config, self.filesystem, "application_123_0001")
        self.assertEqual(context, {
            "currentWorkspaceId": self.workspace, "defaultLakehouseId": self.lakehouse,
            "activityId": "application_123_0001"})
        self.filesystem.getWorkingDirectory.return_value = (
            f"abfss://{self.workspace}@onelake.dfs.fabric.microsoft.com/"
            "00000000-0000-0000-0000-000000000000")
        with self.assertRaises(ValueError):
            runtime_context(self.config, self.filesystem, "application_123_0001")

    def test_mount_is_keyless_and_removed_after_success_or_batch_failure(self):
        config = dict(self.config, batch_key=self.key)
        spark = SimpleNamespace(sparkContext=SimpleNamespace(applicationId="application_123_0001"))
        utilities = Mock()
        utilities.fs.mount.return_value = True
        utilities.fs.getMountPath.return_value = "/mounted/lakehouse"
        with patch("azdemy_recommendations.batch_entrypoint.default_filesystem",
                   return_value=self.filesystem), patch(
                       "azdemy_recommendations.batch_entrypoint.batch", return_value={"count": 6}) as batch:
            self.assertEqual(run_batch(config, spark, utilities), {"count": 6})
            self.assertEqual(batch.call_args.kwargs["files_root"], Path("/mounted/lakehouse/Files"))
            self.assertEqual(len(utilities.fs.mount.call_args.args), 2)
            utilities.fs.unmount.assert_called_once()
        utilities.reset_mock()
        with patch("azdemy_recommendations.batch_entrypoint.default_filesystem",
                   return_value=self.filesystem), patch(
                       "azdemy_recommendations.batch_entrypoint.batch",
                       side_effect=ValueError("batch validation failed")):
            with self.assertRaisesRegex(ValueError, "batch validation failed"):
                run_batch(config, spark, utilities)
            utilities.fs.unmount.assert_called_once()

    def test_python_package_is_deterministic_and_contains_shared_batch_without_caches(self):
        payload, version = package_code(ROOT)
        self.assertEqual((payload, version), package_code(ROOT))
        with ZipFile(io.BytesIO(payload)) as archive:
            self.assertIsNone(archive.testzip())
            self.assertIn("azdemy_recommendations/batch_entrypoint.py", archive.namelist())
            self.assertIn("azdemy_recommendations/spark_job.py", archive.namelist())
            self.assertTrue(all(name.startswith("azdemy_recommendations/")
                                for name in archive.namelist()))
            self.assertFalse(any("__pycache__" in name for name in archive.namelist()))
            self.assertFalse(any(name.endswith(".ipynb") for name in archive.namelist()))
        with TemporaryDirectory() as directory:
            package = Path(directory) / "azdemy_recommendations.zip"
            package.write_bytes(payload)
            subprocess.run([
                sys.executable, "-I", "-c",
                "import sys; sys.path.insert(0, sys.argv[1]); "
                "from azdemy_recommendations.batch_entrypoint import run_batch",
                str(package),
            ], check=True, capture_output=True, text=True)

    def test_spark_definition_binds_existing_lakehouse_and_python_main_not_a_notebook(self):
        source = (ROOT / "fabric" / "spark_batch_main.py").read_bytes()
        definition = spark_definition(self.config, source)
        self.assertEqual(definition["format"], "SparkJobDefinitionV2")
        properties = json.loads(base64.b64decode(definition["parts"][0]["payload"]))
        self.assertEqual(properties["defaultLakehouseArtifactId"], self.lakehouse)
        self.assertEqual(properties["executableFile"], "spark_batch_main.py")
        self.assertEqual(properties["language"], "Python")
        self.assertEqual(properties["additionalLibraryUris"], [])
        self.assertIn(b"addPyFile", source)
        self.assertIn(b"azdemy_recommendations.zip", source)
        self.assertIn(b"from azdemy_recommendations.batch_entrypoint import main", source)
        self.assertIsNone(properties["retryPolicy"])
        self.assertEqual(base64.b64decode(definition["parts"][1]["payload"]), source)
