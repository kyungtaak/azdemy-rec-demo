import unittest

from agent.verify_responses import verify_no_results


class AgentVerificationTests(unittest.TestCase):
    def test_explicit_empty_search_accepts_equivalent_korean_phrasing(self):
        for text in ("해당 과정이 없습니다.", "해당 교육 과정은 찾지 못했습니다."):
            with self.subTest(text=text):
                verify_no_results({"status": "NO_RESULTS", "items": []}, text)

    def test_empty_search_requires_no_results_status_and_no_items(self):
        for result in (
            {"status": "OK", "items": []},
            {"status": "SYSTEM_ERROR", "items": []},
            {"status": "NO_RESULTS", "items": [{"id": "invented-course"}]},
        ):
            with self.subTest(result=result), self.assertRaises(AssertionError):
                verify_no_results(result, "해당 과정이 없습니다.")

    def test_empty_search_requires_explicit_no_result_message(self):
        with self.assertRaises(AssertionError):
            verify_no_results({"status": "NO_RESULTS", "items": []}, "교육 검색을 처리했습니다.")


if __name__ == "__main__":
    unittest.main()
