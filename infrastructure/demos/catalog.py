"""Discover recordings at request time; the bucket itself remains private."""

import json
import logging
import os
import re
from pathlib import PurePosixPath
from urllib.parse import quote


AUDIO_EXTENSIONS = {".m4a", ".mp3", ".wav", ".ogg", ".flac", ".aac", ".opus"}
logger = logging.getLogger(__name__)


def track_from_object(item):
    key = item["Key"]
    path = PurePosixPath(key)
    if path.suffix.lower() not in AUDIO_EXTENSIONS or item["Size"] == 0:
        return None
    title = re.sub(r"[-_]+", " ", path.stem).strip().title()
    title = re.sub(r"\s+Take\s+(\d+)$", r" — Take \1", title)
    version = item["ETag"].strip('"')
    return {
        "id": key,
        "title": title,
        "filename": path.name,
        "url": f"/{quote(key, safe='/')}?v={quote(version, safe='')}",
        "updated": item["LastModified"].isoformat(),
        "bytes": item["Size"],
    }


def response(status, body):
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json", "Cache-Control": "no-store"},
        "body": json.dumps(body, ensure_ascii=False),
    }


def handler(event, context):
    import boto3  # Supplied by the AWS Lambda Python runtime.

    try:
        s3 = boto3.client("s3")
        pages = s3.get_paginator("list_objects_v2").paginate(
            Bucket=os.environ["RECORDINGS_BUCKET"], Prefix="tracks/",
        )
        tracks = []
        for page in pages:
            for item in page.get("Contents", []):
                track = track_from_object(item)
                if track:
                    tracks.append(track)
        # Stable order, independent of later overwrites to an existing song.
        tracks.sort(key=lambda track: (track["title"].casefold(), track["id"]))
        return response(200, {"tracks": tracks})
    except Exception:
        logger.exception("Could not list demo recordings")
        return response(503, {"error": "Recordings are temporarily unavailable."})
