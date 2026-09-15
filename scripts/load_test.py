"""并发压测：对 Python/Java 关键端点做并发请求，如实记录吞吐与延迟分位。

用法：
  python scripts/load_test.py                      # 轻量端点，默认并发 500、每端点 500 次
  python scripts/load_test.py --with-chat          # 追加 /api/chat 压测（并发上限 20，避免 MCP 子进程爆炸）
  python scripts/load_test.py --concurrency 200 --requests 400 --java-url http://127.0.0.1:8080

报告落档 docs/eval_reports/load_test_<时间戳>.json
"""

import argparse
import asyncio
import json
import statistics
import time
from datetime import datetime
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
REPORT_DIR = ROOT / "docs" / "eval_reports"


def percentile(sorted_lat, p):
    if not sorted_lat:
        return 0.0
    idx = min(len(sorted_lat) - 1, max(0, int(len(sorted_lat) * p)))
    return round(sorted_lat[idx] * 1000, 1)


async def worker(client, endpoint, sem, results):
    method = endpoint["method"]
    kwargs = {"url": endpoint["url"]}
    if method == "POST":
        kwargs["json"] = endpoint.get("json", {})
    async with sem:
        t0 = time.perf_counter()
        try:
            resp = await client.request(method, timeout=30.0, **kwargs)
            ok = resp.status_code < 500
            error = "" if ok else f"HTTP {resp.status_code}"
        except Exception as exc:
            ok = False
            error = str(exc)[:120]
        lat = time.perf_counter() - t0
    results.append({"ok": ok, "latency": lat, "error": error})


async def run_endpoint(client, endpoint, count, concurrency):
    sem = asyncio.Semaphore(concurrency)
    results = []
    start = time.perf_counter()
    await asyncio.gather(*(worker(client, endpoint, sem, results) for _ in range(count)))
    elapsed = time.perf_counter() - start
    ok_n = sum(1 for r in results if r["ok"])
    lats = sorted(r["latency"] for r in results)
    errors = [r["error"] for r in results if not r["ok"]][:5]
    return {
        "name": endpoint["name"],
        "url": endpoint["url"],
        "requests": count,
        "concurrency": concurrency,
        "success": ok_n,
        "failed": count - ok_n,
        "error_samples": errors,
        "total_seconds": round(elapsed, 3),
        "rps": round(ok_n / elapsed, 1) if elapsed else 0,
        "avg_ms": round(statistics.mean(lats) * 1000, 1) if lats else 0,
        "p50_ms": percentile(lats, 0.50),
        "p95_ms": percentile(lats, 0.95),
        "p99_ms": percentile(lats, 0.99),
    }


async def main_async(args):
    endpoints = [
        {"name": "python_ping", "method": "GET", "url": args.python_url.rstrip("/") + "/ping"},
        {"name": "java_tickets", "method": "GET", "url": args.java_url.rstrip("/") + "/tickets"},
    ]
    if args.with_chat:
        endpoints.append({
            "name": "python_chat_logistics",
            "method": "POST",
            "url": args.python_url.rstrip("/") + "/api/chat",
            "json": {"message": "我的订单到哪了", "session_id": "load-test"},
        })

    async with httpx.AsyncClient() as client:
        results = []
        for ep in endpoints:
            count = args.requests
            conc = args.concurrency
            if ep["name"] == "python_chat_logistics":
                count = min(count, 60)
                conc = min(conc, 20)  # 每轮 chat 会拉起 MCP 子进程，避免把本机打挂
            print(f"压测 {ep['name']}: 请求 {count} 次 / 并发 {conc}")
            results.append(await run_endpoint(client, ep, count, conc))

    report = {
        "name": "并发压测",
        "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "note": "按本机实际结果如实记录；chat 类端点为防 MCP 子进程打爆，并发封顶 20",
        "results": results,
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    out = REPORT_DIR / ("load_test_" + datetime.now().strftime("%Y%m%d_%H%M%S") + ".json")
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n结果：")
    for r in results:
        print(
            f"  {r['name']:<24} 成功 {r['success']}/{r['requests']} | "
            f"RPS {r['rps']} | p50 {r['p50_ms']}ms | p95 {r['p95_ms']}ms | p99 {r['p99_ms']}ms"
        )
    print(f"\n报告已落档：{out}")
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--python-url", default="http://127.0.0.1:8000")
    parser.add_argument("--java-url", default="http://127.0.0.1:8080")
    parser.add_argument("--concurrency", type=int, default=500)
    parser.add_argument("--requests", type=int, default=500)
    parser.add_argument("--with-chat", action="store_true")
    args = parser.parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
