import argparse
import base64
import hashlib
import json
import re
from pathlib import Path
from tempfile import TemporaryDirectory


def main() -> None:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--config-base64", required=True)
    args, _ = parser.parse_known_args()
    config = json.loads(base64.b64decode(args.config_base64, validate=True))
    if (re.fullmatch(r"[a-f0-9]{64}", config["code_version"]) is None
            or config["code_path"] != "code/" + config["code_version"]):
        raise ValueError("Invalid versioned Spark application path")
    from pyspark.sql import SparkSession
    spark = SparkSession.builder.getOrCreate()
    filesystem = spark._jvm.org.apache.hadoop.fs.FileSystem.get(spark._jsc.hadoopConfiguration())
    with TemporaryDirectory(prefix="azdemy-spark-app-") as directory:
        application = Path(directory) / "azdemy_recommendations.zip"
        remote = spark._jvm.org.apache.hadoop.fs.Path(
            "Files/" + config["code_path"] + "/azdemy_recommendations.zip")
        local = spark._jvm.org.apache.hadoop.fs.Path(application.as_uri())
        filesystem.copyToLocalFile(False, remote, local, True)
        if hashlib.sha256(application.read_bytes()).hexdigest() != config["package_sha256"]:
            raise ValueError("Spark application package checksum mismatch")
        spark.sparkContext.addPyFile(str(application))
        from azdemy_recommendations.batch_entrypoint import main as run
        run()


if __name__ == "__main__":
    main()
