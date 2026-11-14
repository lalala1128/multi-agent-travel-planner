from types import SimpleNamespace
from unittest.mock import Mock

from ingest_knowledge import clear_collection_points, load_manifest, save_manifest


def test_manifest_version_changes_when_document_hash_changes(tmp_path):
    path = tmp_path / "knowledge_manifest.json"
    first_documents = {"doc-1": {"content_hash": "first"}}
    first_version = save_manifest(path, first_documents)

    assert load_manifest(path)["index_version"] == first_version

    second_version = save_manifest(path, {"doc-1": {"content_hash": "second"}})
    assert second_version != first_version


def test_rebuild_clears_all_existing_points_in_batches():
    client = Mock()
    client.scroll.side_effect = [
        ([SimpleNamespace(id="old-1"), SimpleNamespace(id="old-2")], None),
        ([], None),
    ]

    clear_collection_points(client)

    assert client.delete.call_count == 1
    assert client.delete.call_args.kwargs["points_selector"].points == ["old-1", "old-2"]
