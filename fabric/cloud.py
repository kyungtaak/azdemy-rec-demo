"""Small operator-only REST client; tokens remain in memory and curl standard input."""

import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlparse


_tokens: dict[str, tuple[float, str]] = {}
_auth_cli = "az"


def api_name() -> str:
    value = os.environ.get("AZDEMY_API_NAME", "")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,58}[A-Za-z0-9]", value):
        raise ValueError("AZDEMY_API_NAME must contain a deployed App Service name (2-60 characters)")
    return value


def configure_auth_cli(value: str) -> None:
    global _auth_cli
    if value not in {"az", "azd"}:
        raise ValueError("Unsupported operator authentication CLI")
    _auth_cli = value
    _tokens.clear()
    print(f"Operator authentication CLI: {value}", file=sys.stderr)


def token(audience: str) -> str:
    cached = _tokens.get(audience)
    if cached is None or time.monotonic() - cached[0] > 2400:
        az = shutil.which(_auth_cli)
        if az is None:
            raise RuntimeError(f"Authentication CLI is required: {_auth_cli}")
        arguments = ([az, "auth", "token", "--scope", audience.rstrip("/") + "/.default",
                      "--tenant-id", "da5c9e40-aa71-423d-98f0-e5e8174f322f", "--no-prompt"]
                     if _auth_cli == "azd" else [
                         az, "account", "get-access-token", "--resource", audience,
                         "--query", "accessToken", "-o", "tsv"])
        try:
            result = subprocess.run(
                arguments, check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as error:
            raise RuntimeError(f"Entra token acquisition failed: {error.stderr.strip()}") from error
        value = result.stdout.strip()
        if not value:
            raise RuntimeError("Empty Entra token")
        cached = (time.monotonic(), value)
        _tokens[audience] = cached
    return cached[1]


def request(method: str, url: str, audience: str, body: bytes | None = None,
            proxy: str | None = None, content_type: str = "application/json",
            headers: dict[str, str] | None = None,
            allow_status: tuple[int, ...] = ()) -> tuple[int, dict[str, str], bytes]:
    parsed = urlparse(url)
    allowed = (
        parsed.hostname in {"api.fabric.microsoft.com", "management.azure.com"}
        or (parsed.hostname or "").endswith(".fabric.microsoft.com")
        or (os.environ.get("AZDEMY_API_NAME") is not None
            and parsed.hostname == f"{api_name()}.scm.azurewebsites.net")
    )
    if parsed.scheme != "https" or not allowed:
        raise ValueError("Operator request target is not an approved HTTPS service")
    with TemporaryDirectory(prefix="azdemy-rest-") as temporary:
        root = Path(temporary)
        response, header_file = root / "response", root / "headers"
        command = [
            "curl.exe", "--config", "-", "--silent", "--show-error",
            "--connect-timeout", "20", "--max-time", "180",
            "--request", method, "--output", str(response),
            "--dump-header", str(header_file), "--write-out", "%{http_code}", url,
        ]
        if method == "HEAD":
            command.append("--head")
        if proxy:
            command += ["--proxy", proxy]
        if body is not None:
            payload = root / "body"
            payload.write_bytes(body)
            command += ["--data-binary", f"@{payload}", "--header", f"Content-Type: {content_type}"]
        for key, value in (headers or {}).items():
            command += ["--header", f"{key}: {value}"]
        config = f'header = "Authorization: Bearer {token(audience)}"\n'
        result = subprocess.run(command, input=config, capture_output=True, text=True, check=True)
        status = int(result.stdout)
        data = response.read_bytes()
        response_headers = {}
        for line in header_file.read_text(encoding="utf-8").splitlines():
            if ":" in line:
                key, value = line.split(":", 1)
                response_headers[key.lower()] = value.strip()
        if not 200 <= status < 300 and status not in allow_status:
            raise RuntimeError(f"{method} {parsed.path}: HTTP {status}: {data.decode('utf-8', errors='replace')[:2000]}")
        return status, response_headers, data


def json_request(method: str, url: str, body: dict | None = None,
                 proxy: str | None = None) -> tuple[int, dict[str, str], dict]:
    status, headers, data = request(
        method, url, "https://api.fabric.microsoft.com",
        json.dumps(body).encode("utf-8") if body is not None else None, proxy)
    return status, headers, json.loads(data) if data else {}


def workspace_endpoints(workspace_id: str) -> tuple[str, str]:
    from uuid import UUID
    compact = UUID(workspace_id).hex
    host = f"{compact}.z{compact[:2]}"
    return (f"https://{host}.w.api.fabric.microsoft.com",
            f"https://{host}.dfs.fabric.microsoft.com")
