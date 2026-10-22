from datetime import datetime
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ErrorDetail(Model):
    code: Literal["UNAUTHORIZED", "FORBIDDEN", "NO_RESULTS", "STALE_DATA",
                  "INVALID_REQUEST", "SYSTEM_ERROR"]
    message: str
    request_id: str | None = None


class ErrorResponse(Model):
    error: ErrorDetail


class Enrollment(Model):
    opens_at: AwareDatetime
    closes_at: AwareDatetime


class Course(Model):
    id: str
    title: str
    category_id: str
    skill_tags: list[str]
    level: Literal["beginner", "intermediate", "advanced"]
    duration_minutes: int = Field(gt=0)
    language: Literal["ko", "en"]
    subtitle_languages: list[Literal["ko", "en"]]
    summary: str
    learning_objectives: list[str]
    target_roles: list[str]
    prerequisite_knowledge: list[str]
    curriculum: list[str]
    has_hands_on: bool
    eligible_roles: list[str]
    prerequisite_course_ids: list[str]
    enrollment: Enrollment
    status: Literal["open", "closed", "cancelled", "upcoming"]
    is_mandatory: bool
    detail_path: str
    source_ref: str
    data_version: str
    is_synthetic: Literal[True]


class Learner(Model):
    id: str
    role: str
    history_state: Literal["sufficient", "insufficient"]
    completed_course_ids: list[str]


class ReasonEvidence(Model):
    rule: Literal["content_similarity", "cold_start_role_policy"]
    role: str
    matched_tags: list[str]
    completed_course_ids: list[str]
    source_refs: list[str] = Field(min_length=1)
    policy_version: str


class FabricProvenance(Model):
    workspace_id: str = Field(min_length=1)
    lakehouse_id: str = Field(min_length=1)
    job_id: str = Field(min_length=1)
    mlflow_run_id: str = Field(min_length=1)
    model_uri: str = Field(min_length=1)
    model_version: str = Field(min_length=1)
    method: Literal["spark_ml_tfidf_cosine"]
    code_version: str = Field(min_length=1)
    policy_version: str = Field(min_length=1)
    input_versions: dict[str, str]
    input_sha256: dict[str, str]
    as_of: AwareDatetime
    validated_at: AwareDatetime


class Candidate(Model):
    course_id: str
    rank: int = Field(gt=0)
    reason: str = Field(min_length=1)
    evidence: ReasonEvidence | None = None
    score: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)


class Snapshot(Model):
    data_version: str
    catalog_version: str
    generated_at: AwareDatetime
    valid_until: AwareDatetime
    is_synthetic: Literal[True]
    generation: Literal["mock-fabric-static-snapshot", "fabric-spark-content-v1"]
    provenance: FabricProvenance | None = None
    personalized: dict[str, list[Candidate]]
    cold_start_by_role: dict[str, list[Candidate]]
    mandatory_reasons: dict[str, str]

    @model_validator(mode="after")
    def validate_fabric_generation(self):
        if self.generation == "fabric-spark-content-v1":
            if self.provenance is None:
                raise ValueError("Fabric output requires provenance")
            if (self.valid_until - self.generated_at).total_seconds() > 48 * 3600:
                raise ValueError("Fabric output validity exceeds 48 hours")
            if not self.provenance.as_of <= self.generated_at <= self.provenance.validated_at:
                raise ValueError("Invalid Fabric execution timestamps")
            for group in [*self.personalized.values(), *self.cold_start_by_role.values()]:
                if any(c.evidence is None for c in group):
                    raise ValueError("Fabric candidates require evidence")
        return self


class CourseView(Model):
    course: Course
    can_take: bool
    exclusion_reasons: list[str]


class CourseResults(Model):
    status: Literal["OK", "NO_RESULTS"] = "OK"
    is_synthetic: Literal[True] = True
    catalog_version: str
    items: list[CourseView]


class RecommendationItem(Model):
    rank: int
    reason: str
    reason_source_ref: str
    course: Course
    evidence: ReasonEvidence | None = None


class MandatoryItem(Model):
    reason: str
    reason_source_ref: str
    course: Course


class Recommendations(Model):
    status: Literal["OK"] = "OK"
    is_synthetic: Literal[True] = True
    mode: Literal["personalized", "cold_start"]
    version: str
    catalog_version: str
    generated_at: datetime
    valid_until: datetime
    generation: str
    provenance: FabricProvenance | None = None
    items: list[RecommendationItem]
    mandatory_items: list[MandatoryItem]
