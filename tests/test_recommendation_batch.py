import json
import hashlib
import unittest
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from api.main import DATA_DIR
from api.service import Store
from azdemy_recommendations.recommender import build_evidence, build_snapshot, render_reason, validate_policy
from azdemy_recommendations.spark_job import delta_table_path
from tests.test_api import NOW


class BatchTests(unittest.TestCase):
    def test_spark_delta_path_uses_only_the_verified_default_lakehouse_binding(self):
        config = {"workspace_id": "a9e11b86-dd2e-44ef-9454-461d89793045",
                  "lakehouse_id": "d1a58be0-d465-4ceb-b3d7-f4ae2df84d65"}
        context = {"currentWorkspaceId": config["workspace_id"],
                   "defaultLakehouseId": config["lakehouse_id"]}
        self.assertEqual(delta_table_path(config, context), "Tables/genius_recommendations")
        context["defaultLakehouseId"] = "00000000-0000-0000-0000-000000000000"
        with self.assertRaises(ValueError):
            delta_table_path(config, context)

    def setUp(self):
        self.catalog = json.loads((DATA_DIR / "courses.synthetic.json").read_text(encoding="utf-8"))
        self.learners = json.loads((DATA_DIR / "learners.synthetic.json").read_text(encoding="utf-8"))
        self.policy = json.loads(
            (DATA_DIR / "recommendation-policy.synthetic.json").read_text(encoding="utf-8"))
        self.store = Store(DATA_DIR)
        self.provenance = {
            "workspace_id": "workspace", "lakehouse_id": "lakehouse", "job_id": "job",
            "mlflow_run_id": "run", "model_uri": "runs:/run/model", "model_version": "run",
            "method": "spark_ml_tfidf_cosine", "code_version": "code",
            "policy_version": self.policy["data_version"], "input_versions": {
                "catalog": self.catalog["data_version"], "learners": self.learners["data_version"]},
            "input_sha256": {
                "catalog": hashlib.sha256((DATA_DIR / "courses.synthetic.json").read_bytes()).hexdigest(),
                "learners": hashlib.sha256((DATA_DIR / "learners.synthetic.json").read_bytes()).hexdigest()},
            "as_of": NOW.isoformat(), "validated_at": NOW.isoformat(),
        }

    def generate(self, scores=None):
        if scores is None:
            scores = {"learner-a": {c.id: 0.5 for c in self.store.courses.values()}}
        return build_snapshot(self.catalog, self.learners, self.policy, scores,
                              self.provenance, "fabric-test", NOW, 48, 3)

    def test_deterministic_ties_eligibility_and_mandatory_separation(self):
        snapshot = self.generate()
        items = snapshot["personalized"]["learner-a"]
        self.assertEqual(len(items), 3)
        self.assertEqual([i["course_id"] for i in items], sorted(i["course_id"] for i in items))
        for item in items:
            course = self.store.courses[item["course_id"]]
            self.assertFalse(course.is_mandatory)
            self.assertEqual(self.store.exclusions(course, self.store.learners["learner-a"], NOW), [])
            self.assertEqual(item["reason"], render_reason(item["evidence"]))
        self.assertEqual(set(snapshot["mandatory_reasons"]), {"SYN-SEC-001"})

    def test_cold_start_is_explicit_role_policy_not_error_fallback(self):
        snapshot = self.generate()
        self.assertTrue(snapshot["cold_start_by_role"]["software_engineer"])
        with self.assertRaisesRegex(ValueError, "Missing model scores"):
            self.generate({})

    def test_reasons_use_only_actual_matching_tags_and_completed_courses(self):
        evidence = build_evidence(
            self.catalog, self.learners["learners"][0], "SYN-DEV-002", self.policy)
        self.assertEqual(evidence["matched_tags"], ["python"])
        self.assertEqual(evidence["completed_course_ids"], ["SYN-DEV-001"])
        self.assertIn("python", render_reason(evidence))
        self.assertNotIn("부족", render_reason(evidence))

    def test_invalid_scores_policy_and_ttl_fail(self):
        for score in [float("nan"), float("inf"), -0.1, 1.1]:
            scores = {c.id: 0.5 for c in self.store.courses.values()}
            scores["SYN-DEV-002"] = score
            with self.subTest(score=score), self.assertRaises(ValueError):
                self.generate({"learner-a": scores})
        policy = dict(self.policy, cold_start_by_role={"software_engineer": ["UNKNOWN"]})
        with self.assertRaises(ValueError):
            validate_policy(self.catalog, policy)
        for ttl in [0, 49]:
            with self.subTest(ttl=ttl), self.assertRaises(ValueError):
                build_snapshot(self.catalog, self.learners, self.policy, {}, self.provenance,
                               "fabric-test", NOW, ttl, 3)

    def test_generation_times_and_real_provenance_are_retained(self):
        snapshot = self.generate()
        self.assertEqual(snapshot["generation"], "fabric-spark-content-v1")
        self.assertEqual(snapshot["provenance"], self.provenance)
        self.assertEqual(snapshot["generated_at"], NOW.isoformat())
        self.assertEqual(snapshot["valid_until"], (NOW + timedelta(hours=48)).isoformat())

    def test_api_loads_real_snapshot_and_rejects_fabricated_reason_or_input_hash(self):
        for mutation in ["none", "reason", "tags", "hash", "future_validation"]:
            with self.subTest(mutation=mutation), TemporaryDirectory() as directory:
                target = Path(directory)
                for name in ("courses.synthetic.json", "learners.synthetic.json"):
                    (target / name).write_bytes((DATA_DIR / name).read_bytes())
                snapshot = self.generate()
                candidate = snapshot["personalized"]["learner-a"][0]
                if mutation == "reason":
                    candidate["reason"] = "Invented preference"
                elif mutation == "tags":
                    candidate["evidence"]["matched_tags"] = ["invented-skill"]
                elif mutation == "hash":
                    snapshot["provenance"]["input_sha256"]["catalog"] = "0" * 64
                elif mutation == "future_validation":
                    snapshot["provenance"]["validated_at"] = (NOW - timedelta(seconds=1)).isoformat()
                (target / "recommendations.synthetic.json").write_text(
                    json.dumps(snapshot), encoding="utf-8")
                if mutation != "none":
                    with self.assertRaises(ValueError):
                        Store(target)
                else:
                    store = Store(target)
                    response = store.recommendations(store.learners["learner-a"], NOW)
                    self.assertEqual(response.provenance.model_uri, "runs:/run/model")
                    self.assertTrue(all(item.evidence is not None for item in response.items))
