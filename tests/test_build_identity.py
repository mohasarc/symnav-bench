from __future__ import annotations

from symnav_bench.build_identity import build_version_text


def test_build_version_reports_commit_image_and_dependency_versions(monkeypatch) -> None:
    monkeypatch.setenv("SYMNAV_BENCH_SHA", "a" * 40)
    monkeypatch.setenv("SYMNAV_BENCH_IMAGE_VERSION", "phase-3")

    text = build_version_text()

    assert f"bench_sha={'a' * 40}" in text
    assert "image=phase-3" in text
    assert "datacurve-pier=0.3.0" in text
    assert "matplotlib=3.11.0" in text
    assert "PyYAML=6.0.3" in text
