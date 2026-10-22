import base64
import copy
import json
import unittest

from fabric.pipeline import pipeline_definition


class ManualPipelineTests(unittest.TestCase):
    def setUp(self):
        self.state = {
            "workspace_id": "a9e11b86-dd2e-44ef-9454-461d89793045",
            "lakehouse_id": "d1a58be0-d465-4ceb-b3d7-f4ae2df84d65",
            "batch_execution": {"notebook_id": "a8973a50-a5bd-4487-aff8-fea7d18c8b23"},
            "spark_job": {"id": "90fed26c-3efc-4107-9f2b-6b2c06d4ce2c",
                          "code_version": "spark-code-hash", "code_path": "code/spark-code-hash",
                          "package_sha256": "c" * 64,
                          "connection_id": "de227a09-fff9-44a5-8190-150cefadafe1"},
            "input_hashes": {"courses.synthetic.json": "a" * 64},
            "input_path": "inputs/input-hash", "code_path": "code/code-hash",
            "code_version": "code-hash", "training_key": "existing-training",
            "trained_model": {"model_uri": "runs:/approved-run/model", "model_version": "1",
                              "mlflow_run_id": "approved-run"},
            "batch_key": "previous-batch", "as_of": "2026-10-21T02:22:00Z",
        }

    def content(self):
        definition = pipeline_definition(self.state)
        self.assertEqual(len(definition["parts"]), 1)
        part = definition["parts"][0]
        self.assertEqual(part["path"], "pipeline-content.json")
        self.assertEqual(part["payloadType"], "InlineBase64")
        return json.loads(base64.b64decode(part["payload"]))

    def test_only_native_spark_job_runs_without_notebook_training_or_publication(self):
        content = self.content()
        activities = content["properties"]["activities"]
        self.assertEqual(len(activities), 1)
        activity = activities[0]
        self.assertEqual(activity["type"], "FabricSparkJobDefinition")
        self.assertEqual(activity["typeProperties"]["sparkJobDefinitionId"],
                         self.state["spark_job"]["id"])
        self.assertNotIn("notebookId", activity["typeProperties"])
        self.assertEqual(activity["typeProperties"]["workspaceId"], self.state["workspace_id"])
        self.assertEqual(activity["dependsOn"], [])
        self.assertEqual(activity["policy"]["retry"], 0)
        self.assertNotIn("schedules", content["properties"])
        self.assertNotIn("triggers", content["properties"])
        self.assertEqual(activity["externalReferences"], {
            "connection": self.state["spark_job"]["connection_id"]})

    def test_manual_run_has_unique_key_and_stable_trigger_time_not_the_old_batch(self):
        activity = self.content()["properties"]["activities"][0]
        parameter = activity["typeProperties"]["commandLineArguments"]
        self.assertIsInstance(parameter, str)
        expression = parameter
        self.assertIn("pipeline().RunId", expression)
        self.assertIn("pipeline().TriggerTime", expression)
        self.assertNotIn("previous-batch", expression)
        self.assertNotIn("utcNow()", expression)
        self.assertNotIn("GENIUS_PUBLICATION_ROOT", expression)

    def test_definition_is_deterministic_does_not_mutate_state_and_requires_pinned_model(self):
        before = copy.deepcopy(self.state)
        self.assertEqual(pipeline_definition(self.state), pipeline_definition(self.state))
        self.assertEqual(self.state, before)
        self.state["trained_model"]["model_version"] = ""
        with self.assertRaises(ValueError):
            pipeline_definition(self.state)

    def test_command_arguments_encode_config_without_shell_or_expression_quotes(self):
        self.state["training_key"] = "operator's-training"
        content = self.content()
        expression = content["properties"]["activities"][0]["typeProperties"][
            "commandLineArguments"]
        encoded = expression.split("--config-base64 ", 1)[1].split(" ", 1)[0]
        config = json.loads(base64.b64decode(encoded))
        self.assertEqual(config["training_key"], "operator's-training")
        self.assertEqual(config["approved_model"]["model_uri"], "runs:/approved-run/model")
        self.assertNotIn("batch_key", config)
        self.assertNotIn("as_of", config)
