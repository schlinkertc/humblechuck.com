from datetime import datetime, timezone
import json
import sys
from types import SimpleNamespace

from infrastructure.demos import catalog
from scripts import seed_recording
from site_builder.build import build


def audio(key="tracks/peace-i-seek-take-6.m4a", etag='"v1"', size=100):
    return {"Key": key, "Size": size, "ETag": etag, "LastModified": datetime(2026, 11, 16, tzinfo=timezone.utc)}


def fake_s3(monkeypatch, pages):
    requests = []

    def paginate(**kwargs):
        requests.append(kwargs)
        return iter(pages)

    def get_paginator(name):
        assert name == "list_objects_v2"
        return SimpleNamespace(paginate=paginate)

    monkeypatch.setenv("RECORDINGS_BUCKET", "test-recordings")
    monkeypatch.setitem(sys.modules, "boto3", SimpleNamespace(client=lambda name: SimpleNamespace(get_paginator=get_paginator)))
    return requests


def test_catalog_paginates_filters_and_encodes_tracks(monkeypatch):
    requests = fake_s3(monkeypatch, [
        {"Contents": [audio(), audio("tracks/notes.txt"), audio("tracks/empty.mp3", size=0)]},
        {"Contents": [audio("tracks/a song #1.MP3")]},
    ])
    result = catalog.handler({}, None)
    tracks = json.loads(result["body"])["tracks"]
    assert result["statusCode"] == 200
    assert result["headers"]["Cache-Control"] == "no-store"
    assert requests == [{"Bucket": "test-recordings", "Prefix": "tracks/"}]
    assert len(tracks) == 2
    assert tracks[0]["url"] == "/tracks/a%20song%20%231.MP3?v=v1"
    assert tracks[1]["title"] == "Peace I Seek — Take 6"


def test_catalog_sees_uploads_overwrites_and_deletions_without_build(monkeypatch):
    pages = [{"Contents": [audio()]}]
    fake_s3(monkeypatch, pages)
    original = json.loads(catalog.handler({}, None)["body"])["tracks"]
    pages[0]["Contents"] = [audio(etag='"v2"'), audio("tracks/new-song.mp3")]
    updated = json.loads(catalog.handler({}, None)["body"])["tracks"]
    assert len(updated) == 2
    assert next(track for track in updated if track["id"] == original[0]["id"])["url"] != original[0]["url"]
    pages[0]["Contents"] = []
    assert json.loads(catalog.handler({}, None)["body"]) == {"tracks": []}


def test_catalog_failure_returns_retryable_error_without_internal_details(monkeypatch):
    def fail(name):
        raise RuntimeError("secret-bucket-name")
    monkeypatch.setitem(sys.modules, "boto3", SimpleNamespace(client=fail))
    result = catalog.handler({}, None)
    assert result["statusCode"] == 503
    assert "secret-bucket-name" not in result["body"]


def test_demos_build_has_player_and_no_bundled_recordings():
    output = build()
    demos = (output / "demos" / "index.html").read_text()
    assert "<audio controls" in demos
    assert 'src="/demos.js"' in demos
    assert "$name" not in demos
    assert "https://humblechuck.com/demos" in (output / "sitemap.xml").read_text()
    assert 'href="/demos"' in (output / "music" / "index.html").read_text()
    assert not list(output.rglob("*.m4a"))


def test_seed_once_never_overwrites_or_resurrects_deleted_recording(monkeypatch):
    objects = {}
    writes = []

    def aws(*args):
        if args[0] == "sts":
            return SimpleNamespace(returncode=0, stdout=json.dumps({"Account": seed_recording.ACCOUNT}), stderr="")
        key = args[args.index("--key") + 1]
        if args[1] == "head-object":
            return SimpleNamespace(returncode=0 if key in objects else 1, stdout="{}", stderr="" if key in objects else "An error occurred (404)")
        assert args[1] == "put-object"
        assert args[args.index("--if-none-match") + 1] == "*"
        objects[key] = "initial"
        writes.append(key)
        return SimpleNamespace(returncode=0, stdout="{}", stderr="")

    monkeypatch.setattr(seed_recording, "aws", aws)
    seed_recording.main()
    assert writes == [seed_recording.KEY, seed_recording.MARKER]
    objects[seed_recording.KEY] = "user replacement"
    seed_recording.main()
    assert objects[seed_recording.KEY] == "user replacement"
    del objects[seed_recording.KEY]
    seed_recording.main()
    assert seed_recording.KEY not in objects
    assert len(writes) == 2


def test_seed_refuses_wrong_account(monkeypatch):
    import pytest
    monkeypatch.setattr(seed_recording, "aws", lambda *args: SimpleNamespace(returncode=0, stdout='{"Account":"wrong"}', stderr=""))
    with pytest.raises(RuntimeError, match="Refusing to upload"):
        seed_recording.main()
