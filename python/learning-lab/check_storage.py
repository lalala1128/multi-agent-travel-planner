from pathlib import Path

from qdrant_client import QdrantClient


db_path = (
    Path(__file__).resolve().parent
    / "data"
    / "qdrant_demo"
)

client = QdrantClient(path=str(db_path))

result = client.count(
    collection_name="travel_demo",
    exact=True,
)

print("保存的记录数量：", result.count)

client.close()