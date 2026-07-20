from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Protocol

from symnav_bench.dataset_fetch import HttpResponse

GHCR_HOST = "https://ghcr.io"
GHCR_TOKEN_URL = f"{GHCR_HOST}/token?service=ghcr.io"
DOCKER_HUB_REGISTRY_HOST = "https://registry-1.docker.io"
DOCKER_HUB_TOKEN_URL = "https://auth.docker.io/token?service=registry.docker.io"
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
    return resolve_image_digest(GHCR_TOKEN_URL, GHCR_HOST, repository, tag, opener)


def resolve_docker_hub_image_digest(
    repository: str, tag: str, *, opener: RequestOpener = open_request
) -> str | None:
    return resolve_image_digest(
        DOCKER_HUB_TOKEN_URL, DOCKER_HUB_REGISTRY_HOST, repository, tag, opener
    )


def resolve_image_digest(
    token_url: str,
    registry_host: str,
    repository: str,
    tag: str,
    opener: RequestOpener,
) -> str | None:
    try:
        token = anonymous_pull_token(token_url, repository, opener)
        manifest_url = f"{registry_host}/v2/{repository}/manifests/{tag}"
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


def anonymous_pull_token(
    token_url: str, repository: str, opener: RequestOpener
) -> str:
    url = f"{token_url}&scope=repository:{repository}:pull"
    with opener(url, {}) as response:
        return json.loads(response.read())["token"]
