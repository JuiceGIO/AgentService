"""工程化门禁：一条命令跑核心质量检查。

顺序：单元测试(unittest) → golden 评测 → 安全审计 → （Java 在跑则）回归套件。
用法：python scripts/test_all.py [--require-java]
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


def run_stage(name, args, timeout=240) -> dict:
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.run(
        [PY, *args], capture_output=True, text=True,
        encoding="utf-8", errors="replace", env=env, timeout=timeout,
    )
    tail = (proc.stdout + proc.stderr).strip().splitlines()[-5:]
    ok = proc.returncode == 0
    print(f"[{'PASS' if ok else 'FAIL'}] {name}")
    for line in tail:
        print("   ", line)
    return {"name": name, "status": "pass" if ok else "fail", "exit": proc.returncode, "tail": tail}


def java_up() -> bool:
    try:
        import httpx

        return httpx.get("http://127.0.0.1:8080/tickets", timeout=3).status_code == 200
    except Exception:
        return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--require-java", action="store_true", help="Java 未运行时也判失败")
    args = parser.parse_args()

    stages = [
        run_stage("unit_tests", ["-m", "unittest", "discover", "-s", str(ROOT / "tests")]),
        run_stage("golden_baseline", [str(ROOT / "scripts" / "run_eval.py")]),
        run_stage("security_audit", [str(ROOT / "scripts" / "security_audit.py")]),
    ]

    java_ok = java_up()
    print(f"\nJava 8080 可用：{java_ok}")
    if java_ok:
        stages.append(run_stage("regression_suite", [str(ROOT / "scripts" / "run_regression.py")], timeout=300))
    elif args.require_java:
        stages.append({"name": "regression_suite", "status": "fail", "exit": 1,
                       "reason": "java_down_but_required", "tail": []})

    core_fail = [s for s in stages if s["status"] == "fail"]
    print(f"\n门禁汇总：{len(stages) - len(core_fail)}/{len(stages)} 通过")

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    out = REPORT_DIR / "gate_latest.json"
    out.write_text(
        json.dumps({"name": "工程化门禁", "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "require_java": args.require_java, "java_up": java_ok, "stages": stages},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"报告已落档：{out}")
    sys.exit(1 if core_fail else 0)


if __name__ == "__main__":
    main()
