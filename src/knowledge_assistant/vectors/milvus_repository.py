"""基于 pymilvus ``MilvusClient`` 的向量仓储实现。"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from threading import Lock
from typing import Protocol, cast
from uuid import UUID

from pymilvus import DataType, MilvusClient  # type: ignore[import-untyped]
from pymilvus.exceptions import MilvusException  # type: ignore[import-untyped]

from knowledge_assistant.exceptions import VectorStoreError
from knowledge_assistant.vectors.base import VectorRecord, VectorSearchHit


class SchemaLike(Protocol):
    """只描述创建 Collection 时实际使用的 Schema 方法。"""

    def add_field(self, field_name: str, datatype: DataType, **kwargs: object) -> None: ...


class IndexParamsLike(Protocol):
    """只描述本项目配置向量索引时实际使用的方法。"""

    def add_index(self, field_name: str, index_type: str = "", **kwargs: object) -> None: ...


class MilvusClientLike(Protocol):
    """Milvus SDK 的最小接口，单元测试可以注入 Fake Client。"""

    def has_collection(self, collection_name: str, timeout: float | None = None) -> bool: ...

    def create_schema(self, **kwargs: object) -> SchemaLike: ...

    def prepare_index_params(self, field_name: str = "", **kwargs: object) -> IndexParamsLike: ...

    def create_collection(
        self,
        collection_name: str,
        *,
        schema: object,
        index_params: object,
        timeout: float | None = None,
        **kwargs: object,
    ) -> None: ...

    def describe_collection(
        self, collection_name: str, timeout: float | None = None
    ) -> Mapping[str, object]: ...

    def list_indexes(self, collection_name: str, field_name: str = "") -> list[str]: ...

    def describe_index(
        self,
        collection_name: str,
        index_name: str,
        timeout: float | None = None,
    ) -> Mapping[str, object]: ...

    def upsert(
        self,
        collection_name: str,
        data: list[dict[str, object]],
        timeout: float | None = None,
        **kwargs: object,
    ) -> Mapping[str, object]: ...

    def search(
        self,
        collection_name: str,
        data: list[list[float]],
        *,
        filter: str = "",
        limit: int = 10,
        output_fields: list[str] | None = None,
        search_params: dict[str, object] | None = None,
        timeout: float | None = None,
        anns_field: str | None = None,
        **kwargs: object,
    ) -> list[list[dict[str, object]]]: ...

    def delete(
        self,
        collection_name: str,
        *,
        ids: list[str] | None = None,
        filter: str | None = None,
        timeout: float | None = None,
        **kwargs: object,
    ) -> Mapping[str, object]: ...


class MilvusVectorRepository:
    """保存 Chunk 向量，并维护 ``document_chunks_v1`` Collection 契约。"""

    _COLLECTION_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
    _UUID_TEXT_LENGTH = 36
    _UPSERT_BATCH_SIZE = 100

    def __init__(
        self,
        uri: str,
        *,
        collection_name: str = "document_chunks_v1",
        dimension: int = 512,
        metric_type: str = "COSINE",
        timeout_seconds: float = 5.0,
        client: MilvusClientLike | None = None,
    ) -> None:
        if not uri.strip():
            raise ValueError("uri 不能为空")
        if not self._COLLECTION_NAME_PATTERN.fullmatch(collection_name):
            raise ValueError("collection_name 不是合法的 Milvus Collection 名称")
        if dimension <= 0:
            raise ValueError("dimension 必须大于 0")
        normalized_metric = metric_type.upper()
        if normalized_metric != "COSINE":
            raise ValueError("当前 Repository 只支持 COSINE")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds 必须大于 0")

        self.collection_name = collection_name
        self.dimension = dimension
        self.metric_type = normalized_metric
        self.timeout_seconds = timeout_seconds
        self._client = (
            client
            if client is not None
            else cast(
                "MilvusClientLike",
                MilvusClient(uri=uri, timeout=timeout_seconds),
            )
        )
        self._collection_ready = False
        self._collection_lock = Lock()

    def _ensure_collection(self) -> None:
        """首次操作时幂等建 Collection，后续请求复用校验结果。"""
        if self._collection_ready:
            return
        with self._collection_lock:
            if self._collection_ready:
                return
            try:
                if not self._client.has_collection(
                    self.collection_name,
                    timeout=self.timeout_seconds,
                ):
                    self._create_collection()
                self._validate_collection()
            except VectorStoreError:
                raise
            except MilvusException as exc:
                raise VectorStoreError("连接或初始化 Milvus Collection 失败") from exc
            self._collection_ready = True

    def _create_collection(self) -> None:
        """使用显式 Schema 创建 Collection，禁止动态字段掩盖拼写错误。"""
        schema = self._client.create_schema(auto_id=False, enable_dynamic_field=False)
        schema.add_field(
            "chunk_id",
            DataType.VARCHAR,
            is_primary=True,
            auto_id=False,
            max_length=self._UUID_TEXT_LENGTH,
        )
        schema.add_field(
            "document_id",
            DataType.VARCHAR,
            max_length=self._UUID_TEXT_LENGTH,
        )
        schema.add_field("processing_version", DataType.INT64)
        schema.add_field("page_start", DataType.INT64)
        schema.add_field("embedding", DataType.FLOAT_VECTOR, dim=self.dimension)

        index_params = self._client.prepare_index_params()
        index_params.add_index(
            field_name="embedding",
            index_type="AUTOINDEX",
            metric_type=self.metric_type,
        )
        try:
            self._client.create_collection(
                self.collection_name,
                schema=schema,
                index_params=index_params,
                consistency_level="Strong",
                timeout=self.timeout_seconds,
            )
        except MilvusException:
            # 多进程可能同时发现 Collection 不存在；若另一进程已创建则继续校验。
            if not self._client.has_collection(
                self.collection_name,
                timeout=self.timeout_seconds,
            ):
                raise

    def _validate_collection(self) -> None:
        """拒绝复用维度或度量不匹配的同名 Collection。"""
        description = self._client.describe_collection(
            self.collection_name,
            timeout=self.timeout_seconds,
        )
        raw_fields = description.get("fields")
        if not isinstance(raw_fields, Sequence) or isinstance(raw_fields, (str, bytes)):
            raise VectorStoreError("Milvus Collection 未返回有效的字段定义")

        fields: dict[str, Mapping[str, object]] = {}
        for raw_field in raw_fields:
            if isinstance(raw_field, Mapping) and isinstance(raw_field.get("name"), str):
                fields[cast(str, raw_field["name"])] = raw_field

        required_fields = {
            "chunk_id",
            "document_id",
            "processing_version",
            "page_start",
            "embedding",
        }
        missing_fields = sorted(required_fields - fields.keys())
        if missing_fields:
            raise VectorStoreError(
                f"Milvus Collection 缺少字段: {', '.join(missing_fields)}"
            )
        if not bool(fields["chunk_id"].get("is_primary")):
            raise VectorStoreError("Milvus Collection 的 chunk_id 必须是主键")

        params = fields["embedding"].get("params")
        if not isinstance(params, Mapping):
            raise VectorStoreError("Milvus embedding 字段缺少维度参数")
        try:
            actual_dimension = int(cast(str | int, params.get("dim")))
        except (TypeError, ValueError) as exc:
            raise VectorStoreError("Milvus embedding 字段维度无效") from exc
        if actual_dimension != self.dimension:
            raise VectorStoreError(
                f"Milvus 向量维度不匹配: 配置 {self.dimension}, 实际 {actual_dimension}"
            )

        index_names = self._client.list_indexes(self.collection_name, field_name="embedding")
        if not index_names:
            raise VectorStoreError("Milvus embedding 字段缺少向量索引")
        index = self._client.describe_index(
            self.collection_name,
            index_names[0],
            timeout=self.timeout_seconds,
        )
        actual_metric = str(index.get("metric_type", "")).upper()
        if actual_metric != self.metric_type:
            raise VectorStoreError(
                f"Milvus Metric 不匹配: 配置 {self.metric_type}, 实际 {actual_metric or '未知'}"
            )

    def upsert(self, records: Sequence[VectorRecord]) -> None:
        """批量幂等写入；同一批出现相同主键时保留最后一条。"""
        if not records:
            return
        unique_records: dict[str, VectorRecord] = {}
        for record in records:
            self._validate_uuid(record.chunk_id, "chunk_id")
            self._validate_uuid(record.document_id, "document_id")
            if record.processing_version <= 0:
                raise ValueError("processing_version 必须大于 0")
            if record.page_start is not None and record.page_start <= 0:
                raise ValueError("page_start 必须大于 0 或为 None")
            self._validate_vector(record.embedding, "embedding")
            unique_records[record.chunk_id] = record

        self._ensure_collection()
        rows = [
            {
                "chunk_id": record.chunk_id,
                "document_id": record.document_id,
                "processing_version": record.processing_version,
                "page_start": record.page_start or 0,
                "embedding": [float(value) for value in record.embedding],
            }
            for record in unique_records.values()
        ]
        try:
            for start in range(0, len(rows), self._UPSERT_BATCH_SIZE):
                self._client.upsert(
                    self.collection_name,
                    rows[start : start + self._UPSERT_BATCH_SIZE],
                    timeout=self.timeout_seconds,
                )
        except MilvusException as exc:
            raise VectorStoreError("批量写入 Milvus 向量失败") from exc

    def search(
        self,
        query_vector: Sequence[float],
        top_k: int,
        document_ids: Sequence[str] | None = None,
    ) -> list[VectorSearchHit]:
        """搜索一个查询向量，保持 Milvus 返回的相似度顺序。"""
        vector = self._validate_vector(query_vector, "query_vector")
        if top_k <= 0:
            raise ValueError("top_k 必须大于 0")
        unique_document_ids = list(dict.fromkeys(document_ids or []))
        for document_id in unique_document_ids:
            self._validate_uuid(document_id, "document_id")
        filter_expression = ""
        if unique_document_ids:
            quoted_ids = ", ".join(f'"{document_id}"' for document_id in unique_document_ids)
            filter_expression = f"document_id in [{quoted_ids}]"

        self._ensure_collection()
        try:
            result = self._client.search(
                self.collection_name,
                [vector],
                anns_field="embedding",
                filter=filter_expression,
                limit=top_k,
                output_fields=[
                    "chunk_id",
                    "document_id",
                    "processing_version",
                    "page_start",
                ],
                search_params={"metric_type": self.metric_type},
                timeout=self.timeout_seconds,
            )
        except MilvusException as exc:
            raise VectorStoreError("Milvus 向量搜索失败") from exc

        if not result:
            return []
        return [self._to_search_hit(raw_hit) for raw_hit in result[0]]

    def delete_by_document_id(self, document_id: str) -> int:
        """按经过 UUID 校验的文档 ID 删除，避免拼接任意表达式。"""
        self._validate_uuid(document_id, "document_id")
        self._ensure_collection()
        try:
            result = self._client.delete(
                self.collection_name,
                filter=f'document_id == "{document_id}"',
                timeout=self.timeout_seconds,
            )
        except MilvusException as exc:
            raise VectorStoreError("按文档删除 Milvus 向量失败") from exc
        return self._delete_count(result)

    def delete_by_chunk_ids(self, chunk_ids: Sequence[str]) -> int:
        """利用主键删除接口批量删除 Chunk，空输入不访问 Milvus。"""
        if not chunk_ids:
            return 0
        unique_ids = list(dict.fromkeys(chunk_ids))
        for chunk_id in unique_ids:
            self._validate_uuid(chunk_id, "chunk_id")
        self._ensure_collection()
        try:
            result = self._client.delete(
                self.collection_name,
                ids=unique_ids,
                timeout=self.timeout_seconds,
            )
        except MilvusException as exc:
            raise VectorStoreError("按 Chunk 删除 Milvus 向量失败") from exc
        return self._delete_count(result)

    def _validate_vector(self, vector: Sequence[float], field_name: str) -> list[float]:
        if isinstance(vector, (str, bytes)) or len(vector) != self.dimension:
            raise ValueError(f"{field_name} 必须是 {self.dimension} 维向量")
        try:
            values = [float(value) for value in vector]
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field_name} 必须只包含数值") from exc
        if not all(math.isfinite(value) for value in values):
            raise ValueError(f"{field_name} 不能包含 NaN 或无穷值")
        return values

    @staticmethod
    def _validate_uuid(raw_value: str, field_name: str) -> None:
        try:
            UUID(raw_value)
        except (AttributeError, TypeError, ValueError) as exc:
            raise ValueError(f"{field_name} 必须是合法 UUID") from exc

    @staticmethod
    def _delete_count(result: Mapping[str, object]) -> int:
        try:
            count = int(cast(int | str, result.get("delete_count", 0)))
        except (TypeError, ValueError) as exc:
            raise VectorStoreError("Milvus 返回了无效的删除数量") from exc
        if count < 0:
            raise VectorStoreError("Milvus 返回了负数删除数量")
        return count

    @staticmethod
    def _to_search_hit(raw_hit: Mapping[str, object]) -> VectorSearchHit:
        entity = raw_hit.get("entity")
        entity_values: Mapping[str, object] = entity if isinstance(entity, Mapping) else {}
        chunk_id = raw_hit.get("id", entity_values.get("chunk_id"))
        document_id = entity_values.get("document_id")
        processing_version = entity_values.get("processing_version")
        page_start = entity_values.get("page_start", 0)
        score = raw_hit.get("distance", raw_hit.get("score"))
        if not isinstance(chunk_id, str) or not isinstance(document_id, str):
            raise VectorStoreError("Milvus 搜索结果缺少 Chunk 或 Document ID")
        try:
            parsed_page_start = int(cast(int | str, page_start))
            parsed_processing_version = int(cast(int | str, processing_version))
            parsed_score = float(cast(float | int | str, score))
            if parsed_processing_version <= 0 or parsed_page_start < 0:
                raise ValueError
            if not math.isfinite(parsed_score):
                raise ValueError
            return VectorSearchHit(
                chunk_id=str(chunk_id),
                document_id=str(document_id),
                processing_version=parsed_processing_version,
                page_start=parsed_page_start or None,
                score=parsed_score,
            )
        except (TypeError, ValueError) as exc:
            raise VectorStoreError("Milvus 返回了无法解析的搜索结果") from exc
