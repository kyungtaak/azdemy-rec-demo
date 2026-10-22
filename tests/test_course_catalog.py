import json
import unittest
from collections import Counter
from datetime import datetime
from pathlib import Path


CATALOG_PATH = Path(__file__).resolve().parents[1] / "data" / "courses.synthetic.json"
CATEGORY_PREFIXES = {
    "development": "DEV",
    "data_ai": "DAT",
    "cloud": "CLD",
    "security": "SEC",
    "productivity": "PRD",
    "leadership": "LDR",
}


class CourseCatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
        cls.courses = cls.catalog["courses"]
        cls.by_id = {course["id"]: course for course in cls.courses}

    def timestamp(self, value):
        parsed = datetime.fromisoformat(value)
        self.assertIsNotNone(parsed.utcoffset(), value)
        return parsed

    def test_exactly_five_courses_in_each_of_six_categories(self):
        self.assertEqual(len(self.courses), 30)
        self.assertEqual(Counter(c["category_id"] for c in self.courses),
                         Counter({category: 5 for category in CATEGORY_PREFIXES}))
        categories = self.catalog["categories"]
        self.assertEqual(len(categories), 6)
        self.assertEqual({c["id"] for c in categories}, set(CATEGORY_PREFIXES))

    def test_identifiers_titles_and_internal_paths_are_unique(self):
        for field in ("id", "title", "detail_path", "source_ref"):
            with self.subTest(field=field):
                self.assertEqual(len({c[field] for c in self.courses}), 30)
        for course in self.courses:
            with self.subTest(course=course["id"]):
                prefix = CATEGORY_PREFIXES[course["category_id"]]
                self.assertRegex(course["id"], rf"^SYN-{prefix}-00[1-5]$")
                self.assertEqual(course["detail_path"], f"/demo/courses/{course['id']}")
                self.assertEqual(course["source_ref"],
                                 f"synthetic:{self.catalog['data_version']}:{course['id']}")

    def test_every_course_is_explicitly_original_synthetic_data(self):
        self.assertIs(self.catalog["is_synthetic"], True)
        self.assertIn("실제 수강 신청은 불가능", self.catalog["notice"])
        self.assertEqual(self.catalog["provenance"]["kind"], "original_synthetic")
        self.assertIs(self.catalog["provenance"]["external_course_content_used"], False)
        created = self.timestamp(self.catalog["created_at"])
        self.assertLessEqual(created, self.timestamp(self.catalog["scenario_reference_at"]))
        for course in self.courses:
            self.assertIs(course["is_synthetic"], True)
            self.assertEqual(course["data_version"], self.catalog["data_version"])

    def test_complete_course_shape_and_field_types(self):
        expected = {
            "id", "title", "category_id", "skill_tags", "level", "duration_minutes",
            "language", "subtitle_languages", "summary", "learning_objectives",
            "target_roles", "prerequisite_knowledge", "curriculum", "has_hands_on",
            "eligible_roles", "prerequisite_course_ids", "enrollment", "status",
            "is_mandatory", "detail_path", "source_ref", "data_version", "is_synthetic",
        }
        nonempty_lists = (
            "skill_tags", "learning_objectives", "target_roles",
            "prerequisite_knowledge", "curriculum", "eligible_roles",
        )
        for course in self.courses:
            with self.subTest(course=course["id"]):
                self.assertEqual(set(course), expected)
                self.assertIn(course["level"], {"beginner", "intermediate", "advanced"})
                self.assertIs(type(course["duration_minutes"]), int)
                self.assertGreater(course["duration_minutes"], 0)
                for field in ("is_synthetic", "is_mandatory", "has_hands_on"):
                    self.assertIs(type(course[field]), bool)
                for field in (*nonempty_lists, "subtitle_languages", "prerequisite_course_ids"):
                    self.assertIsInstance(course[field], list)
                    self.assertEqual(len(course[field]), len(set(course[field])))
                    self.assertTrue(all(isinstance(s, str) and s.strip() for s in course[field]))
                for field in nonempty_lists:
                    self.assertTrue(course[field], field)
                for field in ("title", "summary"):
                    self.assertRegex(course[field], "[가-힣]")
                self.assertGreaterEqual(len(course["learning_objectives"]), 3)
                self.assertGreaterEqual(len(course["curriculum"]), 3)

    def test_known_roles_and_distinct_target_vs_eligibility(self):
        roles = self.catalog["roles"]
        self.assertEqual(len(roles), 6)
        role_ids = {role["id"] for role in roles}
        self.assertEqual(len(role_ids), 6)
        for course in self.courses:
            self.assertLessEqual(set(course["eligible_roles"]), role_ids)
            self.assertLessEqual(set(course["target_roles"]), set(course["eligible_roles"]))
        self.assertNotEqual(self.by_id["SYN-DEV-001"]["target_roles"],
                            self.by_id["SYN-DEV-001"]["eligible_roles"])
        self.assertNotIn("software_engineer", self.by_id["SYN-LDR-002"]["eligible_roles"])

    def test_prerequisites_resolve_without_self_references_or_cycles(self):
        def visit(course_id, path):
            self.assertNotIn(course_id, path, f"Prerequisite cycle: {path} -> {course_id}")
            for prerequisite in self.by_id[course_id]["prerequisite_course_ids"]:
                self.assertIn(prerequisite, self.by_id)
                visit(prerequisite, path | {course_id})

        for course in self.courses:
            visit(course["id"], set())
        self.assertEqual(self.by_id["SYN-SEC-005"]["prerequisite_course_ids"],
                         ["SYN-SEC-002", "SYN-DAT-004"])

    def test_language_is_not_inferred_from_korean_display_text(self):
        self.assertEqual(Counter(c["language"] for c in self.courses), {"ko": 24, "en": 6})
        for course in self.courses:
            self.assertLessEqual(set(course["subtitle_languages"]), {"ko", "en"})
        english_with_korean = self.by_id["SYN-DEV-003"]
        self.assertEqual(english_with_korean["language"], "en")
        self.assertIn("ko", english_with_korean["subtitle_languages"])
        self.assertNotIn("ko", self.by_id["SYN-DEV-005"]["subtitle_languages"])
        self.assertEqual(self.by_id["SYN-CLD-004"]["language"], "ko")
        self.assertEqual(self.by_id["SYN-CLD-004"]["subtitle_languages"], [])

    def test_enrollment_dates_and_status_at_fixed_scenario_time(self):
        reference = self.timestamp(self.catalog["scenario_reference_at"])
        self.assertEqual(Counter(c["status"] for c in self.courses),
                         {"open": 27, "closed": 1, "cancelled": 1, "upcoming": 1})
        for course in self.courses:
            with self.subTest(course=course["id"]):
                self.assertEqual(set(course["enrollment"]), {"opens_at", "closes_at"})
                start = self.timestamp(course["enrollment"]["opens_at"])
                end = self.timestamp(course["enrollment"]["closes_at"])
                self.assertLess(start, end)
                if course["status"] == "open":
                    self.assertLessEqual(start, reference)
                    self.assertLessEqual(reference, end)
                elif course["status"] == "closed":
                    self.assertLess(end, reference)
                elif course["status"] == "upcoming":
                    self.assertLess(reference, start)
        cancelled = self.by_id["SYN-CLD-005"]
        self.assertEqual(cancelled["status"], "cancelled")
        self.assertLessEqual(self.timestamp(cancelled["enrollment"]["opens_at"]), reference)
        self.assertLess(reference, self.timestamp(cancelled["enrollment"]["closes_at"]))

    def test_mandatory_and_comparison_fixtures(self):
        self.assertEqual([c["id"] for c in self.courses if c["is_mandatory"]],
                         ["SYN-SEC-001"])
        self.assertEqual(self.by_id["SYN-SEC-001"]["eligible_roles"],
                         [r["id"] for r in self.catalog["roles"]])
        basic, next_course = self.by_id["SYN-DEV-001"], self.by_id["SYN-DEV-002"]
        self.assertNotEqual(basic["level"], next_course["level"])
        self.assertNotEqual(basic["duration_minutes"], next_course["duration_minutes"])
        self.assertNotEqual(basic["learning_objectives"], next_course["learning_objectives"])
        self.assertTrue(any(c["has_hands_on"] for c in self.courses))
        self.assertTrue(any(not c["has_hands_on"] for c in self.courses))

    def test_no_external_links_employee_data_or_recommendation_authority(self):
        serialized = json.dumps(self.courses, ensure_ascii=False)
        self.assertNotRegex(serialized, r"https?://|www\.|@")
        forbidden = {"employee_id", "rank", "score", "recommendation_reason",
                     "price", "rating", "student_count", "instructor", "provider_course_id"}
        for course in self.courses:
            self.assertTrue(forbidden.isdisjoint(course))
        self.assertTrue(all(c["source_ref"].startswith("synthetic:") for c in self.courses))


if __name__ == "__main__":
    unittest.main()
