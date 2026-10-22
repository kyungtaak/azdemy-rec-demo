import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import Depends, FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from api.auth import authenticated_learner_id, get_auth_settings
from api.models import CourseResults, CourseView, ErrorResponse, Learner, Recommendations
from api.service import ServiceError, Store
from api.publication import process_pending, read_active_store


logger = logging.getLogger("azdemy.api")
DATA_DIR = Path(__file__).resolve().parents[1] / "data"
API_URL = "https://geniusmda53gutapi.azurewebsites.net"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def get_store(request: Request) -> Store:
    root = getattr(request.app.state, "publication_root", None)
    if root is not None:
        try:
            return read_active_store(root, utc_now())
        except (OSError, ValueError, KeyError) as error:
            logger.error("Published recommendation data unavailable: %s", error)
            raise ServiceError(503, "SYSTEM_ERROR", "게시된 추천 데이터를 사용할 수 없습니다.") from error
    store = request.app.state.store
    if store is None:
        raise ServiceError(503, "SYSTEM_ERROR", "데모 데이터가 준비되지 않았습니다.")
    return store


def current_learner(
    learner_id: str = Depends(authenticated_learner_id),
    store: Store = Depends(get_store),
) -> Learner:
    learner = store.learners.get(learner_id)
    if learner is None:
        raise ServiceError(403, "FORBIDDEN", "허용된 합성 학습자 매핑이 없습니다.")
    return learner


def check_query(request: Request):
    allowed = {
        "/recommendations/me": set(),
        "/courses/search": {"query", "category", "language", "limit"},
        "/courses": {"ids"},
    }.get(request.url.path, set())
    keys = request.query_params.keys()
    if set(keys) - allowed or any(len(request.query_params.getlist(k)) != 1 for k in keys):
        raise ServiceError(422, "INVALID_REQUEST", "허용되지 않거나 중복된 조회 parameter입니다.")


def create_app(store: Store | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(application: FastAPI):
        settings = get_auth_settings()
        publication_path = os.environ.get("GENIUS_PUBLICATION_ROOT")
        application.state.publication_root = Path(publication_path) if publication_path else None
        if application.state.publication_root is not None:
            process_pending(application.state.publication_root, utc_now())
            application.state.store = read_active_store(application.state.publication_root, utc_now())
        elif application.state.store is None:
            application.state.store = Store(DATA_DIR)
        if not set(settings.principal_learners.values()) <= application.state.store.learners.keys():
            raise ValueError("Authentication maps to an unknown synthetic learner")
        yield

    application = FastAPI(
        title="Azdemy Read-only Education API", version="1.0.0",
        description="합성 교육 데이터만 조회합니다. 수강 신청이나 직원 정보 변경은 불가능합니다.",
        servers=[{"url": API_URL}], lifespan=lifespan,
        dependencies=[Depends(check_query)],
        responses={
            status: {"model": ErrorResponse, "description": code}
            for status, code in {
                401: "UNAUTHORIZED", 403: "FORBIDDEN", 404: "NO_RESULTS",
                409: "STALE_DATA", 422: "INVALID_REQUEST",
                500: "SYSTEM_ERROR", 503: "SYSTEM_ERROR",
            }.items()
        },
        docs_url=None, redoc_url=None, openapi_url=None)
    application.state.store = store

    @application.middleware("http")
    async def error_boundary(request: Request, call_next):
        request_id = str(uuid4())
        try:
            response = await call_next(request)
        except Exception:
            logger.exception("Unexpected API failure request_id=%s", request_id)
            response = JSONResponse(
                status_code=500,
                content={"error": {"code": "SYSTEM_ERROR", "message": "API 처리 중 오류가 발생했습니다.",
                                   "request_id": request_id}})
        response.headers["X-Request-ID"] = request_id
        response.headers["Cache-Control"] = "no-store"
        return response

    @application.exception_handler(ServiceError)
    async def service_error(request: Request, error: ServiceError):
        logger.warning("API rejected request code=%s status=%s", error.code, error.status)
        headers = {"WWW-Authenticate": "Bearer"} if error.status == 401 else None
        return JSONResponse(status_code=error.status,
                            content={"error": {"code": error.code, "message": error.message}},
                            headers=headers)

    @application.exception_handler(RequestValidationError)
    async def validation_error(request: Request, error: RequestValidationError):
        logger.warning("Invalid request parameter count=%s", len(error.errors()))
        return JSONResponse(status_code=422, content={
            "error": {"code": "INVALID_REQUEST", "message": "조회 parameter 형식을 확인하세요."}})

    @application.get("/recommendations/me", operation_id="getMyRecommendations",
                     response_model=Recommendations)
    def recommendations(learner: Learner = Depends(current_learner),
                        repository: Store = Depends(get_store),
                        now: datetime = Depends(utc_now)):
        """본인의 추천 snapshot을 조회합니다. 다른 직원 ID를 입력할 수 없습니다."""
        return repository.recommendations(learner, now)

    @application.get("/courses/search", operation_id="searchCourses", response_model=CourseResults)
    def search(
        query: Annotated[str, Query(max_length=100)] = "",
        category: Annotated[str | None, Query(
            max_length=40,
            description="Category ID: development, data_ai, cloud, security, productivity, leadership",
        )] = None,
        language: Annotated[Literal["ko", "en"] | None, Query(
            description="Lecture language CODE only: ko for Korean, en for English. Never use language names.",
        )] = None,
        limit: Annotated[int, Query(ge=1, le=30)] = 10,
        learner: Learner = Depends(current_learner),
        repository: Store = Depends(get_store), now: datetime = Depends(utc_now),
    ):
        """합성 과정 사실과 본인의 수강 가능 여부를 검색합니다."""
        return repository.search(learner, now, query, category, language, limit)

    @application.get("/courses", operation_id="getCourses", response_model=CourseResults)
    def courses(
        ids: Annotated[str, Query(min_length=1, max_length=200,
                                  description="쉼표로 구분한 합성 과정 ID, 최대 5개")],
        learner: Learner = Depends(current_learner),
        repository: Store = Depends(get_store), now: datetime = Depends(utc_now),
    ):
        """최대 5개 과정의 상세 사실을 조회합니다. 비교는 이 사실을 근거로 수행합니다."""
        course_ids = [item.strip() for item in ids.split(",")]
        if (not 1 <= len(course_ids) <= 5 or len(set(course_ids)) != len(course_ids)
                or any(not item for item in course_ids)):
            raise ServiceError(422, "INVALID_REQUEST", "서로 다른 과정 ID를 1~5개 입력하세요.")
        return repository.course_results(course_ids, learner, now)

    @application.get("/demo/courses/{course_id}", include_in_schema=False, response_model=CourseView)
    def course_detail(course_id: str, learner: Learner = Depends(current_learner),
                      repository: Store = Depends(get_store), now: datetime = Depends(utc_now)):
        return repository.course_results([course_id], learner, now).items[0]

    return application


app = create_app()
