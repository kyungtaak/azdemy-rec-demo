import math
from datetime import datetime, timedelta

from .eligibility import exclusion_reasons
from .reasons import build_evidence, render_reason


def validate_policy(catalog: dict, policy: dict) -> None:
    courses = {c["id"]: c for c in catalog["courses"]}
    roles = {r["id"] for r in catalog["roles"]}
    if policy["is_synthetic"] is not True or policy["catalog_version"] != catalog["data_version"]:
        raise ValueError("Policy must reference the synthetic catalog")
    for role, ids in policy["cold_start_by_role"].items():
        if (role not in roles or len(ids) != len(set(ids))
                or not set(ids) <= courses.keys()
                or any(courses[c]["is_mandatory"] for c in ids)):
            raise ValueError("Invalid cold-start policy references")
    if set(policy["mandatory_reasons"]) != {c["id"] for c in courses.values() if c["is_mandatory"]}:
        raise ValueError("Mandatory policy must cover exactly the mandatory courses")


def eligible(course: dict, learner: dict, now: datetime) -> bool:
    return not exclusion_reasons(
        course_id=course["id"], eligible_roles=course["eligible_roles"],
        prerequisite_course_ids=course["prerequisite_course_ids"], status=course["status"],
        opens_at=datetime.fromisoformat(course["enrollment"]["opens_at"]),
        closes_at=datetime.fromisoformat(course["enrollment"]["closes_at"]),
        learner_role=learner["role"], completed_course_ids=learner["completed_course_ids"],
        now=now)


def build_snapshot(catalog: dict, learners: dict, policy: dict, scores: dict,
                   provenance: dict, version: str, generated_at: datetime,
                   ttl_hours: int, top_k: int) -> dict:
    if not 1 <= ttl_hours <= 48 or not 1 <= top_k <= 3 or generated_at.utcoffset() is None:
        raise ValueError("Invalid batch TTL, K or generation time")
    validate_policy(catalog, policy)
    courses = {c["id"]: c for c in catalog["courses"]}
    personalized = {}
    for learner in learners["learners"]:
        if learner["history_state"] != "sufficient":
            continue
        if learner["id"] not in scores:
            raise ValueError(f"Missing model scores: {learner['id']}")
        learner_scores = scores[learner["id"]]
        if set(learner_scores) != set(courses) or any(
            c not in courses or not math.isfinite(s) or not 0 <= s <= 1
            for c, s in learner_scores.items()
        ):
            raise ValueError("Invalid model scores")
        selected = [
            c for c in sorted(learner_scores, key=lambda c: (-learner_scores[c], c))
            if not courses[c]["is_mandatory"] and eligible(courses[c], learner, generated_at)
        ][:top_k]
        personalized[learner["id"]] = []
        for rank, course_id in enumerate(selected, 1):
            evidence = build_evidence(catalog, learner, course_id, policy)
            personalized[learner["id"]].append({
                "course_id": course_id, "rank": rank, "reason": render_reason(evidence),
                "evidence": evidence, "score": learner_scores[course_id],
            })
    cold_start = {}
    for role, ids in policy["cold_start_by_role"].items():
        learner = {"role": role, "completed_course_ids": []}
        cold_start[role] = []
        for course_id in ids:
            if not eligible(courses[course_id], learner, generated_at):
                continue
            evidence = build_evidence(catalog, learner, course_id, policy, cold_start=True)
            cold_start[role].append({
                "course_id": course_id, "rank": len(cold_start[role]) + 1,
                "reason": render_reason(evidence), "evidence": evidence,
            })
            if len(cold_start[role]) == top_k:
                break
    return {
        "data_version": version, "catalog_version": catalog["data_version"],
        "generated_at": generated_at.isoformat(),
        "valid_until": (generated_at + timedelta(hours=ttl_hours)).isoformat(),
        "is_synthetic": True, "generation": "fabric-spark-content-v1",
        "provenance": provenance, "personalized": personalized,
        "cold_start_by_role": cold_start, "mandatory_reasons": policy["mandatory_reasons"],
    }
