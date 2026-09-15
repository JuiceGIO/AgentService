"""全流程 12 项验收预跑（真实服务联调）。

前置：Python（默认 8000）与 Java（默认 8080）都要运行；SLA 用例约需 40-75s。
用法：python scripts/acceptance_12.py [--python-url http://127.0.0.1:8000] [--java-url http://127.0.0.1:8080]
"""

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent


def check(name: str, fn) -> bool:
    try:
        fn()
        print(f"[PASS] {name}")
        return True
    except Exception as exc:
        print(f"[FAIL] {name} -> {exc}")
        return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--python-url", default="http://127.0.0.1:8000")
    parser.add_argument("--java-url", default="http://127.0.0.1:8080")
    args = parser.parse_args()
    py, java = args.python_url.rstrip("/"), args.java_url.rstrip("/")

    results = []
    client = httpx.Client(timeout=90.0)

    def c1():
        r = client.get(py + "/ping")
        assert r.status_code == 200 and r.json().get("status") == "ok"

    results.append(check("1. Python /ping 健康", c1))

    def c2():
        r = client.get(java + "/tickets")
        assert r.status_code == 200

    results.append(check("2. Java 工单服务可达", c2))

    def c3():
        r = client.get(py + "/")
        assert r.status_code == 200 and "ticket-panel" in r.text and "v=0.7.0" in r.text

    results.append(check("3. 工作台页面 v0.7 可访问", c3))

    def c4():
        r = client.post(py + "/api/chat", json={"message": "我的订单到哪了", "session_id": "acc-day19"})
        data = r.json()
        assert r.status_code == 200 and "物流" in data.get("reply", "") and len(data.get("steps", [])) >= 1

    results.append(check("4. 对话→物流查询有工具步骤与业务回答", c4))

    escalate_id = {}

    def c5():
        r = client.post(py + "/api/chat", json={"message": "我要投诉，请升级处理", "session_id": "acc-escalate"})
        data = r.json()
        assert data.get("escalated") is True and data.get("ticket", {}).get("ok") is True
        escalate_id["id"] = data["ticket"]["ticket"]["id"]

    results.append(check("5. 投诉对话→自动建单", c5))

    def c6():
        r = client.get(java + "/tickets", params={"sessionId": "acc-escalate"})
        tickets = r.json()
        assert r.status_code == 200 and any(t["id"] == escalate_id["id"] for t in tickets)

    results.append(check("6. Java 按会话可查到该工单", c6))

    def c7():
        r = client.post(java + f"/tickets/{escalate_id['id']}/transition", json={"to": "PROCESSING"})
        assert r.status_code == 200 and r.json().get("status") == "PROCESSING"

    results.append(check("7. 工单合法流转 NEW→PROCESSING", c7))

    def c8():
        t = client.post(java + "/tickets", json={"sessionId": "acc-409", "title": "非法跳转", "category": "complaint", "priority": "high"}).json()
        r = client.post(java + f"/tickets/{t['id']}/transition", json={"to": "REFUNDED"})
        assert r.status_code == 409

    results.append(check("8. 非法流转返回 409", c8))

    def c9():
        t = client.post(java + "/tickets", json={"sessionId": "acc-sla", "title": "SLA升级验收", "category": "complaint", "priority": "high"}).json()
        deadline = time.time() + 80
        while time.time() < deadline:
            cur = client.get(java + f"/tickets/{t['id']}").json()
            if cur.get("status") == "ESCALATED" or any("ESCALATE_TIMEOUT" in a for a in cur.get("actions", [])):
                return
            time.sleep(5)
        raise AssertionError("工单未在 80s 内超时升级")

    results.append(check("9. SLA 超时自动升级（≤80s）", c9))

    def c10():
        job = client.post(py + "/api/tasks", json={"type": "noop", "args": {"steps": 3, "interval": 0.05}}).json()
        deadline = time.time() + 10
        while time.time() < deadline:
            cur = client.get(py + f"/api/tasks/{job['id']}").json()
            if cur.get("status") in ("succeeded", "failed"):
                assert cur["status"] == "succeeded" and cur.get("progress") == 100
                return
            time.sleep(0.3)
        raise AssertionError("任务超时")

    results.append(check("10. 异步任务队列 noop 全生命周期", c10))

    def c11():
        job = client.post(py + "/api/delayed", json={"type": "echo_delayed", "args": {"echo": "acc", "steps": 1}, "delay_seconds": 1}).json()
        deadline = time.time() + 10
        while time.time() < deadline:
            cur = client.get(py + f"/api/delayed/{job['id']}").json()
            if cur.get("status") in ("succeeded", "failed"):
                assert cur["status"] == "succeeded"
                return
            time.sleep(0.3)
        raise AssertionError("延迟任务超时")

    results.append(check("11. MQ 延迟任务到点执行", c11))

    def c12():
        env = dict(os.environ)
        env["PYTHONIOENCODING"] = "utf-8"
        proc = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "run_eval.py")],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            env=env, timeout=60,
        )
        assert proc.returncode == 0 and "99.0%" in proc.stdout

    results.append(check("12. golden 200 条评测通过", c12))

    client.close()
    passed = sum(results)
    print(f"\n验收汇总：{passed}/12 通过")
    sys.exit(0 if passed == 12 else 1)


if __name__ == "__main__":
    main()
