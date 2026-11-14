from pathlib import Path

from fastembed import TextEmbedding
from qdrant_client import QdrantClient, models


cache_dir = Path(__file__).resolve().parent / ".model_cache"

model = TextEmbedding(
    model_name="BAAI/bge-small-zh-v1.5",
    cache_dir=str(cache_dir),
)

documents = [
    "美食体验：可以将当地市场探索与街区餐饮体验结合安排。",
    "天气提醒：下雨时携带雨具，注意防水。",
]

vectors = list(model.embed(documents))
db_path = (
    Path(__file__).resolve().parent
    / "data"
    / "qdrant_demo"
)

client = QdrantClient(path=str(db_path))
if not client.collection_exists(
    collection_name="travel_demo"
):
    client.create_collection(
        collection_name="travel_demo",
        vectors_config=models.VectorParams(
            size=512,
            distance=models.Distance.COSINE,
        ),
    )
points = [
    models.PointStruct(
        id=1,
        vector=vectors[0].tolist(),
        payload={
            "city": "首尔",
            "source": "美食演示片段",
            "text": documents[0],
        },
    ),
    models.PointStruct(
        id=2,
        vector=vectors[1].tolist(),
        payload={
            "city": "首尔",
            "source": "天气演示片段",
            "text": documents[1],
        },
    ),
    models.PointStruct(
    id=3,
    vector=vectors[0].tolist(),
    payload={
        "city": "东京",
        "source": "东京美食演示片段",
        "text": documents[0],
    },
),
]

client.upsert(
    collection_name="travel_demo",
    points=points,
)
query = "为这个句子生成表示以用于检索相关文章：我想找当地吃饭的地方"

query_vector = list(model.embed([query]))[0]

result = client.query_points(
    collection_name="travel_demo",
    query=query_vector.tolist(),
    query_filter=models.Filter(
        must=[
            models.FieldCondition(
                key="city",
                match=models.MatchValue(value="东京"),
            ),
        ],
    ),
    limit=2,
    score_threshold=0.4,
    with_payload=True,
)
if not result.points:
    print("没有找到满足相似度阈值的资料")
for hit in result.points:
    print("相似度：", hit.score)
    print("来源：", hit.payload["source"])
    print("原文：", hit.payload["text"])
    print("城市：", hit.payload["city"])
    print()


client.close()