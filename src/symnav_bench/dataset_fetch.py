from __future__ import annotations

import json
import shutil
import urllib.request
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Protocol


HUGGING_FACE_HOST = "https://huggingface.co"


class HttpResponse(Protocol):
    headers: Any

    def read(self, size: int = -1) -> bytes: ...

    def __enter__(self) -> HttpResponse: ...

    def __exit__(self, *exc_info: object) -> bool: ...


class UrlOpener(Protocol):
    def __call__(self, url: str) -> HttpResponse: ...


def open_url(url: str) -> HttpResponse:
    request = urllib.request.Request(url, headers={"User-Agent": "symnav-bench"})
    return urllib.request.urlopen(request)


def list_dataset_files(
    repo_id: str, revision: str, *, opener: UrlOpener = open_url
) -> list[str]:
    files: list[str] = []
    url: str | None = (
        f"{HUGGING_FACE_HOST}/api/datasets/{repo_id}/tree/{revision}?recursive=true"
    )
    while url is not None:
        with opener(url) as response:
            entries = json.loads(response.read())
            next_url = next_page_url(response.headers.get("Link"))
        files.extend(
            entry["path"] for entry in entries if entry.get("type") == "file"
        )
        url = next_url
    return sorted(files)


def next_page_url(link_header: str | None) -> str | None:
    if not link_header:
        return None
    for part in link_header.split(","):
        if 'rel="next"' not in part:
            continue
        start = part.find("<")
        end = part.find(">")
        if start != -1 and end > start:
            return part[start + 1 : end]
    return None


def fetch_dataset_files(
    repo_id: str,
    revision: str,
    paths: Sequence[str],
    dest: Path,
    *,
    opener: UrlOpener = open_url,
) -> list[Path]:
    fetched: list[Path] = []
    for path in paths:
        url = f"{HUGGING_FACE_HOST}/datasets/{repo_id}/resolve/{revision}/{path}"
        target = dest / path
        target.parent.mkdir(parents=True, exist_ok=True)
        with opener(url) as response, target.open("wb") as output:
            shutil.copyfileobj(response, output)
        fetched.append(target)
    return fetched
