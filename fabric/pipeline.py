"""Create or explicitly update the manual native Spark batch pipeline."""

import argparse
import base64
import json
from pathlib import Path
from uuid import UUID

from fabric.cloud import configure_auth_cli, json_request, workspace_endpoints
from fabric.run import create_item, save, wait_operation


PIPELINE_NAME = "genius-recommendation-batch"


def pipeline_definition(state: dict) -> dict:
    workspace = str(UUID(state["workspace_id"]))
    job_id = str(UUID(state["spark_job"]["id"]))
    connection_id = str(UUID(state["spark_job"]["connection_id"]))
    model = state["trained_model"]
    if not all(model.get(key) for key in ("model_uri", "model_version", "mlflow_run_id")):
        raise ValueError("Manual pipeline requires a specific approved model version")
    config = {key: state[key] for key in (
        "workspace_id", "lakehouse_id", "input_hashes", "input_path",
        "code_path", "code_version", "training_key")}
    config.update(code_path=state["spark_job"]["code_path"],
                  code_version=state["spark_job"]["code_version"],
                  package_sha256=state["spark_job"]["package_sha256"])
    config.update(approved_model=model)
    encoded = base64.b64encode(json.dumps(config, ensure_ascii=False).encode("utf-8")).decode("ascii")
    literal = f"--config-base64 {encoded} --batch-key __BATCH_KEY__ --as-of __AS_OF__"
    expression = (
        f"@replace(replace('{literal}', '__BATCH_KEY__', pipeline().RunId), "
        "'__AS_OF__', pipeline().TriggerTime)"
    )
    content = {"properties": {
        "description": "Manual recommendation generation, validation and Lakehouse export. No training or API publication.",
        "concurrency": 1,
        "activities": [{
            "name": "Generate_and_validate_recommendations",
            "type": "FabricSparkJobDefinition",
            "externalReferences": {"connection": connection_id},
            "dependsOn": [],
            "policy": {"timeout": "0.00:30:00", "retry": 0,
                       "secureInput": False, "secureOutput": False},
            "typeProperties": {
                "sparkJobDefinitionId": job_id, "workspaceId": workspace,
                "commandLineArguments": expression,
            },
        }],
    }}
    return {"parts": [{
        "path": "pipeline-content.json", "payloadType": "InlineBase64",
        "payload": base64.b64encode(json.dumps(content, ensure_ascii=False).encode("utf-8")).decode("ascii"),
    }]}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", required=True, type=Path)
    parser.add_argument("--auth-cli", choices=["az", "azd"], default="az")
    parser.add_argument("--proxy", default="socks5h://127.0.0.1:1080")
    parser.add_argument("--update", action="store_true")
    args = parser.parse_args()
    configure_auth_cli(args.auth_cli)
    state = json.loads(args.state.read_text(encoding="utf-8"))
    definition = pipeline_definition(state)
    endpoint, _ = workspace_endpoints(state["workspace_id"])
    base = f"{endpoint}/v1/workspaces/{state['workspace_id']}"
    _, _, items = json_request("GET", base + "/items", proxy=args.proxy)
    if items.get("continuationToken"):
        raise ValueError("Inspect all workspace items before creating a pipeline")
    matches = [item for item in items["value"] if item["displayName"] == PIPELINE_NAME]
    if matches and not args.update:
        raise ValueError("Manual pipeline already exists; refusing to create a duplicate or overwrite it")
    spark_job = next(
        (item for item in items["value"]
         if item["id"] == state["spark_job"]["id"] and item["type"] == "SparkJobDefinition"),
        None)
    if spark_job is None or state["spark_job"].get("status") not in {"ready", "verified"}:
        raise ValueError("The configured Spark Job Definition is not ready in this workspace")
    if args.update:
        if (len(matches) != 1 or matches[0]["type"] != "DataPipeline"
                or matches[0]["id"] != state["manual_pipeline"]["id"]):
            raise ValueError("Refusing to update a different pipeline")
        item = matches[0]
        status, headers, existing = json_request(
            "POST", base + f"/dataPipelines/{item['id']}/getDefinition", {}, args.proxy)
        if status == 202:
            existing = wait_operation(headers, args.proxy, state)
        backup = args.state.with_name(args.state.stem + "-pipeline-before-spark.json")
        if backup.exists() and state["manual_pipeline"].get("spark_job_id") != spark_job["id"]:
            raise ValueError("Pipeline migration backup already exists; inspect before retrying")
        if not backup.exists():
            save(backup, existing)
        status, headers, _ = json_request(
            "POST", base + f"/dataPipelines/{item['id']}/updateDefinition",
            {"definition": definition}, args.proxy)
        if status == 202:
            wait_operation(headers, args.proxy, state, result_required=False)
    else:
        item = create_item(state, "dataPipelines", PIPELINE_NAME, args.proxy, definition)
    state["manual_pipeline"] = {
        "id": item["id"], "name": PIPELINE_NAME,
        "spark_job_id": spark_job["id"], "definition": definition,
    }
    save(args.state, state)
    print(json.dumps({"pipeline_id": item["id"], "name": PIPELINE_NAME,
                      "spark_job_id": spark_job["id"], "schedule_created": False}))


if __name__ == "__main__":
    main()
