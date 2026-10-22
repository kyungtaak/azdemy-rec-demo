from datetime import datetime


def exclusion_reasons(
    *, course_id: str, eligible_roles: list[str], prerequisite_course_ids: list[str],
    status: str, opens_at: datetime, closes_at: datetime, learner_role: str,
    completed_course_ids: list[str], now: datetime,
) -> list[str]:
    reasons = []
    if course_id in completed_course_ids:
        reasons.append("COMPLETED")
    if learner_role not in eligible_roles:
        reasons.append("INELIGIBLE_ROLE")
    if not set(prerequisite_course_ids) <= set(completed_course_ids):
        reasons.append("PREREQUISITES_NOT_MET")
    if status != "open":
        reasons.append(f"COURSE_{status.upper()}")
    if now < opens_at:
        reasons.append("ENROLLMENT_NOT_STARTED")
    if now > closes_at:
        reasons.append("ENROLLMENT_ENDED")
    return reasons
