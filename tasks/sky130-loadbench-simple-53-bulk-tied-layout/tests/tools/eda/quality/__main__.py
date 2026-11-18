"""Bounded-process entry point; parent supplies the wall-clock limit."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from . import collect


def main():
    parser = argparse.ArgumentParser(description="Collect GDS-bound engineering facts without running EDA")
    parser.add_argument("--gds", required=True, type=Path)
    parser.add_argument("--lvs-result", required=True, type=Path)
    parser.add_argument("--task", required=True, type=Path)
    parser.add_argument("--task-name", required=True)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--area-report", type=Path)
    args = parser.parse_args()
    area = json.loads(args.area_report.read_text()) if args.area_report else None
    result = collect(args.gds, args.lvs_result, args.task, args.out,
                     task_name=args.task_name, area_report=area)
    print(json.dumps({"status": result["status"], "result": str(args.out / "result.json"),
                      "reason": result.get("reason")}, ensure_ascii=False))
    return 2 if result["status"] == "error" else 0


if __name__ == "__main__":
    raise SystemExit(main())
