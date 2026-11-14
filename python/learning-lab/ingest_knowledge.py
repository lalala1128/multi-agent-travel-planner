"""增量入库：内容去重、版本替换与删除同步。"""

import hashlib
import json
import argparse
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from fastembed import TextEmbedding
from qdrant_client import QdrantClient, models

from document_loader import load_documents


COLLECTION_NAME = "travel_knowledge"
MANIFEST_NAME = "knowledge_manifest.json"


def load_manifest(path: Path) -> dict:
    if not path.exists():
        return {"documents": {}, "index_version": ""}
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(manifest.get("documents"), dict):
        raise ValueError("知识库清单格式不正确")
    return manifest


def save_manifest(path: Path, documents: dict) -> str:
    version_source = json.dumps(documents, ensure_ascii=False, sort_keys=True)
    index_version = hashlib.sha256(version_source.encode("utf-8")).hexdigest()
    payload = {"documents": documents, "index_version": index_version}
    temporary_path = path.with_suffix(".tmp")
    temporary_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary_path.replace(path)
    return index_version


def document_filter(document_id: str) -> models.Filter:
    return models.Filter(
        must=[
            models.FieldCondition(
                key="document_id",
                match=models.MatchValue(value=document_id),
            ),
        ],
    )


def delete_document(client: QdrantClient, document_id: str):
    client.delete(
        collection_name=COLLECTION_NAME,
        points_selector=models.FilterSelector(filter=document_filter(document_id)),
        wait=True,
    )


def clear_collection_points(client: QdrantClient):
    """逐批清空点位，保留集合的向量配置。"""
    while True:
        points, _ = client.scroll(
            collection_name=COLLECTION_NAME,
            limit=100,
            with_payload=False,
            with_vectors=False,
        )
        if not points:
            return
        client.delete(
            collection_name=COLLECTION_NAME,
            points_selector=models.PointIdsList(points=[point.id for point in points]),
            wait=True,
        )


def make_points(chunks: list[dict], vectors) -> list[models.PointStruct]:
    points = []
    for chunk, vector in zip(chunks, vectors, strict=True):
        point_id = str(uuid5(
            NAMESPACE_URL,
            f"{chunk['document_id']}/{chunk['chunk_index']}",
        ))
        points.append(models.PointStruct(
            id=point_id,
            vector=vector.tolist(),
            payload=chunk,
        ))
    return points


def ingest(rebuild: bool = False) -> dict:
    base_dir = Path(__file__).resolve().parent
    manifest_path = base_dir / "data" / MANIFEST_NAME
    manifest_path.parent.mkdir(parents=True, exist_ok=True)

    documents = load_documents()
    if not documents:
        raise ValueError("没有读取到资料，请检查 knowledge 目录")

    current_documents = {
        document["document_id"]: {
            "city": document["city"],
            "source": document["source"],
            "content_hash": document["content_hash"],
        }
        for document in documents
    }
    previous_manifest = load_manifest(manifest_path)
    previous_documents = previous_manifest["documents"]

    client = QdrantClient(path=str(base_dir / "data" / "qdrant_demo"))
    try:
        collection_exists = client.collection_exists(COLLECTION_NAME)
        if rebuild and collection_exists:
            # 仅操作本项目的本地教学集合；用户需显式传 --rebuild 才会执行。
            clear_collection_points(client)
            previous_documents = {}

        if collection_exists and not manifest_path.exists():
            legacy_count = client.count(COLLECTION_NAME, exact=True).count
            if legacy_count:
                raise RuntimeError(
                    "检测到旧版知识库索引。请显式执行 "
                    "python ingest_knowledge.py --rebuild 进行一次迁移。",
                )

        if not collection_exists:
            client.create_collection(
                collection_name=COLLECTION_NAME,
                vectors_config=models.VectorParams(
                    size=512,
                    distance=models.Distance.COSINE,
                ),
            )
            # 集合不存在时，清单不能作为跳过向量化的依据。
            previous_documents = {}

        changed_documents = [
            document for document in documents
            if previous_documents.get(document["document_id"], {}).get("content_hash")
            != document["content_hash"]
        ]
        removed_document_ids = set(previous_documents) - set(current_documents)
        changed_chunks = [
            chunk
            for document in changed_documents
            for chunk in document["chunks"]
        ]

        if changed_chunks:
            model = TextEmbedding(
                model_name="BAAI/bge-small-zh-v1.5",
                cache_dir=str(base_dir / ".model_cache"),
                local_files_only=True,
            )
            vectors = list(model.embed([chunk["text"] for chunk in changed_chunks]))
            points = make_points(changed_chunks, vectors)

            # 先完成向量计算，再替换旧版本，降低版本替换中断的风险。
            for document in changed_documents:
                if document["document_id"] in previous_documents:
                    delete_document(client, document["document_id"])

            client.upsert(COLLECTION_NAME, points=points, wait=True)

        for document_id in removed_document_ids:
            delete_document(client, document_id)

        index_version = save_manifest(manifest_path, current_documents)
        count = client.count(COLLECTION_NAME, exact=True).count
        return {
            "changed_documents": len(changed_documents),
            "removed_documents": len(removed_document_ids),
            "written_chunks": len(changed_chunks),
            "collection_count": count,
            "index_version": index_version,
        }
    finally:
        client.close()


def main():
    parser = argparse.ArgumentParser(description="增量写入旅行知识库")
    parser.add_argument(
        "--rebuild",
        action="store_true",
        help="删除并重建本项目的 travel_knowledge 本地集合",
    )
    args = parser.parse_args()
    result = ingest(rebuild=args.rebuild)
    print("变更文档数量：", result["changed_documents"])
    print("删除文档数量：", result["removed_documents"])
    print("本次写入片段数量：", result["written_chunks"])
    print("集合中的记录数量：", result["collection_count"])
    print("知识库版本：", result["index_version"][:12])


if __name__ == "__main__":
    main()
