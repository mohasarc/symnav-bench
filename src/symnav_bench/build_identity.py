from __future__ import annotations

import os
from importlib.metadata import PackageNotFoundError, version


DEPENDENCIES = ("datacurve-pier", "matplotlib", "PyYAML")


def build_version_text() -> str:
    bench_version = _installed_version("symnav-bench")
    bench_sha = os.environ.get("SYMNAV_BENCH_SHA", "unknown")
    image_version = os.environ.get("SYMNAV_BENCH_IMAGE_VERSION", "unknown")
    dependencies = ", ".join(f"{name}={_installed_version(name)}" for name in DEPENDENCIES)
    return (
        f"symnav-bench {bench_version} "
        f"(bench_sha={bench_sha}; image={image_version}; {dependencies})"
    )


def _installed_version(distribution: str) -> str:
    try:
        return version(distribution)
    except PackageNotFoundError:
        return "unknown"
