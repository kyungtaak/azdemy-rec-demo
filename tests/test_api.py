import json
import os
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from api.auth import AuthSettings, get_auth_settings
from api.main import DATA_DIR, create_app, get_store, utc_now
from api.service import Store
from agent.build_definition import definition


NOW = datetime(2026, 10, 20, 12, tzinfo=timezone.utc)
TENANT, AUDIENCE, PRINCIPAL = (str(uuid4()) for _ in range(3))
SETTINGS = AuthSettings(TENANT, AUDIENCE, {PRINCIPAL: "learner-a"})


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    def setUp(self):
        self.store = Store(DATA_DIR)
        self.app = create_app(self.store)
        self.app.dependency_overrides[get_auth_settings] = lambda: SETTINGS
        self.app.dependency_overrides[utc_now] = lambda: NOW
        self.client = TestClient(self.app, raise_server_exceptions=False)
        self.keys = patch("api.auth.signing_keys")
        mocked = self.keys.start()
        mocked.return_value.get_signing_key_from_jwt.return_value = SimpleNamespace(
            key=self.key.public_key())
        self.addCleanup(self.keys.stop)
        self.addCleanup(self.client.close)

    def token(self, **changes):
        actual_now = datetime.now(timezone.utc)
        claims = {
            "iss": f"https://login.microsoftonline.com/{TENANT}/v2.0",
            "aud": AUDIENCE, "tid": TENANT, "oid": PRINCIPAL,
            "iat": actual_now, "exp": actual_now + timedelta(minutes=5),
            "roles": ["Learner.Read"],
        }
        claims.update(changes)
        return jwt.encode(claims, self.key, algorithm="RS256", headers={"kid": "test"})

    def get(self, path, token=None):
        return self.client.get(path, headers={"Authorization": f"Bearer {token or self.token()}"})

    def test_rec_01_03_04_preserves_snapshot_rank_and_reason(self):
        response = self.get("/recommendations/me")
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertEqual(data["mode"], "personalized")
        self.assertTrue(data["is_synthetic"])
        self.assertEqual(data["version"], "2026-10-20.1")
        self.assertEqual(data["generated_at"], "2026-10-20T12:00:00Z")
        self.assertEqual([item["rank"] for item in data["items"]], [1, 7, 8])
        candidates = {c.course_id: c for c in self.store.snapshot.personalized["learner-a"]}
        for item in data["items"]:
            candidate = candidates[item["course"]["id"]]
            self.assertEqual(item["reason"], candidate.reason)
            self.assertEqual(item["rank"], candidate.rank)
            self.assertTrue(item["reason_source_ref"].startswith("recommendation:"))
            self.assertFalse(item["course"]["is_mandatory"])
        self.assertEqual([i["course"]["id"] for i in data["mandatory_items"]], ["SYN-SEC-001"])
        self.assertEqual(response.headers["cache-control"], "no-store")

    def test_rec_04_each_exclusion_rule(self):
        learner = self.store.learners["learner-a"]
        expected = {
            "SYN-DEV-001": "COMPLETED", "SYN-DEV-005": "ENROLLMENT_ENDED",
            "SYN-CLD-005": "COURSE_CANCELLED", "SYN-LDR-002": "INELIGIBLE_ROLE",
            "SYN-SEC-005": "PREREQUISITES_NOT_MET", "SYN-LDR-005": "ENROLLMENT_NOT_STARTED",
        }
        for course_id, reason in expected.items():
            with self.subTest(course=course_id):
                self.assertIn(reason, self.store.exclusions(self.store.courses[course_id], learner, NOW))

    def test_rec_04_all_prerequisites_and_inclusive_dates(self):
        learner = self.store.learners["learner-a"].model_copy(
            update={"role": "security_engineer", "completed_course_ids": ["SYN-SEC-002"]})
        course = self.store.courses["SYN-SEC-005"]
        self.assertIn("PREREQUISITES_NOT_MET", self.store.exclusions(course, learner, NOW))
        learner = learner.model_copy(update={"completed_course_ids": ["SYN-SEC-002", "SYN-DAT-004"]})
        for date in [course.enrollment.opens_at, course.enrollment.closes_at]:
            self.assertEqual(self.store.exclusions(course, learner, date), [])
        self.assertIn("ENROLLMENT_ENDED", self.store.exclusions(
            course, learner, course.enrollment.closes_at + timedelta(microseconds=1)))

    def test_rec_05_cold_start_is_policy_not_error_fallback(self):
        self.app.dependency_overrides[get_auth_settings] = lambda: AuthSettings(
            TENANT, AUDIENCE, {PRINCIPAL: "learner-b"})
        response = self.get("/recommendations/me")
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertEqual(data["mode"], "cold_start")
        self.assertEqual([i["course"]["id"] for i in data["items"]],
                         ["SYN-DEV-001", "SYN-DEV-004", "SYN-PRD-003"])

    def test_agt_06_missing_personalized_snapshot_is_503_not_cold_start(self):
        self.store.snapshot = self.store.snapshot.model_copy(update={"personalized": {}})
        response = self.get("/recommendations/me")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"]["code"], "SYSTEM_ERROR")

    def test_rec_02_employee_or_scenario_query_is_rejected(self):
        for suffix in ["employee_id=learner-b", "scenario=cold_start", "user_id=learner-b"]:
            with self.subTest(query=suffix):
                self.assertEqual(self.get("/recommendations/me?" + suffix).status_code, 422)

    def test_sec_missing_invalid_or_expired_tokens(self):
        self.assertEqual(self.client.get("/courses?ids=SYN-DEV-001").status_code, 401)
        for token in ["not-a-token", self.token(exp=0), self.token(aud=str(uuid4())),
                      self.token(iss="https://attacker.invalid"), self.token(tid=str(uuid4()))]:
            with self.subTest(token_kind=token[:12]):
                response = self.get("/recommendations/me", token)
                self.assertEqual(response.status_code, 401)
                self.assertEqual(response.headers["www-authenticate"], "Bearer")

    def test_sec_wrong_signature_and_algorithm(self):
        foreign_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        claims = jwt.decode(self.token(), options={"verify_signature": False})
        for token in [jwt.encode(claims, foreign_key, algorithm="RS256"),
                      jwt.encode(claims, "not-a-trusted-key", algorithm="HS256")]:
            self.assertEqual(self.get("/recommendations/me", token).status_code, 401)

    def test_sec_required_claims_and_identity_shape(self):
        claims = jwt.decode(self.token(), options={"verify_signature": False})
        for name in ["exp", "iat", "iss", "aud", "tid", "oid"]:
            with self.subTest(missing=name):
                missing = {key: value for key, value in claims.items() if key != name}
                token = jwt.encode(missing, self.key, algorithm="RS256")
                self.assertEqual(self.get("/recommendations/me", token).status_code, 401)
        for oid in [[], {}, None, ""]:
            self.assertEqual(self.get("/recommendations/me", self.token(oid=oid)).status_code, 401)
        self.assertEqual(self.get("/recommendations/me", self.token(
            nbf=datetime.now(timezone.utc) + timedelta(minutes=5))).status_code, 401)

    def test_sec_unmapped_or_missing_permissions_is_403(self):
        for token in [self.token(oid=str(uuid4())), self.token(roles=[]),
                      self.token(roles="Learner.Read"), self.token(roles=[], scp="unrelated")]:
            self.assertEqual(self.get("/recommendations/me", token).status_code, 403)
        self.assertEqual(self.get("/recommendations/me", self.token(
            roles=[], scp="access_as_user")).status_code, 200)

    def test_sec_signing_key_failure_is_explicit_503(self):
        with patch("api.auth.signing_keys") as keys:
            keys.return_value.get_signing_key_from_jwt.side_effect = jwt.PyJWKClientConnectionError(
                "simulated network error")
            response = self.get("/recommendations/me")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"]["code"], "SYSTEM_ERROR")

    def test_pip_05_expired_or_future_snapshot_is_409(self):
        for date in [self.store.snapshot.valid_until + timedelta(seconds=1),
                     self.store.snapshot.generated_at - timedelta(seconds=1)]:
            self.app.dependency_overrides[utc_now] = lambda date=date: date
            response = self.get("/recommendations/me")
            self.assertEqual(response.status_code, 409)
            self.assertEqual(response.json()["error"]["code"], "STALE_DATA")
        for date in [self.store.snapshot.generated_at, self.store.snapshot.valid_until]:
            self.app.dependency_overrides[utc_now] = lambda date=date: date
            self.assertEqual(self.get("/recommendations/me").status_code, 200)

    def test_agt_06_empty_recommendations_is_not_failure_fallback(self):
        self.store.learners["learner-a"] = self.store.learners["learner-a"].model_copy(
            update={"completed_course_ids": list(self.store.courses)})
        response = self.get("/recommendations/me")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"]["code"], "NO_RESULTS")

    def test_agt_01_04_course_comparison_has_original_facts_and_sources(self):
        response = self.get("/courses?ids=SYN-DEV-001,SYN-DEV-002")
        self.assertEqual(response.status_code, 200, response.text)
        first, second = response.json()["items"]
        self.assertEqual(first["course"]["duration_minutes"], 240)
        self.assertEqual(second["course"]["duration_minutes"], 360)
        self.assertEqual(first["course"]["level"], "beginner")
        self.assertEqual(second["course"]["prerequisite_course_ids"], ["SYN-DEV-001"])
        self.assertEqual(first["course"]["source_ref"], "synthetic:2026-10-20.1:SYN-DEV-001")
        self.assertIn("COMPLETED", first["exclusion_reasons"])
        self.assertTrue(second["can_take"])

    def test_course_search_filters_language_and_limits(self):
        response = self.get("/courses/search?category=development&language=en&limit=1")
        self.assertEqual(response.status_code, 200, response.text)
        items = response.json()["items"]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["course"]["language"], "en")
        self.assertEqual(items[0]["course"]["subtitle_languages"], ["ko", "en"])
        self.assertEqual(self.get("/courses/search?query=Python").status_code, 200)

    def test_agt_06_no_result_and_invalid_parameters_are_distinct(self):
        response = self.get("/courses/search?query=not-a-course")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "NO_RESULTS")
        self.assertEqual(response.json()["items"], [])
        for path in ["/courses?ids=UNKNOWN", "/demo/courses/UNKNOWN"]:
            response = self.get(path)
            self.assertEqual(response.status_code, 404)
            self.assertEqual(response.json()["error"]["code"], "NO_RESULTS")
        for path in [
            "/courses?ids=", "/courses?ids=SYN-DEV-001,SYN-DEV-001",
            "/courses?ids=SYN-DEV-001,", "/courses?ids=A,B,C,D,E,F",
            "/courses?ids=SYN-DEV-001&ids=SYN-DEV-002",
            "/courses/search?limit=31", "/courses/search?language=fr",
            "/courses/search?category=unknown", "/courses/search?employee_id=learner-b",
        ]:
            with self.subTest(path=path):
                response = self.get(path)
                self.assertEqual(response.status_code, 422)
                self.assertEqual(response.json()["error"]["code"], "INVALID_REQUEST")

    def test_agt_06_unexpected_fault_logs_and_returns_no_internal_details(self):
        with patch.object(self.store, "search", side_effect=RuntimeError("private-internal-detail")):
            with self.assertLogs("azdemy.api", level="ERROR"):
                response = self.get("/courses/search")
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json()["error"]["code"], "SYSTEM_ERROR")
        self.assertNotIn("private-internal-detail", response.text)
        self.assertTrue(response.headers["x-request-id"])

    def test_agt_06_missing_store_does_not_return_success(self):
        self.app.state.store = None
        response = self.get("/courses/search")
        self.assertEqual(response.status_code, 503)

    def test_agt_tools_read_only_three_operations_no_employee_parameter(self):
        schema = self.app.openapi()
        self.assertEqual(schema["info"]["title"], "Azdemy Read-only Education API")
        operations = [
            operation for path in schema["paths"].values()
            for method, operation in path.items() if method == "get"]
        self.assertEqual({o["operationId"] for o in operations},
                         {"getMyRecommendations", "searchCourses", "getCourses"})
        self.assertEqual(len(operations), 3)
        for operation in operations:
            self.assertTrue(operation["security"])
            self.assertTrue({"401", "403", "404", "409", "422", "500", "503"}
                            <= operation["responses"].keys())
            self.assertFalse(any("employee" in p["name"] or "learner" in p["name"]
                                 for p in operation.get("parameters", [])))
        self.assertEqual(self.client.post("/recommendations/me").status_code, 405)
        self.assertEqual(self.get("/demo/courses/SYN-DEV-001").status_code, 200)

    def test_agent_definition_is_prompt_with_keyless_read_only_tools(self):
        api_url = "https://azdemy-test-api.azurewebsites.net"
        agent = definition(AUDIENCE, api_url)
        self.assertEqual(agent["kind"], "prompt")
        self.assertEqual(agent["model"], "gpt-5.6-terra")
        self.assertNotIn("harness", agent)
        self.assertEqual(len(agent["tools"]), 1)
        tool = agent["tools"][0]["openapi"]
        self.assertEqual(tool["auth"], {
            "type": "managed_identity", "security_scheme": {"audience": f"api://{AUDIENCE}"}})
        self.assertEqual(len(tool["spec"]["paths"]), 3)
        self.assertEqual(tool["spec"]["servers"], [{"url": api_url}])

    def test_agent_definition_rejects_invalid_deployment_urls(self):
        for url in ("", "http://example.org", "/courses", "https://user@example.org",
                    "https://example.org?query=1", "https://example.org#fragment",
                    "https://example.org/courses"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                definition(AUDIENCE, url)

    def test_local_openapi_does_not_point_to_a_deleted_deployment(self):
        self.assertNotIn("servers", create_app().openapi())

    def test_auth_settings_read_azdemy_environment(self):
        with patch.dict(os.environ, {
            "AZDEMY_TENANT_ID": TENANT,
            "AZDEMY_API_CLIENT_ID": AUDIENCE,
            "AZDEMY_PRINCIPAL_LEARNERS": json.dumps({PRINCIPAL: "learner-a"}),
        }, clear=True):
            self.assertEqual(AuthSettings.from_environment(), SETTINGS)

    def test_publication_root_reads_azdemy_environment(self):
        with TemporaryDirectory() as directory, patch.dict(
            os.environ, {"AZDEMY_PUBLICATION_ROOT": directory}, clear=True
        ), patch("api.main.get_auth_settings", return_value=SETTINGS), patch(
            "api.main.process_pending"
        ) as pending, patch("api.main.read_active_store", return_value=self.store):
            app = create_app(self.store)
            with TestClient(app):
                self.assertEqual(app.state.publication_root, Path(directory))
            pending.assert_called_once()


class StoreValidationTests(unittest.TestCase):
    def test_dat_02_bad_rank_reference_version_or_mandatory_reason_fails_load(self):
        for mutation in ["rank", "reference", "version", "mandatory"]:
            with self.subTest(mutation=mutation), TemporaryDirectory() as directory:
                target = Path(directory)
                for source in DATA_DIR.glob("*.synthetic.json"):
                    (target / source.name).write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
                path = target / "recommendations.synthetic.json"
                data = json.loads(path.read_text(encoding="utf-8"))
                if mutation == "rank":
                    data["personalized"]["learner-a"][1]["rank"] = 1
                elif mutation == "reference":
                    data["personalized"]["learner-a"][0]["course_id"] = "UNKNOWN"
                elif mutation == "version":
                    data["catalog_version"] = "unknown"
                else:
                    data["mandatory_reasons"] = {}
                path.write_text(json.dumps(data), encoding="utf-8")
                with self.assertRaises(ValueError):
                    Store(target)


if __name__ == "__main__":
    unittest.main()
