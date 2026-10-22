"""Explicit operator stages for the synthetic private Fabric demo."""

import argparse
import base64
import hashlib
import io
import json
import os
import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote, urlparse
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZipFile

from api.publication import atomic_json, safe_name, validate_directory, write_manifest
from fabric.cloud import configure_auth_cli, json_request, request, workspace_endpoints


ROOT = Path(__file__).resolve().parents[1]
CAPACITY_ID = "28e18dcd-7720-4325-8190-c51cda278a81"
ARM = "https://management.azure.com"
STORAGE = "https://storage.azure.com/"
SUBSCRIPTION = "b214e225-c96c-489e-a778-a1f25bd40cdb"
APP_RESOURCE = (f"{ARM}/subscriptions/{SUBSCRIPTION}/resourceGroups/rg-genius-rec-demo-krc"
                "/providers/Microsoft.Web/sites/geniusmda53gutapi")


def save(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_json(path, value)


def check_deadline(state: dict) -> None:
    if state.get("deadline") and datetime.now(timezone.utc) >= datetime.fromisoformat(state["deadline"]):
        raise RuntimeError("Approved execution deadline reached; stop and restore compute")


def arm_action(url: str) -> None:
    status, headers, _ = request("POST", url, ARM, b"")
    location = headers.get("azure-asyncoperation") or headers.get("location")
    if status == 202 and not location:
        raise RuntimeError("Compute action did not return an operation URL")
    if location:
        for _ in range(120):
            time.sleep(5)
            _, _, payload = request("GET", location, ARM)
            progress = json.loads(payload)
            if progress.get("status") == "Succeeded":
                return
            if progress.get("status") in {"Failed", "Canceled"}:
                raise RuntimeError(f"Compute action failed: {progress}")
        raise TimeoutError("Compute action did not finish")


def start_compute(state: dict, path: Path, session_window: bool = False) -> None:
    if state.get("compute_started_at"):
        if not session_window or state.get("owned_capacity") or state.get("owned_vm"):
            raise ValueError("An execution window already exists; do not silently extend it")
        state.setdefault("execution_history", []).append({
            k: state.get(k) for k in
            ("compute_started_at", "deadline", "compute_stopped_at", "execution_scope")})
    capacity_url = (f"{ARM}/subscriptions/{SUBSCRIPTION}/resourceGroups/rg-poc-fabric"
                    "/providers/Microsoft.Fabric/capacities/pocfabcap01")
    vm_url = (f"{ARM}/subscriptions/{SUBSCRIPTION}/resourceGroups/rg-genius-rec-demo-krc"
              "/providers/Microsoft.Compute/virtualMachines/vm-genius-jump")
    _, _, payload = request("GET", capacity_url + "?api-version=2023-11-01", ARM)
    capacity = json.loads(payload)
    _, _, payload = request("GET", vm_url + "/instanceView?api-version=2024-07-01", ARM)
    vm = json.loads(payload)
    states = [s["code"] for s in vm["statuses"]]
    state.update(
        compute_started_at=datetime.now(timezone.utc).isoformat(),
        deadline=None if session_window else (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat(),
        execution_scope="active-session-only" if session_window else "two-hours",
        compute_stopped_at=None,
        owned_capacity=capacity["properties"]["state"] == "Paused",
        owned_vm="PowerState/deallocated" in states,
    )
    save(path, state)
    if state["owned_capacity"]:
        arm_action(capacity_url + "/resume?api-version=2023-11-01")
    check_deadline(state)
    if state["owned_vm"]:
        arm_action(vm_url + "/start?api-version=2024-07-01")
    state["compute_ready"] = True
    save(path, state)


def stop_compute(state: dict, path: Path, capacity_only: bool = False) -> None:
    failures = []
    for owned, url in [
        ("owned_capacity", f"{ARM}/subscriptions/{SUBSCRIPTION}/resourceGroups/rg-poc-fabric"
         "/providers/Microsoft.Fabric/capacities/pocfabcap01/suspend?api-version=2023-11-01"),
        ("owned_vm", f"{ARM}/subscriptions/{SUBSCRIPTION}/resourceGroups/rg-genius-rec-demo-krc"
         "/providers/Microsoft.Compute/virtualMachines/vm-genius-jump/deallocate?api-version=2024-07-01"),
    ]:
        if capacity_only and owned == "owned_vm":
            continue
        if state.get(owned):
            try:
                arm_action(url)
                state[owned] = False
            except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
                failures.append(str(error))
            save(path, state)
    if failures:
        raise RuntimeError("Compute cleanup failed: " + "; ".join(failures))
    state["capacity_paused_at" if capacity_only else "compute_stopped_at"] = datetime.now(timezone.utc).isoformat()
    save(path, state)


def wait_operation(headers: dict, proxy: str | None, state: dict, *, result_required: bool = True) -> dict:
    url = headers.get("location")
    endpoint, _ = workspace_endpoints(state["workspace_id"])
    permitted = {"api.fabric.microsoft.com", urlparse(endpoint).hostname}
    if not url or urlparse(url).scheme != "https" or urlparse(url).hostname not in permitted:
        raise RuntimeError("Missing or unexpected Fabric operation Location")
    for _ in range(90):
        check_deadline(state)
        time.sleep(min(30, max(2, int(headers.get("retry-after", "5")))))
        _, headers, operation = json_request("GET", url, proxy=proxy)
        if operation.get("status") == "Succeeded":
            if not result_required:
                return operation
            result_url = headers.get("location") or url.rstrip("/") + "/result"
            if urlparse(result_url).hostname not in permitted:
                raise ValueError("Unexpected Fabric result endpoint")
            _, _, value = json_request("GET", result_url, proxy=proxy)
            return value
        if operation.get("status") in {"Failed", "Cancelled"}:
            raise RuntimeError(f"Fabric operation failed: {operation}")
    raise TimeoutError("Fabric operation did not complete")


def create_item(state: dict, item_type: str, name: str, proxy: str, definition: dict | None = None) -> dict:
    endpoint, _ = workspace_endpoints(state["workspace_id"])
    body = {"displayName": name}
    if definition is not None:
        body["definition"] = definition
    status, headers, result = json_request(
        "POST", f"{endpoint}/v1/workspaces/{state['workspace_id']}/{item_type}", body, proxy)
    return wait_operation(headers, proxy, state) if status == 202 else result


def one_lake_url(state: dict, path: str) -> str:
    _, endpoint = workspace_endpoints(state["workspace_id"])
    return (f"{endpoint}/{state['workspace_id']}/{state['lakehouse_id']}/Files/"
            + quote(path, safe="/"))


def get_file(state: dict, path: str, proxy: str) -> bytes:
    return request("GET", one_lake_url(state, path), STORAGE, proxy=proxy)[2]


def put_file(state: dict, path: str, data: bytes, proxy: str) -> None:
    parts = path.split("/")
    for index in range(1, len(parts)):
        url = one_lake_url(state, "/".join(parts[:index]))
        status, _, existing = request("HEAD", url, STORAGE, proxy=proxy, allow_status=(404,))
        if status == 404:
            request("PUT", url + "?resource=directory", STORAGE, b"", proxy)
    url = one_lake_url(state, path)
    status, file_headers, _ = request("HEAD", url, STORAGE, proxy=proxy, allow_status=(404,))
    overwrite_headers = None
    if status != 404:
        existing = get_file(state, path, proxy)
        if existing == data:
            print(f"OneLake verified existing file: {path} ({len(data)} bytes)", flush=True)
            return
        if len(existing) < len(data) and data.startswith(existing) and file_headers.get("etag"):
            overwrite_headers = {"If-Match": file_headers["etag"]}
            print(f"OneLake retrying interrupted upload: {path}", flush=True)
        else:
            raise ValueError(f"Immutable OneLake file conflicts: {path}")
    request("PUT", url + "?resource=file", STORAGE, b"", proxy, headers=overwrite_headers)
    if data:
        request("PATCH", url + "?action=append&position=0", STORAGE, data, proxy,
                content_type="application/octet-stream")
    request("PATCH", url + f"?action=flush&position={len(data)}", STORAGE, b"", proxy)
    print(f"OneLake uploaded: {path} ({len(data)} bytes)", flush=True)


def run_notebook(state: dict, name: str, config: dict, proxy: str, state_path: Path) -> dict:
    notebook = json.loads((ROOT / "fabric" / f"{name}.ipynb").read_text(encoding="utf-8"))
    notebook["metadata"]["dependencies"] = {"lakehouse": {
        "default_lakehouse": state["lakehouse_id"],
        "default_lakehouse_name": "genius_lakehouse",
        "default_lakehouse_workspace_id": state["workspace_id"],
        "known_lakehouses": [{"id": state["lakehouse_id"]}],
    }}
    notebook["cells"][0]["source"] = [
        "config_json = " + repr(json.dumps(config, ensure_ascii=False)) + "\n"]
    definition = {"format": "ipynb", "parts": [{
        "path": "artifact.content.ipynb", "payloadType": "InlineBase64",
        "payload": base64.b64encode(json.dumps(notebook).encode("utf-8")).decode("ascii"),
    }]}
    endpoint, _ = workspace_endpoints(state["workspace_id"])
    workspace_url = f"{endpoint}/v1/workspaces/{state['workspace_id']}"
    config_hash = hashlib.sha256(json.dumps(config, sort_keys=True).encode("utf-8")).hexdigest()
    binding_key = f"{name}_notebook"
    binding = state.get(binding_key)
    if binding and binding["config_hash"] == config_hash:
        item = {"id": binding["id"]}
    else:
        item = create_item(state, "notebooks", f"azdemy-{name}-{uuid4().hex[:8]}", proxy, definition)
        state[binding_key] = {"id": item["id"], "config_hash": config_hash}
        save(state_path, state)
    status, headers, _ = json_request(
        "POST", f"{workspace_url}/items/{item['id']}/jobs/RunNotebook/instances", {}, proxy)
    if status != 202 or "location" not in headers:
        raise RuntimeError("Notebook job did not return its asynchronous instance")
    location = headers["location"]
    parsed = urlparse(location)
    if parsed.hostname == "api.fabric.microsoft.com" and parsed.path.startswith(
        f"/v1/workspaces/{state['workspace_id']}/"):
        location = endpoint + parsed.path + ("?" + parsed.query if parsed.query else "")
    state[f"{name}_submission"] = {"notebook_id": item["id"], "job_location": location}
    save(state_path, state)
    previous = None
    for _ in range(120):
        check_deadline(state)
        time.sleep(min(30, max(3, int(headers.get("retry-after", "10")))))
        _, headers, job = json_request("GET", location, proxy=proxy)
        if job["status"] != previous:
            print(f"{name}: {job['status']} job={job.get('id')}", flush=True)
            previous = job["status"]
        if job["status"] == "Completed":
            return {"notebook_id": item["id"], "job": job}
        if job["status"] in {"Failed", "Cancelled", "Deduped"}:
            raise RuntimeError(f"Notebook did not complete successfully: {job}")
    raise TimeoutError("Notebook exceeded bounded wait")


def prepare(state: dict, proxy: str, state_path: Path) -> None:
    if "lakehouse_id" not in state:
        state["lakehouse_id"] = create_item(
            state, "lakehouses", "genius_lakehouse", proxy)["id"]
        save(state_path, state)
    inputs = {}
    for name in ("courses.synthetic.json", "learners.synthetic.json",
                 "recommendation-policy.synthetic.json"):
        data = (ROOT / "data" / name).read_bytes()
        inputs[name] = hashlib.sha256(data).hexdigest()
    code_files = (
        "azdemy_recommendations/__init__.py", "azdemy_recommendations/eligibility.py",
        "azdemy_recommendations/reasons.py", "azdemy_recommendations/recommender.py",
        "azdemy_recommendations/spark_job.py",
    )
    code_hash = hashlib.sha256()
    for name in (*code_files, "fabric/train.ipynb", "fabric/batch.ipynb"):
        code_hash.update(name.encode("utf-8"))
        code_hash.update(ROOT.joinpath(*name.split("/")).read_bytes())
    code_version = code_hash.hexdigest()
    input_key = hashlib.sha256(json.dumps(inputs, sort_keys=True).encode("utf-8")).hexdigest()[:20]
    state.update(input_hashes=inputs, code_version=code_version,
                 input_path=f"inputs/{input_key}", code_path=f"code/{code_version}",
                 training_key=f"train-{input_key}-{code_version[:12]}")
    save(state_path, state)
    for name in inputs:
        put_file(state, f"{state['input_path']}/{name}", (ROOT / "data" / name).read_bytes(), proxy)
    for name in code_files:
        put_file(state, f"{state['code_path']}/{name}",
                 ROOT.joinpath(*name.split("/")).read_bytes(), proxy)


def publish(source: Path, state: dict, proxy: str, state_path: Path, bootstrap: bool = False,
            rollback: bool = False) -> None:
    store, _ = validate_directory(source)
    expected_generation = "mock-fabric-static-snapshot" if bootstrap else "fabric-spark-content-v1"
    if not rollback and store.snapshot.generation != expected_generation:
        raise ValueError("The actual Fabric workflow cannot publish a mock release")
    if rollback:
        print(f"Explicit operator rollback: {store.snapshot.data_version}", flush=True)
    scm = "https://geniusmda53gutapi.scm.azurewebsites.net"
    remote = f"{scm}/api/vfs/data/genius-recommendations"
    status, _, data = request("GET", remote + "/active.json", ARM, proxy=proxy, allow_status=(404,))
    previous = json.loads(data)["version"] if status == 200 else None
    if bootstrap and previous is not None:
        raise ValueError("Legacy bootstrap is allowed only before the first published release")
    request_id = "publish-" + uuid4().hex
    archive = io.BytesIO()
    with ZipFile(archive, "w", ZIP_DEFLATED) as output:
        for name in ("manifest.json", "courses.synthetic.json", "learners.synthetic.json",
                     "recommendations.synthetic.json"):
            output.write(source / name, name)
    request("PUT", f"{scm}/api/zip/data/genius-recommendations/incoming/{request_id}/",
            ARM, archive.getvalue(), proxy, "application/zip")
    pending = {"request_id": request_id, "version": store.snapshot.data_version,
               "expected_current": previous, "incoming": request_id}
    request("PUT", remote + "/pending.json", ARM, json.dumps(pending).encode("utf-8"), proxy,
            headers={"If-Match": "*"})
    _, _, settings_data = request("POST", APP_RESOURCE + "/config/appsettings/list?api-version=2023-12-01",
                                   ARM, b"")
    settings = json.loads(settings_data)
    if settings["properties"].get("GENIUS_PUBLICATION_ROOT") != "/home/data/genius-recommendations":
        settings["properties"]["GENIUS_PUBLICATION_ROOT"] = "/home/data/genius-recommendations"
        request("PUT", APP_RESOURCE + "/config/appsettings?api-version=2023-12-01",
                ARM, json.dumps({"properties": settings["properties"]}).encode("utf-8"))
    state["pending_publication"] = {
        **pending, "result_key": "bootstrap_publication" if bootstrap else "publication"}
    save(state_path, state)
    print(json.dumps({"status": "pending", "request_id": request_id,
                      "version": store.snapshot.data_version, "requires_restart_and_confirmation": True}),
          flush=True)


def confirm_publication(state: dict, proxy: str, state_path: Path) -> None:
    pending = state["pending_publication"]
    request_id = safe_name(pending["request_id"])
    remote = ("https://geniusmda53gutapi.scm.azurewebsites.net"
              "/api/vfs/data/genius-recommendations")
    wake = subprocess.run([
        "curl.exe", "--proxy", proxy, "--silent", "--show-error",
        "--connect-timeout", "20", "--max-time", "90", "--output", os.devnull,
        "--write-out", "%{http_code}",
        "https://geniusmda53gutapi.azurewebsites.net/recommendations/me",
    ], check=True, capture_output=True, text=True)
    print(f"Unauthenticated private API wake-up HTTP {wake.stdout.strip()}", flush=True)
    if wake.stdout.strip() not in {"401", "502", "503"}:
        raise RuntimeError(f"Unexpected API wake-up status: {wake.stdout.strip()}")
    started = time.monotonic()
    for _ in range(30):
        check_deadline(state)
        if time.monotonic() - started >= 180:
            break
        status, _, data = request(
            "GET", remote + f"/requests/{request_id}.json", ARM, proxy=proxy, allow_status=(404,))
        if status == 200:
            result = json.loads(data)
            if (result.get("request_id") != request_id
                    or result.get("version") != pending["version"]):
                raise RuntimeError("API publication receipt does not match the submitted request")
            state[pending["result_key"]] = result
            save(state_path, state)
            if result["status"] != "completed":
                raise RuntimeError(f"Server rejected snapshot activation: {result}")
            print(json.dumps(result), flush=True)
            return
        time.sleep(5)
    raise TimeoutError("API did not confirm pending publication")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=[
        "start", "stop", "pause", "workspace", "deny", "prepare", "train", "batch", "export",
        "publish", "bootstrap", "rollback", "confirm"])
    parser.add_argument("--state", required=True, type=Path)
    parser.add_argument("--proxy", default="socks5h://127.0.0.1:1080")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--auth-cli", choices=["az", "azd"], default="az")
    parser.add_argument("--new-batch", action="store_true")
    parser.add_argument("--session-window", action="store_true")
    args = parser.parse_args()
    configure_auth_cli(args.auth_cli)
    if args.new_batch and args.stage != "batch":
        raise ValueError("--new-batch is valid only for an actual batch execution")
    if args.session_window and args.stage != "start":
        raise ValueError("--session-window requires an explicitly approved compute start")
    state = json.loads(args.state.read_text(encoding="utf-8")) if args.state.exists() else {}
    if args.stage not in {"stop", "pause"} and not (args.stage == "start" and args.session_window):
        check_deadline(state)
    if args.stage == "start":
        start_compute(state, args.state, session_window=args.session_window)
    elif args.stage == "stop":
        stop_compute(state, args.state)
    elif args.stage == "pause":
        stop_compute(state, args.state, capacity_only=True)
    elif args.stage == "workspace":
        if "workspace_id" in state:
            raise ValueError("State already contains a workspace; refusing to create another")
        _, _, existing = json_request("GET", "https://api.fabric.microsoft.com/v1/workspaces")
        if any(w["displayName"] == "ws-genius-rec-demo" for w in existing["value"]):
            raise ValueError("Workspace name already exists; inspect ownership before reusing")
        _, _, created = json_request("POST", "https://api.fabric.microsoft.com/v1/workspaces", {
            "displayName": "ws-genius-rec-demo", "capacityId": CAPACITY_ID,
            "description": "azdemy-rec-demo synthetic-only private recommendation pipeline",
        })
        state.update(workspace_id=created["id"], capacity_id=CAPACITY_ID)
    elif args.stage == "deny":
        _, _, policy = json_request("GET",
            f"https://api.fabric.microsoft.com/v1/workspaces/{state['workspace_id']}/networking/communicationPolicy")
        policy["inbound"] = {"publicAccessRules": {"defaultAction": "Deny"}}
        json_request("PUT",
            f"https://api.fabric.microsoft.com/v1/workspaces/{state['workspace_id']}/networking/communicationPolicy",
            policy)
    elif args.stage == "prepare":
        prepare(state, args.proxy, args.state)
    elif args.stage in {"train", "batch"}:
        config = {k: state[k] for k in (
            "workspace_id", "lakehouse_id", "input_hashes", "input_path", "code_path",
            "code_version", "training_key")}
        if args.stage == "batch":
            model = state["trained_model"]
            if not model.get("model_version") or not model.get("mlflow_run_id"):
                raise ValueError("A specific registered model is required")
            if args.new_batch:
                state["batch_key"] = uuid4().hex[:20]
                state["as_of"] = datetime.now(timezone.utc).isoformat()
            else:
                state.setdefault("batch_key", uuid4().hex[:20])
                state.setdefault("as_of", datetime.now(timezone.utc).isoformat())
            config.update(approved_model=model, batch_key=state["batch_key"], as_of=state["as_of"])
        save(args.state, state)
        execution = run_notebook(state, args.stage, config, args.proxy, args.state)
        state[f"{args.stage}_execution"] = execution
        if args.stage == "train":
            state["trained_model"] = json.loads(get_file(
                state, f"control/{state['training_key']}/trained-model.json", args.proxy))
        else:
            state["batch_result"] = json.loads(get_file(
                state, f"batches/{state['batch_key']}/_SUCCESS", args.proxy))
    elif args.stage == "export":
        if args.output is None:
            raise ValueError("--output is required for export")
        args.output.mkdir(parents=True, exist_ok=True)
        for name in ("manifest.json", "courses.synthetic.json", "learners.synthetic.json",
                     "recommendations.synthetic.json"):
            (args.output / name).write_bytes(get_file(
                state, f"{state['batch_result']['export']}/{name}", args.proxy))
        validate_directory(args.output)
    elif args.stage == "confirm":
        confirm_publication(state, args.proxy, args.state)
    elif args.stage == "bootstrap":
        from tempfile import TemporaryDirectory
        with TemporaryDirectory(prefix="azdemy-legacy-bootstrap-") as directory:
            source = Path(directory)
            for name in ("courses.synthetic.json", "learners.synthetic.json",
                         "recommendations.synthetic.json"):
                _, _, data = request("GET",
                    "https://geniusmda53gutapi.scm.azurewebsites.net/api/vfs/site/wwwroot/data/" + name,
                    ARM, proxy=args.proxy)
                (source / name).write_bytes(data)
            write_manifest(source)
            publish(source, state, args.proxy, args.state, bootstrap=True)
    elif args.stage == "rollback":
        from tempfile import TemporaryDirectory
        remote = ("https://geniusmda53gutapi.scm.azurewebsites.net/api/vfs"
                  "/data/genius-recommendations/")
        _, _, data = request("GET", remote + "active.json", ARM, proxy=args.proxy)
        previous = json.loads(data).get("previous")
        if previous is None:
            raise ValueError("No previous normal release exists for rollback")
        safe_name(previous)
        with TemporaryDirectory(prefix="azdemy-rollback-") as directory:
            source = Path(directory)
            for name in ("manifest.json", "courses.synthetic.json", "learners.synthetic.json",
                         "recommendations.synthetic.json"):
                _, _, data = request("GET", remote + f"releases/{previous}/{name}",
                                     ARM, proxy=args.proxy)
                (source / name).write_bytes(data)
            publish(source, state, args.proxy, args.state, rollback=True)
    else:
        if args.output is None:
            raise ValueError("--output must point to the validated export")
        publish(args.output, state, args.proxy, args.state)
    save(args.state, state)
    print(json.dumps({"stage": args.stage, "workspace_id": state.get("workspace_id"),
                      "deadline": state.get("deadline")}), flush=True)


if __name__ == "__main__":
    main()
