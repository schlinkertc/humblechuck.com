"""Run from GitHub Actions after deployment, using its existing AWS session.

A permanent marker keeps future deploys from restoring a removed demo or
overwriting a replacement. Conditional writes also protect against races.
"""

import json
from pathlib import Path
import subprocess
import tempfile


ACCOUNT = "559681045665"
REGION = "us-east-1"
BUCKET = f"humblechuck-recordings-{ACCOUNT}-{REGION}"
KEY = "tracks/peace-i-seek-take-6.m4a"
MARKER = "setup/initial-recording-v1"
SOURCE = Path(__file__).resolve().parents[1] / "recordings" / "seed" / "peace-i-seek-take-6.m4a"


def aws(*args):
    return subprocess.run(
        ["aws", *args, "--region", REGION, "--output", "json"],
        capture_output=True, text=True, check=False,
    )


def require_success(result):
    if result.returncode:
        raise RuntimeError(result.stderr.strip())
    return json.loads(result.stdout or "{}")


def exists(key):
    result = aws("s3api", "head-object", "--bucket", BUCKET, "--key", key)
    if result.returncode == 0:
        return True
    if "(404)" in result.stderr or "(NoSuchKey)" in result.stderr:
        return False
    require_success(result)


def put_once(key, path, content_type):
    result = aws(
        "s3api", "put-object", "--bucket", BUCKET, "--key", key,
        "--body", str(path), "--content-type", content_type,
        "--cache-control", "no-store", "--if-none-match", "*",
    )
    if result.returncode and ("(PreconditionFailed)" in result.stderr or "(412)" in result.stderr):
        return
    require_success(result)


def main():
    identity = require_success(aws("sts", "get-caller-identity"))
    if identity.get("Account") != ACCOUNT:
        raise RuntimeError(f"Refusing to upload outside personal AWS account {ACCOUNT}")
    if exists(MARKER):
        print("Initial demo setup already completed; recordings left untouched.")
        return
    if not exists(KEY):
        put_once(KEY, SOURCE, "audio/mp4")
    with tempfile.TemporaryDirectory() as directory:
        marker = Path(directory) / "initialized"
        marker.write_text("Initial demo setup completed. Do not delete this marker.\n")
        put_once(MARKER, marker, "text/plain")
    print(f"Initial demo ready: s3://{BUCKET}/{KEY}")


if __name__ == "__main__":
    main()
