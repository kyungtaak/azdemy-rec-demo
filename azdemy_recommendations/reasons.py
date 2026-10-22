def build_evidence(catalog: dict, learner: dict, course_id: str, policy: dict,
                   cold_start: bool = False) -> dict:
    courses = {c["id"]: c for c in catalog["courses"]}
    course = courses[course_id]
    completed = [] if cold_start else [
        courses[c] for c in sorted(learner["completed_course_ids"])
        if set(courses[c]["skill_tags"]) & set(course["skill_tags"])
    ]
    return {
        "rule": "cold_start_role_policy" if cold_start else "content_similarity",
        "role": learner["role"],
        "matched_tags": sorted(set(course["skill_tags"]) & {
            tag for c in completed for tag in c["skill_tags"]}),
        "completed_course_ids": [c["id"] for c in completed],
        "source_refs": [course["source_ref"], *[c["source_ref"] for c in completed]],
        "policy_version": policy["data_version"],
    }


def render_reason(evidence: dict) -> str:
    role = evidence["role"]
    if evidence["rule"] == "cold_start_role_policy":
        return (f"학습 이력이 부족한 합성 {role} 사용자를 위한 직무별 기초 정책 추천입니다. "
                "개인화 모델의 추론 결과가 아닙니다.")
    if evidence["matched_tags"]:
        tags = ", ".join(evidence["matched_tags"])
        ids = ", ".join(evidence["completed_course_ids"])
        return (f"수료한 합성 과정 {ids}과 이 과정의 공통 역량 태그는 {tags}입니다. "
                "직무와 과정 콘텐츠의 유사도를 계산한 모델 추천입니다.")
    return (f"합성 {role} 사용자가 수강 가능한 과정 중 "
            "직무와 과정 콘텐츠의 유사도를 계산한 모델 추천입니다.")
