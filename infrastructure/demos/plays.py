"""Anonymous qualified plays and counters; raw events are never publicly listed."""

import base64
from datetime import datetime, timezone
from functools import lru_cache
import json
import logging
import math
import os
from pathlib import PurePosixPath
import re
from uuid import UUID


logger = logging.getLogger(__name__)
AUDIO_EXTENSIONS = {".m4a", ".mp3", ".wav", ".ogg", ".flac", ".aac", ".opus"}
FIELDS = {"event_id", "demo_id", "listened_seconds", "duration_seconds", "recording_version", "page", "referrer_host"}


@lru_cache(maxsize=2)
def client(service):
    import boto3  # Included in the Lambda runtime.
    return boto3.client(service)


def response(status, body):
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json", "Cache-Control": "no-store"},
        "body": json.dumps(body),
    }


def demo_key(value):
    if (not isinstance(value, str) or not value.startswith("tracks/")
            or len(value.encode("utf-8")) > 1024
            or any(part in {"", ".", ".."} for part in value.split("/"))
            or any(ord(char) < 32 for char in value)
            or PurePosixPath(value).suffix.lower() not in AUDIO_EXTENSIONS):
        raise ValueError("Invalid demo_id.")
    return value


def seconds(value, minimum):
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not minimum <= value <= 86400 or not math.isfinite(value)):
        raise ValueError("Invalid listening duration.")
    return {"N": str(round(value, 2))}


def parse_play(event):
    headers = {key.lower(): value for key, value in event.get("headers", {}).items()}
    if headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
        raise ValueError("Expected application/json.")
    body = event.get("body") or ""
    if len(body) > 6000:
        raise ValueError("Play event is too large.")
    if event.get("isBase64Encoded"):
        body = base64.b64decode(body, validate=True).decode("utf-8")
    if len(body.encode("utf-8")) > 4096:
        raise ValueError("Play event is too large.")
    data = json.loads(body)
    if not isinstance(data, dict) or set(data) - FIELDS:
        raise ValueError("Invalid play event fields.")
    key = demo_key(data.get("demo_id"))
    event_id = data.get("event_id")
    if not isinstance(event_id, str):
        raise ValueError("Invalid event_id.")
    parsed_id = UUID(event_id)
    if parsed_id.version != 4 or str(parsed_id) != event_id:
        raise ValueError("Invalid event_id.")
    listened = seconds(data.get("listened_seconds"), 10)
    page = data.get("page")
    if page not in {"/demos", "/demos/"}:
        raise ValueError("Invalid page.")
    item = {
        "pk": {"S": f"DEMO#{key}"}, "sk": {"S": f"PLAY#{event_id}"},
        "event_id": {"S": event_id}, "demo_id": {"S": key},
        "event_type": {"S": "qualified_play"}, "schema_version": {"N": "1"},
        "listened_seconds": listened, "page": {"S": "/demos"},
    }
    if "duration_seconds" in data:
        item["duration_seconds"] = seconds(data["duration_seconds"], 0.01)
    if "referrer_host" in data:
        host = data["referrer_host"]
        if not isinstance(host, str) or not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?", host):
            raise ValueError("Invalid referrer_host.")
        item["referrer_host"] = {"S": host}
    version = data.get("recording_version")
    if version is not None and (not isinstance(version, str) or not 1 <= len(version) <= 1024
                                or any(ord(char) < 32 for char in version)):
        raise ValueError("Invalid recording_version.")
    return item, version


def get_total(db, table, key):
    result = db.get_item(
        TableName=table, Key={"pk": {"S": f"DEMO#{key}"}, "sk": {"S": "TOTAL"}},
        ConsistentRead=True, ProjectionExpression="plays",
    )
    return int(result.get("Item", {}).get("plays", {"N": "0"})["N"])


def record_play(db, table, item):
    # The event key is independent of the timestamp/day: retries after midnight
    # still fail this conditional put, leaving BOTH counters unchanged.
    now = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    item["played_at"] = {"S": now}
    writes = [{"Put": {"TableName": table, "Item": item, "ConditionExpression": "attribute_not_exists(pk)"}}]
    for sort_key in ("TOTAL", f"DAY#{now[:10]}"):
        writes.append({"Update": {
            "TableName": table, "Key": {"pk": item["pk"], "sk": {"S": sort_key}},
            "UpdateExpression": "ADD plays :one", "ExpressionAttributeValues": {":one": {"N": "1"}},
        }})
    try:
        db.transact_write_items(TransactItems=writes)
        return True
    except Exception as error:
        details = getattr(error, "response", {})
        reasons = details.get("CancellationReasons", [])
        if (details.get("Error", {}).get("Code") == "TransactionCanceledException"
                and reasons and reasons[0].get("Code") == "ConditionalCheckFailed"):
            return False
        raise


def handler(event, context):
    method = event.get("requestContext", {}).get("http", {}).get("method")
    if method not in {"GET", "POST"}:
        return response(405, {"error": "Method not allowed."})
    try:
        if method == "GET":
            key = demo_key((event.get("queryStringParameters") or {}).get("demo_id"))
            item = None
        else:
            item, version = parse_play(event)
            key = item["demo_id"]["S"]
    except (ValueError, TypeError, UnicodeError):
        return response(400, {"error": "Invalid play event or demo ID."})

    try:
        db = client("dynamodb")
        table = os.environ["PLAY_EVENTS_TABLE"]
        recorded = None
        if item is not None:
            args = {"Bucket": os.environ["RECORDINGS_BUCKET"], "Key": key}
            if version:
                args["VersionId"] = version
            try:
                recording = client("s3").head_object(**args)
            except Exception as error:
                if getattr(error, "response", {}).get("Error", {}).get("Code") in {"404", "403", "NoSuchKey", "NoSuchVersion", "NotFound", "AccessDenied"}:
                    return response(404, {"error": "Recording not found."})
                raise
            if recording["ContentLength"] == 0:
                return response(404, {"error": "Recording not found."})
            if recording.get("VersionId"):
                item["recording_version"] = {"S": recording["VersionId"]}
            recorded = record_play(db, table, item)
        body = {"demo_id": key, "plays": get_total(db, table, key)}
        if recorded is not None:
            body["recorded"] = recorded
        return response(200, body)
    except Exception:
        # Never log the incoming event, IP address, full referrer, or user agent.
        logger.exception("Could not read or record a demo play")
        return response(503, {"error": "Play counts are temporarily unavailable."})
