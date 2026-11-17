"""Discover recordings at request time; the bucket itself remains private."""

import json
import logging
import os
import re
from pathlib import PurePosixPath
from functools import lru_cache
from urllib.parse import quote


AUDIO_EXTENSIONS = {".m4a", ".mp3", ".wav", ".ogg", ".flac", ".aac", ".opus"}
logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def s3_client():
    import boto3  # Supplied by the AWS Lambda Python runtime.
    return boto3.client("s3")


def track_from_object(item):
    key = item["Key"]
    path = PurePosixPath(key)
    if path.suffix.lower() not in AUDIO_EXTENSIONS or item["Size"] == 0:
        return None
    title = re.sub(r"[-_]+", " ", path.stem).strip().title()
    title = re.sub(r"\s+Take\s+(\d+)$", r" — Take \1", title)
    # Bind the URL to an actual S3 version, so CDN caching cannot mix an
    # overwritten recording's old audio ranges with its new contents.
    version = item.get("VersionId")
    if version:
        query = f"versionId={quote(version, safe='')}"
    else:  # Local preview files have no S3 version ID.
        etag = item["ETag"].strip('"')
        query = f"v={quote(etag, safe='')}"
    return {
        "id": key,
        "title": title,
        "filename": path.name,
        "url": f"/{quote(key, safe='/')}?{query}",
        "updated": item["LastModified"].isoformat(),
        "bytes": item["Size"],
    }


def response(status, body):
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json", "Cache-Control": "public, max-age=15, s-maxage=15" if status == 200 else "no-store"},
        "body": json.dumps(body, ensure_ascii=False),
    }


def handler(event, context):
    try:
        s3 = s3_client()
        pages = s3.get_paginator("list_object_versions").paginate(
            Bucket=os.environ["RECORDINGS_BUCKET"], Prefix="tracks/",
        )
        tracks = []
        for page in pages:
            # A deletion makes all previous versions non-latest. Never expose
            # old versions or resurrect a track behind a delete marker.
            for item in page.get("Versions", []):
                if not item.get("IsLatest"):
                    continue
                track = track_from_object(item)
                if track:
                    tracks.append(track)
        # Stable order, independent of later overwrites to an existing song.
        tracks.sort(key=lambda track: (track["title"].casefold(), track["id"]))
        return response(200, {"tracks": tracks})
    except Exception:
        logger.exception("Could not list demo recordings")
        return response(503, {"error": "Recordings are temporarily unavailable."})
