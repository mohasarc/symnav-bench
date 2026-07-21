from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Protocol

from symnav_bench.dataset_fetch import HttpResponse

GHCR_HOST = "https://ghcr.io"
GHCR_TOKEN_URL = f"{GHCR_HOST}/token?service=ghcr.io"
DOCKER_HUB_REGISTRY_HOST = "https://registry-1.docker.io"
DOCKER_HUB_TOKEN_URL = "https://auth.docker.io/token?service=registry.docker.io"
DOCKER_HUB_USERNAME_VARIABLE = "DOCKER_HUB_USERNAME"
DOCKER_HUB_TOKEN_VARIABLE = "DOCKER_HUB_TOKEN"
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
    def __call__(
        self, url: str, headers: dict[str, str], method: str = "GET"
    ) -> HttpResponse: ...


def open_request(
    url: str, headers: dict[str, str], method: str = "GET"
) -> HttpResponse:
    request = urllib.request.Request(
        url, headers={"User-Agent": "symnav-bench", **headers}, method=method
    )
    return urllib.request.urlopen(request)


@dataclass(frozen=True)
class RegistryCredentials:
    username: str
    token: str

    def basic_auth_header(self) -> str:
        encoded = base64.b64encode(f"{self.username}:{self.token}".encode()).decode()
        return f"Basic {encoded}"


def docker_hub_credentials_from_environment() -> RegistryCredentials | None:
    username = os.environ.get(DOCKER_HUB_USERNAME_VARIABLE)
    token = os.environ.get(DOCKER_HUB_TOKEN_VARIABLE)
    if username and token:
        return RegistryCredentials(username=username, token=token)
    return None


class RegistryDigestResolver:
    def __init__(
        self,
        token_url: str,
        registry_host: str,
        credentials: RegistryCredentials | None = None,
        opener: RequestOpener | None = None,
    ) -> None:
        self.token_url = token_url
        self.registry_host = registry_host
        self.credentials = credentials
        self.opener: RequestOpener = opener if opener is not None else open_request
        self.pull_tokens: dict[str, str] = {}

    def resolve(self, repository: str, tag: str) -> str | None:
        try:
            token = self.pull_token(repository)
            manifest_url = f"{self.registry_host}/v2/{repository}/manifests/{tag}"
            headers = {"Authorization": f"Bearer {token}", "Accept": MANIFEST_ACCEPT}
            with self.opener(manifest_url, headers, method="HEAD") as response:
                digest = response.headers.get("Docker-Content-Digest")
        except urllib.error.HTTPError as error:
            if error.code in MISSING_IMAGE_STATUSES:
                return None
            raise
        if not digest:
            raise ValueError(f"registry returned no digest for {repository}:{tag}")
        return digest

    def image_working_dir(self, repository: str, reference: str) -> str:
        manifest = self.fetch_json(
            repository, f"/manifests/{reference}", accept=MANIFEST_ACCEPT
        )
        if "manifests" in manifest:
            amd64 = next(
                entry
                for entry in manifest["manifests"]
                if entry.get("platform", {}).get("architecture") == "amd64"
            )
            manifest = self.fetch_json(
                repository, f"/manifests/{amd64['digest']}", accept=MANIFEST_ACCEPT
            )
        config_digest = manifest["config"]["digest"]
        config = self.fetch_json(repository, f"/blobs/{config_digest}")
        return config.get("config", {}).get("WorkingDir", "")

    def fetch_json(
        self, repository: str, path: str, accept: str = "application/json"
    ) -> dict:
        token = self.pull_token(repository)
        url = f"{self.registry_host}/v2/{repository}{path}"
        headers = {"Authorization": f"Bearer {token}", "Accept": accept}
        with self.opener(url, headers) as response:
            return json.loads(response.read())

    def pull_token(self, repository: str) -> str:
        cached = self.pull_tokens.get(repository)
        if cached is not None:
            return cached
        url = f"{self.token_url}&scope=repository:{repository}:pull"
        headers: dict[str, str] = {}
        if self.credentials is not None:
            headers["Authorization"] = self.credentials.basic_auth_header()
        with self.opener(url, headers) as response:
            token = json.loads(response.read())["token"]
        self.pull_tokens[repository] = token
        return token


def docker_hub_digest_resolver(
    opener: RequestOpener | None = None,
) -> RegistryDigestResolver:
    return RegistryDigestResolver(
        DOCKER_HUB_TOKEN_URL,
        DOCKER_HUB_REGISTRY_HOST,
        credentials=docker_hub_credentials_from_environment(),
        opener=opener if opener is not None else open_request,
    )


def resolve_ghcr_image_digest(
    repository: str, tag: str, *, opener: RequestOpener = open_request
) -> str | None:
    return RegistryDigestResolver(GHCR_TOKEN_URL, GHCR_HOST, opener=opener).resolve(
        repository, tag
    )


def resolve_docker_hub_image_digest(
    repository: str, tag: str, *, opener: RequestOpener = open_request
) -> str | None:
    return RegistryDigestResolver(
        DOCKER_HUB_TOKEN_URL, DOCKER_HUB_REGISTRY_HOST, opener=opener
    ).resolve(repository, tag)
