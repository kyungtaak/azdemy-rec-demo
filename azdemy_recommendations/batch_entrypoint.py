import argparse
import base64
import json
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse
from uuid import UUID

from .spark_job import batch


def decode_request(encoded: str, batch_key: str, as_of: str) -> dict:
    config = json.loads(base64.b64decode(encoded, validate=True))
    config["workspace_id"] = str(UUID(config["workspace_id"]))
    config["lakehouse_id"] = str(UUID(config["lakehouse_id"]))
    config["batch_key"] = str(UUID(batch_key))
    timestamp = datetime.fromisoformat(as_of)
    if timestamp.utcoffset() is None:
        raise ValueError("Spark batch as_of must include a timezone")
    config["as_of"] = timestamp.isoformat()
    return config


def default_filesystem(spark):
    return spark._jvm.org.apache.hadoop.fs.FileSystem.get(spark._jsc.hadoopConfiguration())


def runtime_context(config: dict, filesystem, application_id: str) -> dict:
    root = urlparse(str(filesystem.getUri()))
    working = urlparse(str(filesystem.getWorkingDirectory()))
    if (root.scheme != "abfss" or working.scheme != "abfss"
            or root.netloc != working.netloc
            or root.hostname != "onelake.dfs.fabric.microsoft.com"
            or root.query or working.query or working.fragment):
        raise ValueError("Spark filesystem is not the approved secure OneLake binding")
    workspace = str(UUID(root.username))
    lakehouse = str(UUID(working.path.strip("/")))
    if (workspace != config["workspace_id"] or lakehouse != config["lakehouse_id"]
            or not application_id):
        raise ValueError("Spark runtime does not match the approved workspace and Lakehouse")
    return {"currentWorkspaceId": workspace, "defaultLakehouseId": lakehouse,
            "activityId": application_id}


def run_batch(config: dict, spark, utilities) -> dict:
    filesystem = default_filesystem(spark)
    context = runtime_context(config, filesystem, spark.sparkContext.applicationId)
    mount_point = f"/azdemy-{config['batch_key']}"
    if not utilities.fs.mount(str(filesystem.getWorkingDirectory()), mount_point):
        raise RuntimeError("Keyless OneLake filesystem mount failed")
    try:
        files_root = Path(utilities.fs.getMountPath(mount_point)) / "Files"
        return batch(config, spark, context, files_root=files_root)
    finally:
        utilities.fs.unmount(mount_point)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config-base64", required=True)
    parser.add_argument("--batch-key", required=True)
    parser.add_argument("--as-of", required=True)
    args = parser.parse_args()
    config = decode_request(args.config_base64, args.batch_key, args.as_of)
    import notebookutils
    from pyspark.sql import SparkSession
    spark = SparkSession.builder.getOrCreate()
    result = run_batch(config, spark, notebookutils)
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
