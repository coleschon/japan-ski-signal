import hashlib
import json
import os
from decimal import Decimal
from pathlib import Path
from typing import Any, Protocol


class Store(Protocol):
    def get(self, key: str, default: Any = None) -> Any: ...

    def put(self, key: str, value: Any) -> None: ...

    def scan(self, prefix: str) -> list[tuple[str, Any]]: ...

    def reserve_usage(self, key: str, remote_usage: int, cap: int) -> int | None: ...


def _json_default(value: Any) -> str:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if hasattr(value, "__dataclass_fields__"):
        from dataclasses import asdict

        return asdict(value)
    raise TypeError(f"Cannot serialize {type(value).__name__}")


def _to_dynamodb_value(value: Any) -> Any:
    return json.loads(json.dumps(value, default=str), parse_float=Decimal)


def _from_dynamodb_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        if value == value.to_integral_value():
            return int(value)
        return float(value)
    if isinstance(value, dict):
        return {key: _from_dynamodb_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_from_dynamodb_value(item) for item in value]
    return value


class LocalStore:
    def __init__(self, root: str | Path = ".localdata") -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        name = hashlib.sha256(key.encode()).hexdigest()
        return self.root / f"{name}.json"

    def get(self, key: str, default: Any = None) -> Any:
        path = self._path(key)
        if not path.exists():
            return default
        record = json.loads(path.read_text(encoding="utf-8"))
        return record["value"]

    def put(self, key: str, value: Any) -> None:
        record = {"key": key, "value": value}
        self._path(key).write_text(
            json.dumps(record, default=_json_default, ensure_ascii=False),
            encoding="utf-8",
        )

    def scan(self, prefix: str) -> list[tuple[str, Any]]:
        rows = []
        for path in self.root.glob("*.json"):
            record = json.loads(path.read_text(encoding="utf-8"))
            if record["key"].startswith(prefix):
                rows.append((record["key"], record["value"]))
        return rows

    def reserve_usage(self, key: str, remote_usage: int, cap: int) -> int | None:
        used = max(int(self.get(key, 0)), remote_usage)
        if used >= cap:
            return None
        self.put(key, used + 1)
        return used + 1


class DynamoStore:
    def __init__(self, table_name: str, region_name: str | None = None) -> None:
        import boto3

        self.table = boto3.resource("dynamodb", region_name=region_name).Table(table_name)

    def get(self, key: str, default: Any = None) -> Any:
        response = self.table.get_item(Key={"pk": key, "sk": "value"})
        item = response.get("Item")
        return default if item is None else _from_dynamodb_value(item["value"])

    def put(self, key: str, value: Any) -> None:
        self.table.put_item(
            Item={"pk": key, "sk": "value", "value": _to_dynamodb_value(value)}
        )

    def scan(self, prefix: str) -> list[tuple[str, Any]]:
        from boto3.dynamodb.conditions import Attr

        rows: list[tuple[str, Any]] = []
        kwargs: dict[str, Any] = {
            "FilterExpression": Attr("pk").begins_with(prefix) & Attr("sk").eq("value")
        }
        while True:
            response = self.table.scan(**kwargs)
            rows.extend(
                (item["pk"], _from_dynamodb_value(item["value"]))
                for item in response.get("Items", [])
            )
            if "LastEvaluatedKey" not in response:
                return rows
            kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]

    def reserve_usage(self, key: str, remote_usage: int, cap: int) -> int | None:
        from botocore.exceptions import ClientError

        item_key = {"pk": key, "sk": "value"}
        try:
            self.table.update_item(
                Key=item_key,
                UpdateExpression="SET #value = :remote",
                ConditionExpression="attribute_not_exists(#value) OR #value < :remote",
                ExpressionAttributeNames={"#value": "value"},
                ExpressionAttributeValues={":remote": remote_usage},
            )
        except ClientError as error:
            if error.response.get("Error", {}).get("Code") != "ConditionalCheckFailedException":
                raise
        try:
            response = self.table.update_item(
                Key=item_key,
                UpdateExpression="ADD #value :one",
                ConditionExpression="attribute_not_exists(#value) OR #value < :cap",
                ExpressionAttributeNames={"#value": "value"},
                ExpressionAttributeValues={":one": 1, ":cap": cap},
                ReturnValues="UPDATED_NEW",
            )
        except ClientError as error:
            if error.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
                return None
            raise
        return int(response["Attributes"]["value"])


class S3SnapshotWriter:
    def __init__(self, bucket: str, region_name: str | None = None) -> None:
        import boto3

        self.bucket = bucket
        self.client = boto3.client("s3", region_name=region_name)

    def write(self, key: str, payload: Any) -> None:
        self.client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=json.dumps(payload, default=_json_default, ensure_ascii=False).encode(),
            ContentType="application/json",
        )


def configured_store() -> Store:
    table = os.environ.get("DYNAMODB_TABLE")
    if table:
        return DynamoStore(table, os.environ.get("AWS_REGION"))
    return LocalStore(os.environ.get("LOCAL_DATA_DIR", ".localdata"))
