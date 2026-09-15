"""一键回归：评测基线 + 单/多 Agent 对比 + 历史验收脚本（Java 在跑时）。

用法：python scripts/run_regression.py        # 常规
      python scripts/run_regression.py --full # 追加 SLA 超时（约 80s）
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPORT_DIR = ROOT / "docs" / "eval_reports"

PY = sys.executable

SCRIPTS = [
    ("golden_baseline", "scripts/run_eval.py", False),
    ("eval_v1_compare", "scripts/eval_v1.py", False),
    ("autoticket", "scripts/test_autoticket.py", True),
    ("task_queue", "scripts/test_task_queue.py", True),
    ("delayed_queue", "scripts/test_delayed_queue.py", True),
]


def java_up() -> bool:
    try:
        import httpx

        return httpx.get("http://127.0.0.1:8080/tickets", timeout=3).status_code == 200
    except Exception:
        return False


def run_one(name: str, rel: str, needs_java: bool, java_ok: bool):
    if needs_java and not java_ok:
        print(f"[SKIP] {name}（Java 未运行）")
        return {"name": name, "status": "skipped", "reason": "java_down"}
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.run(
        [PY, str(ROOT / rel)], capture_output=True, text=True,
        encoding="utf-8", errors="replace", env=env, timeout=180,
    )
    tail = (proc.stdout + proc.stderr).strip().splitlines()
    tail = tail[-6:]
    print(f"[{'PASS' if proc.returncode == 0 else 'FAIL'}] {name}")
    for line in tail:
        print("   ", line)
    return {
        "name": name,
        "status": "pass" if proc.returncode == 0 else "fail",
        "exit": proc.returncode,
        "tail": tail,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--full", action="store_true", help="追加 SLA 超时验收（约 80s）")
    args = parser.parse_args()

    java_ok = java_up()
    print(f"Java 8080 可用：{java_ok}\n")
    items = list(SCRIPTS)
    if args.full:
        items.append(("sla_escalation", "scripts/test_sla_escalation.py", True))

    results = [run_one(name, rel, need, java_ok) for name, rel, need in items]
    fail = [r for r in results if r["status"] == "fail"]
    skipped = [r for r in results if r["status"] == "skipped"]
    print(f"\n汇总：{len(results) - len(fail) - len(skipped)} 过 / {len(fail)} 失败 / {len(skipped)} 跳过")

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    out = REPORT_DIR / "regression_latest.json"
    out.write_text(
        json.dumps({"date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "results": results},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"报告已落档：{out}")
    sys.exit(1 if fail else 0)


if __name__ == "__main__":
    main()
