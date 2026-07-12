from __future__ import annotations

import json
import shutil
from dataclasses import asdict
from pathlib import Path

from symnav_bench.report.dashboard_payload import DashboardPayload


class StaticDashboardWriter:
    def write(self, payload: DashboardPayload, out_dir: Path) -> list[Path]:
        out_dir.mkdir(parents=True, exist_ok=True)
        static_source = Path(__file__).parents[1] / "dashboard" / "static"
        static_target = out_dir / "static"
        if static_target.exists():
            shutil.rmtree(static_target)
        shutil.copytree(static_source, static_target)
        template = (static_source / "index.html").read_text(encoding="utf-8")
        serialized = json.dumps(asdict(payload), sort_keys=True).replace("<", "\\u003c")
        index = template.replace("__DASHBOARD_PAYLOAD__", serialized)
        index_path = out_dir / "index.html"
        index_path.write_text(index, encoding="utf-8")
        data_path = out_dir / "analysis.json"
        data_path.write_text(
            json.dumps(asdict(payload), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return [index_path, data_path, *sorted(static_target.iterdir())]
