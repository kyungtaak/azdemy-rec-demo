import json
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import TypeAdapter

from azdemy_recommendations.eligibility import exclusion_reasons
from azdemy_recommendations.reasons import build_evidence, render_reason
from api.models import (
    Course, CourseResults, CourseView, Learner, MandatoryItem,
    RecommendationItem, Recommendations, Snapshot,
)


class ServiceError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


class Store:
    def __init__(self, data_dir: Path):
        catalog_text = (data_dir / "courses.synthetic.json").read_text(encoding="utf-8")
        catalog = json.loads(catalog_text)
        courses = TypeAdapter(list[Course]).validate_json(json.dumps(catalog["courses"]))
        self.courses = {c.id: c for c in courses}
        self.catalog_version = catalog["data_version"]
        self.categories = {c["id"] for c in catalog["categories"]}
        self.roles = {r["id"] for r in catalog["roles"]}
        learners = json.loads((data_dir / "learners.synthetic.json").read_text(encoding="utf-8"))
        parsed = TypeAdapter(list[Learner]).validate_json(json.dumps(learners["learners"]))
        self.learners = {learner.id: learner for learner in parsed}
        self.snapshot = Snapshot.model_validate_json(
            (data_dir / "recommendations.synthetic.json").read_text(encoding="utf-8"))
        if (catalog["is_synthetic"] is not True or learners["is_synthetic"] is not True
                or learners["data_version"] != self.catalog_version
                or len(self.courses) != len(courses) or len(self.learners) != len(parsed)
                or self.snapshot.catalog_version != self.catalog_version
                or self.snapshot.generated_at >= self.snapshot.valid_until):
            raise ValueError("Invalid snapshot identity, version or validity interval")
        for course in courses:
            if (course.category_id not in self.categories
                    or not set(course.eligible_roles) <= self.roles
                    or not set(course.prerequisite_course_ids) <= self.courses.keys()
                    or course.enrollment.opens_at >= course.enrollment.closes_at):
                raise ValueError(f"Invalid catalog references: {course.id}")
        for learner in parsed:
            if (learner.role not in self.roles
                    or not set(learner.completed_course_ids) <= self.courses.keys()):
                raise ValueError(f"Invalid learner references: {learner.id}")
        if not self.snapshot.personalized.keys() <= self.learners.keys():
            raise ValueError("Unknown personalized learner")
        if not self.snapshot.cold_start_by_role.keys() <= self.roles:
            raise ValueError("Unknown cold-start role")
        groups = [*self.snapshot.personalized.values(), *self.snapshot.cold_start_by_role.values()]
        for candidates in groups:
            ids = [c.course_id for c in candidates]
            ranks = [c.rank for c in candidates]
            if (len(ids) != len(set(ids)) or len(ranks) != len(set(ranks))
                    or ranks != sorted(ranks) or not set(ids) <= self.courses.keys()):
                raise ValueError("Invalid recommendation references or ordering")
        mandatory_ids = {c.id for c in courses if c.is_mandatory}
        if set(self.snapshot.mandatory_reasons) != mandatory_ids:
            raise ValueError("Mandatory reasons must match mandatory courses")
        if self.snapshot.generation == "fabric-spark-content-v1":
            provenance = self.snapshot.provenance
            if provenance is None:
                raise ValueError("Missing Fabric provenance")
            expected_versions = {"catalog": self.catalog_version,
                                 "learners": learners["data_version"]}
            expected_hashes = {
                "catalog": hashlib.sha256((data_dir / "courses.synthetic.json").read_bytes()).hexdigest(),
                "learners": hashlib.sha256((data_dir / "learners.synthetic.json").read_bytes()).hexdigest(),
            }
            if (provenance.input_versions != expected_versions
                    or provenance.input_sha256 != expected_hashes):
                raise ValueError("Fabric input provenance does not match release data")
            required = {v.id for v in parsed if v.history_state == "sufficient"}
            if set(self.snapshot.personalized) != required:
                raise ValueError("Fabric output must cover sufficient-history learners")
            for key, candidates in [
                *self.snapshot.personalized.items(), *self.snapshot.cold_start_by_role.items(),
            ]:
                cold = key in self.roles
                learner_data = ({"role": key, "completed_course_ids": []} if cold
                                else self.learners[key].model_dump())
                if len(candidates) > 3:
                    raise ValueError("Fabric output exceeds approved K")
                for candidate in candidates:
                    expected = build_evidence(
                        catalog, learner_data, candidate.course_id,
                        {"data_version": provenance.policy_version}, cold_start=cold)
                    if (candidate.evidence is None
                            or candidate.evidence.model_dump() != expected
                            or candidate.reason != render_reason(expected)):
                        raise ValueError("Recommendation reason is not grounded in release data")
                    learner = Learner(id="policy", history_state="insufficient", **learner_data) if cold else self.learners[key]
                    course = self.courses[candidate.course_id]
                    if course.is_mandatory or self.exclusions(course, learner, self.snapshot.generated_at):
                        raise ValueError("Fabric result contains an excluded course")

    def exclusions(self, course: Course, learner: Learner, now: datetime) -> list[str]:
        return exclusion_reasons(
            course_id=course.id, eligible_roles=course.eligible_roles,
            prerequisite_course_ids=course.prerequisite_course_ids, status=course.status,
            opens_at=course.enrollment.opens_at, closes_at=course.enrollment.closes_at,
            learner_role=learner.role, completed_course_ids=learner.completed_course_ids, now=now)

    def course_results(self, ids: list[str], learner: Learner, now: datetime) -> CourseResults:
        if not ids or any(course_id not in self.courses for course_id in ids):
            raise ServiceError(404, "NO_RESULTS", "일치하는 합성 과정을 확인할 수 없습니다.")
        items = []
        for course_id in ids:
            course = self.courses[course_id]
            reasons = self.exclusions(course, learner, now)
            items.append(CourseView(course=course, can_take=not reasons, exclusion_reasons=reasons))
        return CourseResults(catalog_version=self.catalog_version, items=items)

    def search(self, learner: Learner, now: datetime, query: str = "",
               category: str | None = None, language: Literal["ko", "en"] | None = None,
               limit: int = 10) -> CourseResults:
        if category is not None and category not in self.categories:
            raise ServiceError(422, "INVALID_REQUEST", "알 수 없는 카테고리입니다.")
        term = query.casefold().strip()
        ids = [
            c.id for c in self.courses.values()
            if (category is None or c.category_id == category)
            and (language is None or c.language == language)
            and (not term or term in " ".join([c.title, c.summary, *c.skill_tags]).casefold())
        ][:limit]
        if not ids:
            return CourseResults(status="NO_RESULTS", catalog_version=self.catalog_version, items=[])
        return self.course_results(ids, learner, now)

    def recommendations(self, learner: Learner, now: datetime) -> Recommendations:
        snapshot = self.snapshot
        if now < snapshot.generated_at or now > snapshot.valid_until:
            raise ServiceError(409, "STALE_DATA", "추천 snapshot이 유효 기간 밖입니다. 재게시가 필요합니다.")
        mode: Literal["personalized", "cold_start"]
        if learner.history_state == "insufficient":
            mode = "cold_start"
            candidates = snapshot.cold_start_by_role.get(learner.role)
        else:
            mode = "personalized"
            candidates = snapshot.personalized.get(learner.id)
        if candidates is None:
            raise ServiceError(503, "SYSTEM_ERROR", "해당 학습자의 추천 snapshot을 사용할 수 없습니다.")
        items = []
        for candidate in candidates:
            course = self.courses[candidate.course_id]
            if course.is_mandatory or self.exclusions(course, learner, now):
                continue
            items.append(RecommendationItem(
                rank=candidate.rank, reason=candidate.reason, course=course,
                evidence=candidate.evidence,
                reason_source_ref=f"recommendation:{snapshot.data_version}:{mode}:{course.id}"))
        mandatory = [
            MandatoryItem(course=c, reason=snapshot.mandatory_reasons[c.id],
                          reason_source_ref=f"mandatory:{snapshot.data_version}:{c.id}")
            for c in self.courses.values()
            if c.is_mandatory and not self.exclusions(c, learner, now)
        ]
        if not items and not mandatory:
            raise ServiceError(404, "NO_RESULTS", "조건에 맞는 추천 교육이 없습니다.")
        return Recommendations(
            mode=mode, version=snapshot.data_version, catalog_version=self.catalog_version,
            generated_at=snapshot.generated_at, valid_until=snapshot.valid_until,
            generation=snapshot.generation, provenance=snapshot.provenance,
            items=items, mandatory_items=mandatory)
