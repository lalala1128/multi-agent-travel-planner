from pathlib import Path

import numpy as np
from fastembed import TextEmbedding


def cosine_similarity(vector_a, vector_b):
    dot_product = np.dot(vector_a, vector_b)

    length_a = np.linalg.norm(vector_a)
    length_b = np.linalg.norm(vector_b)

    return float(dot_product / (length_a * length_b))


cache_dir = Path(__file__).resolve().parent / ".model_cache"

model = TextEmbedding(
    model_name="BAAI/bge-small-zh-v1.5",
    cache_dir=str(cache_dir),
)

texts = [
    "为这个句子生成表示以用于检索相关文章：我想找当地吃饭的地方",
    "美食体验：可以将当地市场探索与街区餐饮体验结合安排。",
    "天气提醒：下雨时携带雨具，注意防水。",
]

vectors = list(model.embed(texts))

query_vector = vectors[0]
food_vector = vectors[1]
weather_vector = vectors[2]

print("向量数量：", len(vectors))
print("每条向量的维度：", len(query_vector))

print(
    "问题与美食资料的相似度：",
    cosine_similarity(query_vector, food_vector),
)

print(
    "问题与天气资料的相似度：",
    cosine_similarity(query_vector, weather_vector),
)