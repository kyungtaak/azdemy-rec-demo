"""Check persisted live Foundry responses against the original synthetic data."""

import argparse
import json
import re
from pathlib import Path

from api.main import DATA_DIR
from api.service import Store


def load_response(directory: Path, scenario: str):
    response = json.loads((directory / f"live-{scenario}.json").read_text(encoding="utf-8"))
    assert response["status"] == "completed", scenario
    assert response["error"] is None, scenario
    text = "\n".join(
        part["text"] for item in response["output"] if item["type"] == "message"
        for part in item["content"] if part["type"] == "output_text")
    results = {}
    for item in response["output"]:
        if item["type"] == "openapi_call_output":
            assert item["status"] == "completed", scenario
            result = json.loads(item["output"])
            results[item["name"]] = json.loads(result["response"])
    return response, text, results


def verify_no_results(result: dict, text: str) -> None:
    assert result["status"] == "NO_RESULTS" and result["items"] == []
    assert any(phrase in text for phrase in ("없", "찾지 못"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--response-dir", type=Path, required=True)
    parser.add_argument("--release-dir", type=Path)
    arguments = parser.parse_args()
    directory = arguments.response_dir
    store = Store(arguments.release_dir or DATA_DIR)

    _, text, results = load_response(directory, "recommendations")
    recommendations = results["education_getMyRecommendations"]
    assert recommendations["mode"] == "personalized"
    expected_ranks = [c.rank for c in store.snapshot.personalized["learner-a"]
                      if not store.courses[c.course_id].is_mandatory
                      and not store.exclusions(store.courses[c.course_id], store.learners["learner-a"],
                                               store.snapshot.generated_at)]
    assert [item["rank"] for item in recommendations["items"]] == expected_ranks
    original = {c.course_id: c for c in store.snapshot.personalized["learner-a"]}
    positions = []
    for item in recommendations["items"]:
        candidate = original[item["course"]["id"]]
        assert item["rank"] == candidate.rank
        assert item["reason"] == candidate.reason
        positions.append(text.index(candidate.reason))
        assert item["reason_source_ref"] in text
        assert item["course"]["source_ref"] in text
    assert positions == sorted(positions), "Answer reordered snapshot recommendations"
    assert all(re.search(rf"\b{rank}\b", text) for rank in expected_ranks)
    assert [item["course"]["id"] for item in recommendations["mandatory_items"]] == ["SYN-SEC-001"]
    assert recommendations["version"] in text and recommendations["generated_at"] in text
    assert recommendations["is_synthetic"] is True and "합성" in text
    if arguments.release_dir:
        assert recommendations["generation"] == "fabric-spark-content-v1"
        assert recommendations["provenance"] == store.snapshot.provenance.model_dump(mode="json")
    print("PASS REC-01/03/04, AGT-04/05: live ranks, verbatim reasons, sources, mandatory separation")

    _, text, results = load_response(directory, "comparison")
    courses = results["education_getCourses"]["items"]
    assert [item["course"]["id"] for item in courses] == ["SYN-DEV-001", "SYN-DEV-002"]
    assert [item["course"]["duration_minutes"] for item in courses] == [240, 360]
    assert [item["can_take"] for item in courses] == [False, True]
    for item in courses:
        original_course = store.courses[item["course"]["id"]]
        assert item["course"] == original_course.model_dump(mode="json")
        assert original_course.source_ref in text
        assert str(original_course.duration_minutes) in text
    assert "가격" in text and "확인" in text
    print("PASS AGT-01/04: live comparison facts equal catalog; missing price not fabricated")

    _, text, results = load_response(directory, "search")
    courses = results["education_searchCourses"]["items"]
    assert [item["course"]["id"] for item in courses] == ["SYN-DEV-003", "SYN-DEV-005"]
    assert all(item["course"]["language"] == "en" for item in courses)
    assert courses[0]["course"]["subtitle_languages"] == ["ko", "en"]
    assert courses[1]["course"]["subtitle_languages"] == ["en"]
    assert "COURSE_CLOSED" in courses[1]["exclusion_reasons"]
    assert all(item["course"]["source_ref"] in text for item in courses)
    print("PASS AGT-01/04: live category/language search, subtitles, closed-course eligibility")

    response, text, results = load_response(directory, "denial")
    assert not results
    assert not any(item["type"] == "openapi_call" for item in response["output"])
    assert any(phrase in text for phrase in ("조회할 수 없", "제공할 수 없", "공개할 수 없"))
    print("PASS AGT-03: another learner request refused without a tool call")

    _, text, results = load_response(directory, "noresult")
    result = results["education_searchCourses"]
    verify_no_results(result, text)
    print("PASS AGT-06: explicit NO_RESULTS search result, no fabricated courses")


if __name__ == "__main__":
    main()
