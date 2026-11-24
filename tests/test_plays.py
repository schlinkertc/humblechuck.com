import base64
from copy import deepcopy
from datetime import datetime, timezone
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest

from infrastructure.demos import plays


KEY = "tracks/peace-i-seek-take-6.m4a"


class AwsError(Exception):
    def __init__(self, code, reasons=None):
        self.response = {"Error": {"Code": code}, "CancellationReasons": reasons or []}


class Database:
    """In-memory atomic writes to exercise duplicates, failures, and totals."""
    def __init__(self):
        self.items = {}
        self.writes = []
        self.failure = None

    def transact_write_items(self, TransactItems):
        self.writes.append(deepcopy(TransactItems))
        if self.failure:
            raise self.failure
        put = TransactItems[0]["Put"]
        item = put["Item"]
        key = (item["pk"]["S"], item["sk"]["S"])
        assert put["ConditionExpression"] == "attribute_not_exists(pk)"
        if key in self.items:
            raise AwsError("TransactionCanceledException", [{"Code": "ConditionalCheckFailed"}])
        pending = {**self.items, key: deepcopy(item)}
        for write in TransactItems[1:]:
            update = write["Update"]
            assert update["TableName"] == put["TableName"]
            assert update["UpdateExpression"] == "ADD plays :one"
            assert update["ExpressionAttributeValues"] == {":one": {"N": "1"}}
            key = (update["Key"]["pk"]["S"], update["Key"]["sk"]["S"])
            previous = int(pending.get(key, {}).get("plays", {"N": "0"})["N"])
            pending[key] = {**update["Key"], "plays": {"N": str(previous + 1)}}
        self.items = pending

    def get_item(self, **kwargs):
        assert kwargs["ConsistentRead"] is True
        key = kwargs["Key"]
        return {"Item": self.items.get((key["pk"]["S"], key["sk"]["S"]), {})}


@pytest.fixture
def storage(monkeypatch):
    db = Database()
    requests = []

    def head_object(**kwargs):
        requests.append(kwargs)
        return {"ContentLength": 1000, "VersionId": kwargs.get("VersionId", "latest")}

    monkeypatch.setattr(plays, "client", lambda service: db if service == "dynamodb" else SimpleNamespace(head_object=head_object))
    monkeypatch.setenv("PLAY_EVENTS_TABLE", "test-plays")
    monkeypatch.setenv("RECORDINGS_BUCKET", "test-recordings")
    return db, requests


def payload(**kwargs):
    return {"event_id": str(uuid4()), "demo_id": KEY, "listened_seconds": 10.25,
            "duration_seconds": 120, "recording_version": "take-version",
            "page": "/demos", "referrer_host": "instagram.com", **kwargs}


def request(data=None, method="POST"):
    return {"requestContext": {"http": {"method": method}},
            "headers": {"Content-Type": "application/json; charset=utf-8"},
            "queryStringParameters": {"demo_id": KEY},
            "body": json.dumps(data if data is not None else payload())}


def test_records_server_timestamp_attributes_and_both_counters(storage):
    db, heads = storage
    result = plays.handler(request(), None)
    assert result["statusCode"] == 200
    assert json.loads(result["body"])["plays"] == 1
    assert result["headers"]["Cache-Control"] == "no-store"
    event = next(item for (pk, sk), item in db.items.items() if sk.startswith("PLAY#"))
    timestamp = datetime.fromisoformat(event["played_at"]["S"].replace("Z", "+00:00"))
    assert abs((datetime.now(timezone.utc) - timestamp).total_seconds()) < 5
    assert event["demo_id"] == {"S": KEY}
    assert event["recording_version"] == {"S": "take-version"}
    assert event["referrer_host"] == {"S": "instagram.com"}
    assert event["event_type"] == {"S": "qualified_play"}
    assert event["listened_seconds"] == {"N": "10.25"}
    assert heads == [{"Bucket": "test-recordings", "Key": KEY, "VersionId": "take-version"}]
    assert db.items[(f"DEMO#{KEY}", "TOTAL")]["plays"] == {"N": "1"}
    assert db.items[(f"DEMO#{KEY}", f"DAY#{timestamp.date()}")]["plays"] == {"N": "1"}


