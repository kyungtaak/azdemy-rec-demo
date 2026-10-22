import hashlib
import json
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from api.main import DATA_DIR
from api.publication import (
    activate_release, active_version, load_release, process_pending, read_active_store,
    stage_release, write_manifest,
)
from tests.test_api import NOW


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.source = self.root / "source"
        self.source.mkdir()
        for path in DATA_DIR.glob("*.synthetic.json"):
            (self.source / path.name).write_bytes(path.read_bytes())
        self.version = "2026-10-20.1"
        write_manifest(self.source)

    def stage(self):
        return stage_release(self.root / "published", self.source)

    def test_valid_release_activation_and_restart_load(self):
        self.stage()
        root = self.root / "published"
        activate_release(root, self.version, None, NOW)
        store = read_active_store(root, NOW)
        self.assertEqual(active_version(root), self.version)
        self.assertEqual(store.snapshot.data_version, self.version)
        self.assertEqual(load_release(root, self.version, NOW).catalog_version, "2026-10-20.1")

    def test_checksum_failure_does_not_replace_previous(self):
        self.stage()
        root = self.root / "published"
        activate_release(root, self.version, None, NOW)
        (self.source / "recommendations.synthetic.json").write_text("{}", encoding="utf-8")
        with self.assertRaises(ValueError):
            stage_release(root, self.source)
        self.assertEqual(active_version(root), self.version)

    def test_idempotent_stage_and_conflicting_version_rejected(self):
        root = self.root / "published"
        self.stage()
        self.stage()
        snapshot_path = self.source / "recommendations.synthetic.json"
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
        snapshot["personalized"]["learner-a"][0]["reason"] += " changed"
        snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")
        write_manifest(self.source)
        with self.assertRaises(ValueError):
            stage_release(root, self.source)

    def test_expired_activation_keeps_pointer_but_expired_reads_remain_stale(self):
        self.stage()
        root = self.root / "published"
        activate_release(root, self.version, None, NOW)
        expired = NOW + timedelta(days=3)
        with self.assertRaises(ValueError):
            activate_release(root, self.version, self.version, expired)
        store = read_active_store(root, expired)
        with self.assertRaisesRegex(Exception, "유효 기간"):
            store.recommendations(store.learners["learner-a"], expired)
        self.assertEqual(active_version(root), self.version)

    def test_stale_expected_version_and_traversal_are_rejected(self):
        self.stage()
        root = self.root / "published"
        activate_release(root, self.version, None, NOW)
        with self.assertRaises(ValueError):
            activate_release(root, self.version, None, NOW)
        for version in ["../source", "/absolute", "a/b", "a\\b", ""]:
            with self.subTest(version=version), self.assertRaises(ValueError):
                load_release(root, version, NOW)

    def test_concurrent_first_activation_has_only_one_winner(self):
        self.stage()
        root = self.root / "published"

        def activate():
            try:
                activate_release(root, self.version, None, NOW)
                return True
            except ValueError:
                return False

        with ThreadPoolExecutor(max_workers=2) as executor:
            winners = list(executor.map(lambda _: activate(), range(2)))
        self.assertEqual(winners.count(True), 1)
        self.assertEqual(read_active_store(root, NOW).snapshot.data_version, self.version)

    def test_pending_failure_is_explicit_and_preserves_current(self):
        self.stage()
        root = self.root / "published"
        activate_release(root, self.version, None, NOW)
        request = {"request_id": "request-1", "version": self.version,
                   "expected_current": self.version, "incoming": "missing"}
        (root / "pending.json").write_text(json.dumps(request), encoding="utf-8")
        result = process_pending(root, NOW)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(active_version(root), self.version)
        self.assertEqual(process_pending(root, NOW), result)

    def test_manifest_covers_exact_files_and_actual_bytes(self):
        manifest = json.loads((self.source / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(set(manifest["files"]), {
            "courses.synthetic.json", "learners.synthetic.json", "recommendations.synthetic.json"})
        for name, digest in manifest["files"].items():
            self.assertEqual(digest, hashlib.sha256((self.source / name).read_bytes()).hexdigest())

    def test_interrupted_pending_write_does_not_break_previous_release(self):
        self.stage()
        root = self.root / "published"
        activate_release(root, self.version, None, NOW)
        (root / "pending.json").write_text('{"request_id":', encoding="utf-8")
        self.assertEqual(process_pending(root, NOW)["status"], "failed")
        self.assertEqual(read_active_store(root, NOW).snapshot.data_version, self.version)

    def test_rollback_and_interleaved_readers_observe_complete_versions(self):
        root = self.root / "published"
        self.stage()
        activate_release(root, self.version, None, NOW)
        snapshot_path = self.source / "recommendations.synthetic.json"
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
        snapshot["data_version"] = "second-version"
        snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")
        write_manifest(self.source)
        stage_release(root, self.source)

        def reader():
            for _ in range(5):
                store = read_active_store(root, NOW)
                response = store.recommendations(store.learners["learner-a"], NOW)
                self.assertIn(response.version, {self.version, "second-version"})
                for item in response.items:
                    self.assertIn(response.version, item.reason_source_ref)

        with ThreadPoolExecutor(max_workers=2) as executor:
            future = executor.submit(reader)
            activate_release(root, "second-version", self.version, NOW)
            activate_release(root, self.version, "second-version", NOW)
            future.result()
        self.assertEqual(active_version(root), self.version)

    def test_repeat_activation_preserves_previous_version_for_rollback(self):
        root = self.root / "published"
        self.stage()
        activate_release(root, self.version, None, NOW)
        snapshot_path = self.source / "recommendations.synthetic.json"
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
        snapshot["data_version"] = "next-version"
        snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")
        write_manifest(self.source)
        stage_release(root, self.source)
        activate_release(root, "next-version", self.version, NOW)
        before = (root / "active.json").read_bytes()
        activate_release(root, "next-version", "next-version", NOW)
        self.assertEqual((root / "active.json").read_bytes(), before)

    def test_reused_request_id_is_reported_without_breaking_previous_release(self):
        self.stage()
        root = self.root / "published"
        activate_release(root, self.version, None, NOW)
        request = {"request_id": "reused", "version": self.version,
                   "expected_current": self.version, "incoming": "missing"}
        (root / "pending.json").write_text(json.dumps(request), encoding="utf-8")
        original = process_pending(root, NOW)
        request["incoming"] = "different"
        (root / "pending.json").write_text(json.dumps(request), encoding="utf-8")
        self.assertEqual(process_pending(root, NOW)["status"], "failed")
        self.assertEqual(read_active_store(root, NOW).snapshot.data_version, self.version)
        self.assertEqual(json.loads((root / "requests" / "reused.json").read_text()), original)
