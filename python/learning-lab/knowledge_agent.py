import json
from pathlib import Path

from fastembed import TextEmbedding
from qdrant_client import QdrantClient, models
from knowledge_cache import KnowledgeCache
from reranker import rerank


class KnowledgeAgent:
    def __init__(self, cache=None):
        base_dir = Path(__file__).resolve().parent

        self.db_path = base_dir / "data" / "qdrant_demo"
        self.collection_name = "travel_knowledge"
        self.embedding_model = "BAAI/bge-small-zh-v1.5"
        self.top_k = 3
        self.candidate_k = 9
        self.score_threshold = 0.4
        self.keyword_weight = 0.2
        self.cache = cache if cache is not None else KnowledgeCache()

        self.model_cache_dir = base_dir / ".model_cache"
        # 命中 Redis 时不必加载模型；模型文件已在前面的实验中下载。
        self.model = None

    def current_knowledge_version(self) -> str:
        manifest_path = self.db_path.parent / "knowledge_manifest.json"
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            return manifest["index_version"]
        except (OSError, KeyError, json.JSONDecodeError):
            # 清单不可用时仍可检索，但不复用带版本承诺的旧缓存。
            return "manifest-unavailable"

    def run(
        self,
        city: str,
        question: str,
    ) -> list[dict]:
        question = question.strip()

        if not question:
            return []

        context = {
            "city": city,
            "question": question,
            "model": self.embedding_model,
            "collection": self.collection_name,
            "top_k": self.top_k,
            "candidate_k": self.candidate_k,
            "score_threshold": self.score_threshold,
            "keyword_weight": self.keyword_weight,
            "knowledge_version": self.current_knowledge_version(),
        }

        cached = self.cache.get(context)
        if cached is not None:
            print("知识检索：命中 Redis 缓存")
            return cached

        print("知识检索：未命中缓存，执行 Embedding 和 Qdrant 查询")

        if self.model is None:
            self.model = TextEmbedding(
                model_name=self.embedding_model,
                cache_dir=str(self.model_cache_dir),
                local_files_only=True,
            )

        # 将问题转换为向量
        query = (
            "为这个句子生成表示以用于检索相关文章："
            + question
        )

        query_vector = list(self.model.embed([query]))[0]

        client = QdrantClient(path=str(self.db_path))

        try:
            if not client.collection_exists(self.collection_name):
                raise ValueError("知识集合不存在，请先运行入库脚本")

            # 只检索指定城市的资料
            result = client.query_points(
                collection_name=self.collection_name,
                query=query_vector.tolist(),
                query_filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="city",
                            match=models.MatchValue(value=city),
                        ),
                    ],
                ),
                limit=self.candidate_k,
                score_threshold=self.score_threshold,
                with_payload=True,
            )

            results = []

            for hit in result.points:
                results.append({
                    "id": str(hit.id),
                    "city": hit.payload["city"],
                    "source": hit.payload["source"],
                    "chunk_index": hit.payload["chunk_index"],
                    "text": hit.payload["text"],
                    "score": float(hit.score),
                })

            results = rerank(
                question,
                results,
                keyword_weight=self.keyword_weight,
            )[:self.top_k]
            self.cache.set(context, results)
            return results

        finally:
            client.close()

    def close(self):
        self.cache.close()


if __name__ == "__main__":
    agent = KnowledgeAgent()

    try:
        results = agent.run(
            city="首尔",
            question="我想找当地吃饭的地方",
        )

        if not results:
            print("没有找到满足条件的资料")

        for item in results:
            print("相似度：", item["score"])
            print("城市：", item["city"])
            print("来源：", item["source"])
            print("原文：", item["text"])
            print()
    finally:
        agent.close()
