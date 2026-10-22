"""Executed in the Fabric Spark runtime, not imported by the API."""

import hashlib
import json
import math
import shutil
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from .recommender import build_snapshot


def delta_table_path(config: dict, context: dict) -> str:
    if (UUID(context["currentWorkspaceId"]) != UUID(config["workspace_id"])
            or UUID(context["defaultLakehouseId"]) != UUID(config["lakehouse_id"])):
        raise ValueError("Spark default Lakehouse differs from the approved workspace binding")
    return "Tables/genius_recommendations"


def read_inputs(config: dict, files_root: Path | None = None) -> tuple[Path, dict, dict, dict]:
    root = (files_root if files_root is not None else Path("/lakehouse/default/Files")) / config["input_path"]
    catalog = json.loads((root / "courses.synthetic.json").read_text(encoding="utf-8"))
    learners = json.loads((root / "learners.synthetic.json").read_text(encoding="utf-8"))
    policy = json.loads((root / "recommendation-policy.synthetic.json").read_text(encoding="utf-8"))
    for name, digest in config["input_hashes"].items():
        if hashlib.sha256((root / name).read_bytes()).hexdigest() != digest:
            raise ValueError(f"Input checksum mismatch: {name}")
    return root, catalog, learners, policy


def tokens(course: dict) -> list[str]:
    return sorted({f"skill:{v}" for v in course["skill_tags"]}
                  | {f"role:{v}" for v in course["target_roles"]})


def train(config: dict, spark) -> dict:
    import mlflow
    import mlflow.spark
    from pyspark.ml import Pipeline
    from pyspark.ml.feature import CountVectorizer, IDF, Normalizer

    _, catalog, _, policy = read_inputs(config)
    mlflow.autolog(disable=True)
    mlflow.set_experiment("genius-content-baseline")
    frame = spark.createDataFrame([(c["id"], tokens(c)) for c in catalog["courses"]], ["id", "tokens"])
    with mlflow.start_run(run_name=f"train-{config['code_version'][:12]}") as run:
        mlflow.log_params({
            "method": "spark_ml_tfidf_cosine", "catalog_version": catalog["data_version"],
            "policy_version": policy["data_version"], "code_version": config["code_version"],
            "course_count": len(catalog["courses"]), "quality_evaluated": False,
            "spark_version": spark.version,
        })
        pipeline = Pipeline(stages=[
            CountVectorizer(inputCol="tokens", outputCol="counts", minDF=1.0),
            IDF(inputCol="counts", outputCol="weighted"),
            Normalizer(inputCol="weighted", outputCol="features"),
        ])
        model = pipeline.fit(frame)
        info = mlflow.spark.log_model(model, "model")
        registered = mlflow.register_model(info.model_uri, "genius-content-baseline")
        result = {
            "model_uri": info.model_uri, "model_version": str(registered.version),
            "mlflow_run_id": run.info.run_id, "code_version": config["code_version"],
            "input_hashes": config["input_hashes"],
        }
    path = Path("/lakehouse/default/Files/control") / config["training_key"]
    path.mkdir(parents=True, exist_ok=True)
    (path / "trained-model.json").write_text(json.dumps(result), encoding="utf-8")
    return result


