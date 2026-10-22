"""Build a Linux CPython 3.12 deployment zip without using Windows binaries."""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZIP_DEFLATED, ZipFile


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="azdemy-api-package-") as directory:
        stage = Path(directory)
        shutil.copytree(root / "api", stage / "api", ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copytree(root / "azdemy_recommendations", stage / "azdemy_recommendations",
                        ignore=shutil.ignore_patterns("__pycache__"))
        (stage / "data").mkdir()
        for source in (root / "data").glob("*.synthetic.json"):
            shutil.copy2(source, stage / "data" / source.name)
        subprocess.run([
            sys.executable, "-m", "pip", "install", "--disable-pip-version-check",
            "--target", str(stage / ".python_packages" / "lib" / "site-packages"),
            "--platform", "manylinux2014_x86_64", "--python-version", "3.12",
            "--implementation", "cp", "--abi", "cp312", "--only-binary=:all:",
            "--no-compile", "-r", str(root / "requirements.txt"),
        ], check=True)
        with ZipFile(args.output, "w", ZIP_DEFLATED) as archive:
            for path in stage.rglob("*"):
                if path.is_file():
                    archive.write(path, path.relative_to(stage))
        with ZipFile(args.output) as archive:
            assert "api/main.py" in archive.namelist()
            assert archive.testzip() is None
    print(f"Deployment package: {args.output} ({args.output.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