def test_retry_is_idempotent_even_on_another_day(storage, monkeypatch):
    db, _ = storage
    event = request()
    assert json.loads(plays.handler(event, None)["body"])["recorded"] is True
    saved = deepcopy(db.items)
    monkeypatch.setattr(plays, "datetime", SimpleNamespace(now=lambda tz: datetime(2030, 1, 1, tzinfo=tz)))
    retried = json.loads(plays.handler(event, None)["body"])
    assert retried == {"demo_id": KEY, "plays": 1, "recorded": False}
    assert db.items == saved
    second = json.loads(plays.handler(request(), None)["body"])
    assert second["plays"] == 2 and second["recorded"] is True


def test_get_exposes_only_total_and_never_raw_event_attributes(storage):
    db, heads = storage
    assert json.loads(plays.handler(request(method="GET"), None)["body"]) == {"demo_id": KEY, "plays": 0}
    assert heads == []
    plays.handler(request(), None)
    result = plays.handler(request(method="GET"), None)
    assert json.loads(result["body"]) == {"demo_id": KEY, "plays": 1}


@pytest.mark.parametrize("changes", [
    {"demo_id": "private/secret.mp3"}, {"demo_id": "tracks/../secret.mp3"},
    {"demo_id": "tracks/notes.txt"}, {"demo_id": "tracks/" + "é" * 600 + ".mp3"},
    {"event_id": "not-an-id"}, {"listened_seconds": 9.99}, {"listened_seconds": True},
    {"listened_seconds": float("nan")}, {"listened_seconds": float("inf")},
    {"listened_seconds": 10 ** 1000},
    {"duration_seconds": -1}, {"referrer_host": "https://example.com/private?token=secret"},
    {"page": "/demos?email=private"}, {"recording_version": []},
    {"played_at": "2000-01-01T00:00:00Z"}, {"user_email": "private@example.com"},
])
def test_invalid_or_unapproved_attributes_do_not_touch_storage(storage, changes):
    db, heads = storage
    assert plays.handler(request(payload(**changes)), None)["statusCode"] == 400
    assert heads == [] and db.writes == []


@pytest.mark.parametrize("body", ["[]", "null", "{", "x" * 7000])
def test_invalid_json_and_oversized_bodies(storage, body):
    event = request()
    event["body"] = body
    assert plays.handler(event, None)["statusCode"] == 400


def test_base64_body_and_content_type(storage):
    event = request()
    event["body"] = base64.b64encode(event["body"].encode()).decode()
    event["isBase64Encoded"] = True
    assert plays.handler(event, None)["statusCode"] == 200
    event["body"] = "invalid base64!"
    assert plays.handler(event, None)["statusCode"] == 400
    event = request()
    event["headers"] = {"content-type": "text/plain"}
    assert plays.handler(event, None)["statusCode"] == 400


def test_missing_recording_does_not_increment(storage, monkeypatch):
    db, _ = storage
    def missing(**kwargs):
        raise AwsError("NoSuchKey")
    monkeypatch.setattr(plays, "client", lambda service: db if service == "dynamodb" else SimpleNamespace(head_object=missing))
    assert plays.handler(request(), None)["statusCode"] == 404
    assert db.items == {}


def test_transaction_failure_does_not_claim_a_play_or_expose_details(storage):
    db, _ = storage
    db.failure = AwsError("TransactionCanceledException", [{"Code": "TransactionConflict"}])
    result = plays.handler(request(), None)
    assert result["statusCode"] == 503
    assert "TransactionConflict" not in result["body"]
    assert db.items == {}


def test_rejects_other_http_methods_without_storage(storage):
    db, heads = storage
    assert plays.handler(request(method="DELETE"), None)["statusCode"] == 405
    assert heads == [] and db.items == {}
