"""Package the shared batch code and configure the notebook-free Fabric Spark job."""

import argparse
import base64
import hashlib
import io
import json
from pathlib import Path
from uuid import UUID
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from fabric.cloud import configure_auth_cli, json_request, workspace_endpoints
from fabric.run import ROOT, put_file, save, wait_operation


def package_code(root: Path) -> tuple[bytes, str]:
    buffer = io.BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
        for path in sorted((root / "azdemy_recommendations").glob("*.py")):
            info = ZipInfo(path.relative_to(root).as_posix(), date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            archive.writestr(info, path.read_bytes())
    payload = buffer.getvalue()
    main = (root / "fabric" / "spark_batch_main.py").read_bytes()
    return payload, hashlib.sha256(payload + main).hexdigest()


def spark_definition(state: dict, main: bytes) -> dict:
    UUID(state["workspace_id"])
    lakehouse = str(UUID(state["lakehouse_id"]))
    properties = {
        "executableFile": "spark_batch_main.py", "defaultLakehouseArtifactId": lakehouse,
        "mainClass": "", "additionalLakehouseIds": [], "retryPolicy": None,
        "commandLineArguments": "", "additionalLibraryUris": [],
        "language": "Python", "environmentArtifactId": None,
    }
    return {"format": "SparkJobDefinitionV2", "parts": [
        {"path": "SparkJobDefinitionV1.json", "payloadType": "InlineBase64",
         "payload": base64.b64encode(json.dumps(properties).encode("utf-8")).decode("ascii")},
        {"path": "Main/spark_batch_main.py", "payloadType": "InlineBase64",
         "payload": base64.b64encode(main).decode("ascii")},
    ]}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", required=True, type=Path)
    parser.add_argument("--auth-cli", choices=["az", "azd"], default="az")
    parser.add_argument("--proxy", default="socks5h://127.0.0.1:1080")
    args = parser.parse_args()
    configure_auth_cli(args.auth_cli)
    state = json.loads(args.state.read_text(encoding="utf-8"))
    job_id = str(UUID(state["spark_job"]["id"]))
    endpoint, _ = workspace_endpoints(state["workspace_id"])
    base = f"{endpoint}/v1/workspaces/{state['workspace_id']}"
    _, _, item = json_request("GET", base + "/items/" + job_id, proxy=args.proxy)
    if item["type"] != "SparkJobDefinition" or item["displayName"] != "genius-recommendation-spark-job":
        raise ValueError("Spark job identity differs from the approved migration target")
    payload, version = package_code(ROOT)
    code_path = f"code/{version}"
    relative_path = f"{code_path}/azdemy_recommendations.zip"
    put_file(state, relative_path, payload, args.proxy)
    definition = spark_definition(
        state, (ROOT / "fabric" / "spark_batch_main.py").read_bytes())
    status, headers, _ = json_request(
        "POST", base + f"/sparkJobDefinitions/{job_id}/updateDefinition",
        {"definition": definition}, args.proxy)
    if status == 202:
        wait_operation(headers, args.proxy, state, result_required=False)
    state["spark_job"].update(
        status="ready", definition=definition, code_version=version,
        code_path=code_path, package_sha256=hashlib.sha256(payload).hexdigest())
    save(args.state, state)
    print(json.dumps({"spark_job_id": job_id, "code_version": version,
                      "runtime": "SparkJobDefinition", "notebook_execution": False}))


if __name__ == "__main__":
    main()
