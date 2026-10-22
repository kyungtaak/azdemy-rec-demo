import argparse
import json
from pathlib import Path
from uuid import UUID

from api.main import create_app


def definition(api_client_id: str) -> dict:
    audience = f"api://{UUID(api_client_id)}"
    return {
        "kind": "prompt",
        "model": "gpt-5.6-terra",
        "instructions": Path(__file__).with_name("instructions.txt").read_text(encoding="utf-8"),
        "tools": [{
            "type": "openapi",
            "openapi": {
                "name": "education",
                "description": "Read-only synthetic education queries for the fixed authorized learner.",
                "spec": create_app().openapi(),
                "auth": {
                    "type": "managed_identity",
                    "security_scheme": {"audience": audience},
                },
            },
        }],
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-client-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    arguments.output.write_text(
        json.dumps({"definition": definition(arguments.api_client_id)}, ensure_ascii=False, indent=2),
        encoding="utf-8")
