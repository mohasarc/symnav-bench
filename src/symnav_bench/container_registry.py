from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Protocol

from symnav_bench.dataset_fetch import HttpResponse

GHCR_HOST = "https://ghcr.io"
MANIFEST_ACCEPT = ", ".join(
    (
        "application/vnd.oci.image.index.v1+json",
        "application/vnd.docker.distribution.manifest.list.v2+json",
        "application/vnd.oci.image.manifest.v1+json",
        "application/vnd.docker.distribution.manifest.v2+json",
    )
)
MISSING_IMAGE_STATUSES = (401, 403, 404)


class RequestOpener(Protocol):
    def __call__(self, url: str, headers: dict[str, str]) -> HttpResponse: ...


def open_request(url: str, headers: dict[str, str]) -> HttpResponse:
    request = urllib.request.Request(
        url, headers={"User-Agent": "symnav-bench", **headers}
    )
    return urllib.request.urlopen(request)


def resolve_ghcr_image_digest(
    repository: str, tag: str, *, opener: RequestOpener = open_request
) -> str | None:
    try:
        token = anonymous_pull_token(repository, opener)
        manifest_url = f"{GHCR_HOST}/v2/{repository}/manifests/{tag}"
        headers = {"Authorization": f"Bearer {token}", "Accept": MANIFEST_ACCEPT}
        with opener(manifest_url, headers) as response:
            digest = response.headers.get("Docker-Content-Digest")
    except urllib.error.HTTPError as error:
        if error.code in MISSING_IMAGE_STATUSES:
            return None
        raise
    if not digest:
        raise ValueError(f"registry returned no digest for {repository}:{tag}")
    return digest


def anonymous_pull_token(repository: str, opener: RequestOpener) -> str:
    url = f"{GHCR_HOST}/token?service=ghcr.io&scope=repository:{repository}:pull"
    with opener(url, {}) as response:
        return json.loads(response.read())["token"]