def batch(config: dict, spark, context: dict, *, files_root: Path | None = None) -> dict:
    import mlflow
    import mlflow.spark
    from delta.tables import DeltaTable

    files = files_root if files_root is not None else Path("/lakehouse/default/Files")
    source, catalog, learners, policy = read_inputs(config, files)
    model_info = config["approved_model"]
    root = files / "batches" / config["batch_key"]
    complete = root / "_SUCCESS"
    delta_path = delta_table_path(config, context)
    if complete.exists():
        result = json.loads(complete.read_text(encoding="utf-8"))
        if (result["input_hashes"] != config["input_hashes"]
                or result["provenance"]["model_uri"] != model_info["model_uri"]
                or result["provenance"]["code_version"] != config["code_version"]
                or result["provenance"]["as_of"] != config["as_of"]):
            raise ValueError("Conflicting reuse of a completed batch key")
        manifest = json.loads((root / "export" / "manifest.json").read_text(encoding="utf-8"))
        for name, digest in manifest["files"].items():
            if hashlib.sha256((root / "export" / name).read_bytes()).hexdigest() != digest:
                raise ValueError("Completed batch export has been damaged")
        persisted = spark.read.format("delta").load(delta_path).filter(
                f"batch_key = '{config['batch_key']}'")
        if (persisted.count() != result["count"]
                or persisted.dropDuplicates(["subject", "mode", "course_id"]).count() != result["count"]):
            raise ValueError("Completed batch Delta rows are missing, duplicated or damaged")
        return result
    root.mkdir(parents=True, exist_ok=True)
    generation_file = root / "generation.json"
    if not generation_file.exists():
        generation_file.write_text(
            json.dumps({"generated_at": datetime.now(timezone.utc).isoformat()}), encoding="utf-8")
    generated_at = datetime.fromisoformat(json.loads(generation_file.read_text())["generated_at"])
    mlflow.autolog(disable=True)
    model = mlflow.spark.load_model(model_info["model_uri"])
    if [type(stage).__name__ for stage in model.stages] != [
        "CountVectorizerModel", "IDFModel", "Normalizer",
    ]:
        raise ValueError("Approved model does not implement the expected feature pipeline")
    courses = {c["id"]: c for c in catalog["courses"]}
    frame = spark.createDataFrame([(c["id"], tokens(c)) for c in courses.values()], ["id", "tokens"])
    course_vectors = {r.id: r.features.toArray().tolist()
                      for r in model.transform(frame).select("id", "features").collect()}
    profiles = []
    for learner in learners["learners"]:
        if learner["history_state"] == "sufficient":
            profile = {f"role:{learner['role']}"} | {
                f"skill:{tag}" for cid in learner["completed_course_ids"]
                for tag in courses[cid]["skill_tags"]}
            profiles.append((learner["id"], sorted(profile)))
    profile_frame = spark.createDataFrame(profiles, "id string, tokens array<string>")
    scores = {}
    for row in model.transform(profile_frame).select("id", "features").collect():
        vector = row.features.toArray().tolist()
        scores[row.id] = {}
        for cid, features in course_vectors.items():
            value = sum(a * b for a, b in zip(vector, features))
            if not math.isfinite(value) or not -1e-12 <= value <= 1 + 1e-12:
                raise ValueError("Non-finite or invalid normalized model similarity")
            scores[row.id][cid] = min(1.0, max(0.0, value))
    activity_id = context.get("activityId")
    if not activity_id:
        raise ValueError("Fabric runtime did not supply an activityId")
    provenance = {
        "workspace_id": config["workspace_id"], "lakehouse_id": config["lakehouse_id"],
        "job_id": activity_id, "mlflow_run_id": model_info["mlflow_run_id"],
        "model_uri": model_info["model_uri"], "model_version": model_info["model_version"],
        "method": "spark_ml_tfidf_cosine", "code_version": config["code_version"],
        "policy_version": policy["data_version"], "input_versions": {
            "catalog": catalog["data_version"], "learners": learners["data_version"]},
        "input_sha256": {
            "catalog": config["input_hashes"]["courses.synthetic.json"],
            "learners": config["input_hashes"]["learners.synthetic.json"]},
        "as_of": config["as_of"], "validated_at": datetime.now(timezone.utc).isoformat(),
    }
    snapshot = build_snapshot(catalog, learners, policy, scores, provenance,
                              f"fabric-{config['batch_key']}", generated_at, 48, 3)
    rows = []
    for mode, groups in [("personalized", snapshot["personalized"]),
                         ("cold_start", snapshot["cold_start_by_role"])]:
        for subject, items in groups.items():
            for item in items:
                rows.append((config["batch_key"], subject, mode, item["course_id"], item["rank"],
                             json.dumps(item, ensure_ascii=False), model_info["mlflow_run_id"]))
    frame = spark.createDataFrame(
        rows, "batch_key string, subject string, mode string, course_id string, rank int, "
        "candidate_json string, model_run_id string")
    if DeltaTable.isDeltaTable(spark, delta_path):
        DeltaTable.forPath(spark, delta_path).alias("target").merge(
            frame.alias("source"),
            "target.batch_key=source.batch_key AND target.subject=source.subject "
            "AND target.mode=source.mode AND target.course_id=source.course_id",
        ).whenMatchedUpdateAll().whenNotMatchedInsertAll().execute()
    else:
        frame.write.format("delta").mode("errorifexists").save(delta_path)
    stored = spark.read.format("delta").load(delta_path).filter(
        f"batch_key = '{config['batch_key']}'")
    if stored.count() != len(rows) or stored.dropDuplicates(
        ["batch_key", "subject", "mode", "course_id"]).count() != len(rows):
        raise ValueError("Delta result count or uniqueness validation failed")
    if (stored.exceptAll(frame).count() != 0 or frame.exceptAll(stored).count() != 0):
        raise ValueError("Delta result values differ from the validated batch")
    export = root / "export"
    export.mkdir(exist_ok=True)
    for name in ("courses.synthetic.json", "learners.synthetic.json"):
        shutil.copyfile(source / name, export / name)
    (export / "recommendations.synthetic.json").write_text(
        json.dumps(snapshot, ensure_ascii=False), encoding="utf-8")
    manifest = {
        "schema_version": 1, "version": snapshot["data_version"],
        "files": {name: hashlib.sha256((export / name).read_bytes()).hexdigest() for name in (
            "courses.synthetic.json", "learners.synthetic.json", "recommendations.synthetic.json")},
    }
    (export / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    result = {"version": snapshot["data_version"], "count": len(rows),
              "export": f"batches/{config['batch_key']}/export", "provenance": provenance,
              "input_hashes": config["input_hashes"]}
    complete.write_text(json.dumps(result), encoding="utf-8")
    return result
