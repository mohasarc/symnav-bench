from __future__ import annotations

import io
import json
import urllib.error

import pytest

from symnav_bench.container_registry import resolve_ghcr_image_digest

REPOSITORY = "timesler/swe-polybench.eval.x86_64.mui__material-ui-7444"
DIGEST = "sha256:" + "d" * 64


class FakeResponse:
    def __init__(self, body: bytes, headers: dict[str, str] | None = None) -> None:
        self.body = body
        self.headers = headers or {}

    def read(self, size: int = -1) -> bytes:
        return self.body

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *exc_info: object) -> bool:
        return False


def http_error(url: str, code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(url, code, "error", None, io.BytesIO(b""))


def registry_opener(
    requests: list[tuple[str, dict[str, str]]],
    manifest_error: urllib.error.HTTPError | None = None,
    token_error: urllib.error.HTTPError | None = None,
    digest_header: str | None = DIGEST,
):
    def opener(url: str, headers: dict[str, str]) -> FakeResponse:
        requests.append((url, headers))
        if "/token?" in url:
            if token_error is not None:
                raise token_error
            return FakeResponse(json.dumps({"token": "anonymous-token"}).encode())
        if manifest_error is not None:
            raise manifest_error
        manifest_headers = (
            {} if digest_header is None else {"Docker-Content-Digest": digest_header}
        )
        return FakeResponse(b"{}", manifest_headers)

    return opener


def test_resolves_manifest_digest_via_anonymous_token() -> None:
    requests: list[tuple[str, dict[str, str]]] = []

    digest = resolve_ghcr_image_digest(
        REPOSITORY, "latest", opener=registry_opener(requests)
    )

    assert digest == DIGEST
    token_url, token_headers = requests[0]
    assert f"repository:{REPOSITORY}:pull" in token_url
    assert "service=ghcr.io" in token_url
    manifest_url, manifest_headers = requests[1]
    assert manifest_url == f"https://ghcr.io/v2/{REPOSITORY}/manifests/latest"
    assert manifest_headers["Authorization"] == "Bearer anonymous-token"
    assert "application/vnd.oci.image.index.v1+json" in manifest_headers["Accept"]


def test_unpublished_repository_resolves_to_none() -> None:
    opener = registry_opener([], token_error=http_error("https://ghcr.io/token", 403))

    assert resolve_ghcr_image_digest(REPOSITORY, "latest", opener=opener) is None


def test_missing_tag_resolves_to_none() -> None:
    opener = registry_opener([], manifest_error=http_error("https://ghcr.io/v2", 404))

    assert resolve_ghcr_image_digest(REPOSITORY, "latest", opener=opener) is None


def test_unexpected_registry_error_is_raised() -> None:
    opener = registry_opener([], manifest_error=http_error("https://ghcr.io/v2", 500))

    with pytest.raises(urllib.error.HTTPError):
        resolve_ghcr_image_digest(REPOSITORY, "latest", opener=opener)


def test_missing_digest_header_is_an_error() -> None:
    opener = registry_opener([], digest_header=None)

    with pytest.raises(ValueError, match=REPOSITORY):
        resolve_ghcr_image_digest(REPOSITORY, "latest", opener=opener)
