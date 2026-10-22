import unittest
import json
from pathlib import Path
from types import SimpleNamespace
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fabric.cloud import request, workspace_endpoints
from api.publication import write_manifest
from fabric.run import ROOT, confirm_publication, main, publish, put_file, stop_compute, wait_operation


class OperatorClientTests(unittest.TestCase):
    def test_head_uses_curl_no_body_mode(self):
        def execute(command, **kwargs):
            self.assertIn("--head", command)
            Path(command[command.index("--output") + 1]).write_bytes(b"")
            Path(command[command.index("--dump-header") + 1]).write_text(
                "HTTP/1.1 404 Not Found\nx-ms-error-code: PathNotFound\n", encoding="utf-8")
            return SimpleNamespace(stdout="404")

        with patch("fabric.cloud.token", return_value="test-token"), patch(
                "fabric.cloud.subprocess.run", side_effect=execute):
            status, headers, _ = request(
                "HEAD", "https://onelake.dfs.fabric.microsoft.com/missing",
                "https://storage.azure.com/", allow_status=(404,))
        self.assertEqual(status, 404)
        self.assertEqual(headers["x-ms-error-code"], "PathNotFound")

    def test_unapproved_hosts_are_rejected_before_token_acquisition(self):
        with patch("fabric.cloud.token") as credential:
            with self.assertRaises(ValueError):
                request("GET", "https://example.org/data", "https://storage.azure.com/")
            credential.assert_not_called()

    def test_workspace_endpoint_uses_guid_without_dashes(self):
        api, dfs = workspace_endpoints("a9e11b86-dd2e-44ef-9454-461d89793045")
        self.assertEqual(api, "https://a9e11b86dd2e44ef9454461d89793045.za9.w.api.fabric.microsoft.com")
        self.assertEqual(dfs, "https://a9e11b86dd2e44ef9454461d89793045.za9.dfs.fabric.microsoft.com")

    def test_empty_code_file_is_created_without_zero_length_append(self):
        calls = []

        def server(method, url, *args, **kwargs):
            calls.append((method, url))
            return (404 if method == "HEAD" else 201), {}, b""

        state = {"workspace_id": "a9e11b86-dd2e-44ef-9454-461d89793045",
                 "lakehouse_id": "lakehouse"}
        with patch("fabric.run.request", side_effect=server):
            put_file(state, "code/api/__init__.py", b"", "socks5h://localhost:1080")
        self.assertFalse(any("action=append" in url for _, url in calls))
        self.assertTrue(any("action=flush&position=0" in url for _, url in calls))

    def test_lro_accepts_own_workspace_private_endpoint(self):
        workspace = "a9e11b86-dd2e-44ef-9454-461d89793045"
        endpoint, _ = workspace_endpoints(workspace)
        responses = [(200, {}, {"status": "Succeeded"}), (200, {}, {"id": "notebook"})]
        with patch("fabric.run.json_request", side_effect=responses), patch("fabric.run.time.sleep"):
            result = wait_operation(
                {"location": endpoint + "/v1/operations/operation", "retry-after": "1"},
                "socks5h://localhost:1080", {"workspace_id": workspace})
        self.assertEqual(result["id"], "notebook")

    def test_update_lro_does_not_request_a_result_when_operation_has_no_result(self):
        workspace = "a9e11b86-dd2e-44ef-9454-461d89793045"
        endpoint, _ = workspace_endpoints(workspace)
        with patch("fabric.run.json_request", return_value=(
                200, {}, {"status": "Succeeded"})) as api, patch("fabric.run.time.sleep"):
            result = wait_operation(
                {"location": endpoint + "/v1/operations/update"}, "socks5h://localhost:1080",
                {"workspace_id": workspace}, result_required=False)
        self.assertEqual(result["status"], "Succeeded")
        api.assert_called_once()

    def test_bootstrap_dispatches_explicit_legacy_migration(self):
        def server(method, url, *args, **kwargs):
            name = url.rsplit("/", 1)[-1]
            return 200, {}, (ROOT / "data" / name).read_bytes()

        with TemporaryDirectory() as directory:
            state = Path(directory) / "state.json"
            state.write_text(json.dumps({"workspace_id": "workspace"}), encoding="utf-8")
            with patch("sys.argv", ["fabric.run", "bootstrap", "--state", str(state)]), patch(
                "fabric.run.request", side_effect=server), patch("fabric.run.publish") as publisher:
                main()
            self.assertTrue(publisher.call_args.kwargs["bootstrap"])

    def test_capacity_pause_keeps_jump_host_for_independent_api_verification(self):
        state = {"owned_capacity": True, "owned_vm": True}
        with TemporaryDirectory() as directory, patch(
                "fabric.run.request", return_value=(200, {}, b"")) as arm:
            stop_compute(state, Path(directory) / "state.json", capacity_only=True)
        self.assertFalse(state["owned_capacity"])
        self.assertTrue(state["owned_vm"])
        self.assertEqual(arm.call_count, 1)
        self.assertIn("/suspend?", arm.call_args.args[1])

    def test_publication_staging_is_not_success_until_specific_receipt_is_confirmed(self):
        pending = {}

        def server(method, url, audience, body=None, *args, **kwargs):
            if url.endswith("/active.json"):
                return 404, {}, b""
            if url.endswith("/pending.json"):
                pending.update(json.loads(body))
            if "/appsettings/list?" in url:
                return 200, {}, json.dumps({"properties": {
                    "GENIUS_PUBLICATION_ROOT": "/home/data/genius-recommendations"}}).encode()
            self.assertNotIn("/restart?", url)
            if "/requests/" in url:
                return 200, {}, json.dumps({
                    "status": "completed", "request_id": pending["request_id"],
                    "version": pending["version"]}).encode()
            return 200, {}, b""

        with TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("courses.synthetic.json", "learners.synthetic.json",
                         "recommendations.synthetic.json"):
                (root / name).write_bytes((ROOT / "data" / name).read_bytes())
            write_manifest(root)
            state = {}
            with patch("fabric.run.request", side_effect=server), patch(
                    "fabric.run.subprocess.run", return_value=SimpleNamespace(stdout="401")) as commands:
                publish(root, state, "socks5h://localhost:1080", root / "state.json", bootstrap=True)
                commands.assert_not_called()
                self.assertNotIn("bootstrap_publication", state)
                self.assertEqual(state["pending_publication"]["request_id"], pending["request_id"])
                confirm_publication(state, "socks5h://localhost:1080", root / "state.json")
            self.assertEqual(state["bootstrap_publication"]["status"], "completed")
