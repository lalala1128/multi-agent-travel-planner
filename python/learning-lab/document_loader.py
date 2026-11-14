import hashlib
from pathlib import Path


def stable_document_id(city: str, source: str) -> str:
    """文件改写后仍保持不变的文档身份，不使用内容计算。"""
    identity = f"{city}/{source}".encode("utf-8")
    return hashlib.sha256(identity).hexdigest()


def content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def load_documents(knowledge_dir: Path | None = None) -> list[dict]:
    if knowledge_dir is None:
        knowledge_dir = Path(__file__).resolve().parent / "knowledge"

    documents = []

    for file in sorted(knowledge_dir.glob("*.md")):
        content = file.read_text(encoding="utf-8")
        paragraphs = content.split("\n\n")
        city = file.stem
        document = {
            "city": city,
            "source": file.name,
            "document_id": stable_document_id(city, file.name),
            "content_hash": content_hash(content),
            "chunks": [],
        }

        for index, paragraph in enumerate(paragraphs):
            text = paragraph.strip()

            if not text:
                continue

            document["chunks"].append({
                "city": city,
                "source": file.name,
                "chunk_index": index,
                "text": text,
                "document_id": document["document_id"],
                "content_hash": document["content_hash"],
            })

        if document["chunks"]:
            documents.append(document)

    return documents


def load_chunks(knowledge_dir: Path | None = None) -> list[dict]:
    chunks = []
    for document in load_documents(knowledge_dir):
        chunks.extend(document["chunks"])
    return chunks


if __name__ == "__main__":
    chunks = load_chunks()

    print("片段数量：", len(chunks))

    for chunk in chunks:
        print(chunk)
