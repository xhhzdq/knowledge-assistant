"""Milvus 向量仓储的无网络单元测试。"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from pymilvus import DataType
from pymilvus.exceptions import MilvusException

from knowledge_assistant.exceptions import VectorStoreError
from knowledge_assistant.vectors import (
    MilvusVectorRepository,
    VectorRecord,
    VectorSearchHit,
)

DIMENSION = 4


def new_id() -> str:
    return str(uuid4())


def unit_vector(index: int = 0) -> list[float]:
    vector = [0.0] * DIMENSION
    vector[index] = 1.0
    return vector


class FakeSchema:
    def __init__(self) -> None:
        self.fields: list[dict[str, object]] = []

    def add_field(self, field_name: str, datatype: DataType, **kwargs: object) -> None:
        self.fields.append({"name": field_name, "type": datatype, **kwargs})


class FakeIndexParams:
    def __init__(self) -> None:
        self.indexes: list[dict[str, object]] = []

    def add_index(self, field_name: str, index_type: str = "", **kwargs: object) -> None:
        self.indexes.append(
            {"field_name": field_name, "index_type": index_type, **kwargs}
        )


class FakeMilvusClient:
    """用字典模拟主键 upsert，记录 Repository 传给 SDK 的参数。"""

    def __init__(
        self,
        *,
        collection_exists: bool = False,
        dimension: int = DIMENSION,
        metric_type: str = "COSINE",
    ) -> None:
        self.collection_exists = collection_exists
        self.dimension = dimension
        self.metric_type = metric_type
        self.create_calls = 0
        self.has_calls = 0
        self.upsert_calls: list[list[dict[str, object]]] = []
        self.search_calls: list[dict[str, object]] = []
        self.delete_calls: list[dict[str, object]] = []
        self.rows: dict[str, dict[str, object]] = {}
        self.search_result: list[list[dict[str, object]]] = [[]]
        self.failure: MilvusException | None = None
        self.schema: FakeSchema | None = None
        self.index_params: FakeIndexParams | None = None

    def _raise_if_failed(self) -> None:
        if self.failure is not None:
            raise self.failure

    def has_collection(self, _collection_name: str, timeout: float | None = None) -> bool:
        del timeout
        self.has_calls += 1
        self._raise_if_failed()
        return self.collection_exists

    def create_schema(self, **_kwargs: object) -> FakeSchema:
        self.schema = FakeSchema()
        return self.schema

    def prepare_index_params(
        self, field_name: str = "", **_kwargs: object
    ) -> FakeIndexParams:
        del field_name
        self.index_params = FakeIndexParams()
        return self.index_params

    def create_collection(
        self,
        _collection_name: str,
        *,
        schema: object,
        index_params: object,
        timeout: float | None = None,
        **_kwargs: object,
    ) -> None:
        del schema, index_params, timeout
        self._raise_if_failed()
        self.collection_exists = True
        self.create_calls += 1

    def describe_collection(
        self, _collection_name: str, timeout: float | None = None
    ) -> dict[str, object]:
        del timeout
        self._raise_if_failed()
        if self.schema is not None:
            described_fields: list[dict[str, object]] = []
            for field in self.schema.fields:
                described = {
                    "name": field["name"],
                    "is_primary": field.get("is_primary", False),
                    "params": {},
                }
                if "dim" in field:
                    described["params"] = {"dim": field["dim"]}
                described_fields.append(described)
            return {"fields": described_fields}
        return {
            "fields": [
                {"name": "chunk_id", "is_primary": True, "params": {"max_length": 36}},
                {"name": "document_id", "params": {"max_length": 36}},
                {"name": "processing_version", "params": {}},
                {"name": "page_start", "params": {}},
                {"name": "embedding", "params": {"dim": self.dimension}},
            ]
        }

    def list_indexes(self, _collection_name: str, field_name: str = "") -> list[str]:
        del field_name
        self._raise_if_failed()
        return ["embedding"]

    def describe_index(
        self,
        _collection_name: str,
        _index_name: str,
        timeout: float | None = None,
    ) -> dict[str, object]:
        del timeout
        self._raise_if_failed()
        if self.index_params is not None:
            return self.index_params.indexes[0]
        return {"field_name": "embedding", "metric_type": self.metric_type}

    def upsert(
        self,
        _collection_name: str,
        data: list[dict[str, object]],
        timeout: float | None = None,
        **_kwargs: object,
    ) -> dict[str, object]:
        del timeout
        self._raise_if_failed()
        self.upsert_calls.append(data)
        for row in data:
            self.rows[str(row["chunk_id"])] = row
        return {"upsert_count": len(data)}

    def search(
        self,
        _collection_name: str,
        data: list[list[float]],
        **kwargs: object,
    ) -> list[list[dict[str, object]]]:
        self._raise_if_failed()
        self.search_calls.append({"data": data, **kwargs})
        limit = int(kwargs["limit"])
        return [self.search_result[0][:limit]]

    def delete(
        self,
        _collection_name: str,
        *,
        ids: list[str] | None = None,
        filter: str | None = None,
        timeout: float | None = None,
        **_kwargs: object,
    ) -> dict[str, object]:
        del timeout
        self._raise_if_failed()
        self.delete_calls.append({"ids": ids, "filter": filter})
        if ids is not None:
            existing_ids = [chunk_id for chunk_id in ids if chunk_id in self.rows]
        else:
            document_id = str(filter).split('"')[1]
            existing_ids = [
                chunk_id
                for chunk_id, row in self.rows.items()
                if row["document_id"] == document_id
            ]
        for chunk_id in existing_ids:
            del self.rows[chunk_id]
        return {"delete_count": len(existing_ids)}


def repository(client: FakeMilvusClient) -> MilvusVectorRepository:
    return MilvusVectorRepository(
        "http://unused:19530",
        dimension=DIMENSION,
        client=client,
    )


def record(
    *,
    chunk_id: str | None = None,
    document_id: str | None = None,
    page_start: int | None = 1,
    embedding: list[float] | None = None,
) -> VectorRecord:
    return VectorRecord(
        chunk_id=chunk_id or new_id(),
        document_id=document_id or new_id(),
        processing_version=1,
        page_start=page_start,
        embedding=embedding or unit_vector(),
    )


def test_first_operation_creates_and_validates_collection_once() -> None:
    client = FakeMilvusClient()
    repo = repository(client)

    repo.upsert([record()])
    repo.upsert([record()])

    assert client.create_calls == 1
    assert client.has_calls == 1
    assert client.schema is not None
    assert [field["name"] for field in client.schema.fields] == [
        "chunk_id",
        "document_id",
        "processing_version",
        "page_start",
        "embedding",
    ]
    assert client.schema.fields[-1]["dim"] == DIMENSION
    assert client.index_params is not None
    assert client.index_params.indexes == [
        {
            "field_name": "embedding",
            "index_type": "AUTOINDEX",
            "metric_type": "COSINE",
        }
    ]


def test_upsert_is_idempotent_and_uses_batches() -> None:
    client = FakeMilvusClient(collection_exists=True)
    repo = repository(client)
    shared_chunk_id = new_id()
    document_id = new_id()
    first = record(chunk_id=shared_chunk_id, document_id=document_id, page_start=1)
    replacement = record(
        chunk_id=shared_chunk_id,
        document_id=document_id,
        page_start=2,
        embedding=unit_vector(1),
    )
    extra_records = [record() for _ in range(100)]

    repo.upsert([first, replacement, *extra_records])

    assert sum(len(batch) for batch in client.upsert_calls) == 101
    assert [len(batch) for batch in client.upsert_calls] == [100, 1]
    assert len(client.rows) == 101
    assert client.rows[shared_chunk_id]["page_start"] == 2
    assert client.rows[shared_chunk_id]["embedding"] == unit_vector(1)


@pytest.mark.parametrize(
    ("dimension", "metric", "message"),
    [(8, "COSINE", "向量维度不匹配"), (DIMENSION, "L2", "Metric 不匹配")],
)
def test_existing_collection_contract_is_validated(
    dimension: int, metric: str, message: str
) -> None:
    repo = repository(
        FakeMilvusClient(
            collection_exists=True,
            dimension=dimension,
            metric_type=metric,
        )
    )

    with pytest.raises(VectorStoreError, match=message):
        repo.upsert([record()])


def test_search_preserves_order_limit_and_document_filter() -> None:
    client = FakeMilvusClient(collection_exists=True)
    document_ids = [new_id(), new_id()]
    chunk_ids = [new_id(), new_id()]
    client.search_result = [
        [
            {
                "id": chunk_ids[0],
                "distance": 0.91,
                "entity": {
                    "document_id": document_ids[0],
                    "processing_version": 2,
                    "page_start": 3,
                },
            },
            {
                "id": chunk_ids[1],
                "distance": 0.73,
                "entity": {
                    "document_id": document_ids[1],
                    "processing_version": 1,
                    "page_start": 0,
                },
            },
        ]
    ]

    hits = repository(client).search(
        unit_vector(),
        top_k=2,
        document_ids=[document_ids[0], document_ids[0], document_ids[1]],
    )

    assert hits == [
        VectorSearchHit(chunk_ids[0], document_ids[0], 2, 3, 0.91),
        VectorSearchHit(chunk_ids[1], document_ids[1], 1, None, 0.73),
    ]
    call = client.search_calls[0]
    assert call["limit"] == 2
    assert call["filter"] == (
        f'document_id in ["{document_ids[0]}", "{document_ids[1]}"]'
    )
    assert call["search_params"] == {"metric_type": "COSINE"}


def test_delete_by_document_and_chunk_ids_returns_count() -> None:
    client = FakeMilvusClient(collection_exists=True)
    repo = repository(client)
    document_id = new_id()
    first = record(document_id=document_id)
    second = record(document_id=document_id)
    third = record()
    repo.upsert([first, second, third])

    assert repo.delete_by_chunk_ids([first.chunk_id, first.chunk_id]) == 1
    assert repo.delete_by_document_id(document_id) == 1
    assert third.chunk_id in client.rows
    assert client.delete_calls[-1]["filter"] == f'document_id == "{document_id}"'


def test_empty_upsert_and_delete_do_not_connect() -> None:
    client = FakeMilvusClient()
    repo = repository(client)

    repo.upsert([])
    assert repo.delete_by_chunk_ids([]) == 0
    assert client.has_calls == 0


@pytest.mark.parametrize(
    "operation",
    [
        lambda repo: repo.upsert([record()]),
        lambda repo: repo.search(unit_vector(), 1),
        lambda repo: repo.delete_by_document_id(new_id()),
        lambda repo: repo.delete_by_chunk_ids([new_id()]),
    ],
)
def test_sdk_errors_are_converted(operation: Any) -> None:
    client = FakeMilvusClient(collection_exists=True)
    repo = repository(client)
    repo.upsert([record()])
    client.failure = MilvusException(message="simulated")

    with pytest.raises(VectorStoreError):
        operation(repo)


@pytest.mark.parametrize(
    "operation",
    [
        lambda repo: repo.upsert([record(embedding=[1.0, 0.0])]),
        lambda repo: repo.search([1.0, 0.0], 1),
        lambda repo: repo.search(unit_vector(), 0),
        lambda repo: repo.delete_by_document_id("not-a-uuid"),
        lambda repo: repo.delete_by_chunk_ids(["not-a-uuid"]),
    ],
)
def test_invalid_inputs_are_rejected_before_sdk_call(operation: Any) -> None:
    client = FakeMilvusClient(collection_exists=True)

    with pytest.raises(ValueError):
        operation(repository(client))
    assert client.has_calls == 0
