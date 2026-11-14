from document_loader import load_documents


def test_document_identity_is_stable_but_content_hash_changes(tmp_path):
    source = tmp_path / "首尔.md"
    source.write_text("美食体验：逛市场。", encoding="utf-8")

    first = load_documents(tmp_path)[0]
    source.write_text("美食体验：逛市场。\n\n文化体验：参观博物馆。", encoding="utf-8")
    second = load_documents(tmp_path)[0]

    assert first["document_id"] == second["document_id"]
    assert first["content_hash"] != second["content_hash"]
    assert second["chunks"][0]["document_id"] == second["document_id"]
    assert len(second["chunks"]) == 2
