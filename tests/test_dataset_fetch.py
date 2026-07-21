from __future__ import annotations

import io
import json
from pathlib import Path

from symnav_bench.dataset_fetch import fetch_dataset_files, list_dataset_files


class FakeResponse:
    def __init__(self, body: bytes, headers: dict[str, str] | None = None) -> None:
        self.stream = io.BytesIO(body)
        self.headers = headers or {}

    def read(self, size: int = -1) -> bytes:
        return self.stream.read(size)

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *exc_info: object) -> bool:
        return False


class FakeOpener:
    def __init__(self, responses: dict[str, FakeResponse]) -> None:
        self.responses = responses
        self.requested: list[str] = []

    def __call__(self, url: str) -> FakeResponse:
        self.requested.append(url)
        return self.responses[url]


def tree_response(entries: list[dict], headers: dict[str, str] | None = None) -> FakeResponse:
    return FakeResponse(json.dumps(entries).encode(), headers)


def test_list_dataset_files_returns_sorted_file_paths() -> None:
    tree_url = (
        "https://huggingface.co/api/datasets/AmazonScience/SWE-PolyBench"
        "/tree/deadbeef?recursive=true"
    )
    opener = FakeOpener(
        {
            tree_url: tree_response(
                [
                    {"type": "file", "path": "test.csv"},
                    {"type": "file", "path": "README.md"},
                    {"type": "directory", "path": "data"},
                ]
            )
        }
    )

    files = list_dataset_files("AmazonScience/SWE-PolyBench", "deadbeef", opener=opener)

    assert files == ["README.md", "test.csv"]
    assert opener.requested == [tree_url]


def test_list_dataset_files_follows_pagination_links() -> None:
    first_url = (
        "https://huggingface.co/api/datasets/org/name/tree/deadbeef?recursive=true"
    )
    next_url = (
        "https://huggingface.co/api/datasets/org/name/tree/deadbeef"
        "?recursive=true&cursor=abc"
    )
    opener = FakeOpener(
        {
            first_url: tree_response(
                [{"type": "file", "path": "b.jsonl"}],
                headers={"Link": f'<{next_url}>; rel="next"'},
            ),
            next_url: tree_response([{"type": "file", "path": "a.jsonl"}]),
        }
    )

    files = list_dataset_files("org/name", "deadbeef", opener=opener)

    assert files == ["a.jsonl", "b.jsonl"]
    assert opener.requested == [first_url, next_url]


def test_fetch_dataset_files_downloads_each_path_under_dest(tmp_path: Path) -> None:
    base = "https://huggingface.co/datasets/org/name/resolve/deadbeef"
    opener = FakeOpener(
        {
            f"{base}/test.csv": FakeResponse(b"csv-bytes"),
            f"{base}/ts/data.jsonl": FakeResponse(b"jsonl-bytes"),
        }
    )

    fetched = fetch_dataset_files(
        "org/name", "deadbeef", ["test.csv", "ts/data.jsonl"], tmp_path, opener=opener
    )

    assert fetched == [tmp_path / "test.csv", tmp_path / "ts" / "data.jsonl"]
    assert (tmp_path / "test.csv").read_bytes() == b"csv-bytes"
    assert (tmp_path / "ts" / "data.jsonl").read_bytes() == b"jsonl-bytes"
    assert opener.requested == [f"{base}/test.csv", f"{base}/ts/data.jsonl"]
