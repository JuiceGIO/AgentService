"""优化①：规则引擎 vs LLM（DeepSeek）vs 混合路由 三路意图对比。

混合路由 = 规则先判（快、零成本），仅当“低置信度/fallback/命中语义难例白名单”才调 LLM；
脚本会统计混合模式真实的 LLM 调用次数与触发率。

前置：本机 .env 已配置 OPENAI_API_KEY / OPENAI_BASE_URL（需能联网，勿在离线沙箱跑）。
用法：
  python scripts/compare_llm_vs_rule.py --limit 60
  python scripts/compare_llm_vs_rule.py --full
  python scripts/compare_llm_vs_rule.py --dataset docs/independent_golden.json
"""

import argparse
import asyncio
import json
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
REPORT_DIR = ROOT / "docs" / "eval_reports"

import app.agent.llm as llm_mod  # noqa: E402

from app.agent.llm import OpenAIChatLLM, parse_action  # noqa: E402
from app.agent.router import INTENT_LABELS, ROUTER_PROMPT, Router, detect_intent_rule  # noqa: E402


def load_golden(path: Path):
    data = json.loads(path.read_text(encoding="utf-8"))
    return data["meta"], data["cases"]


def parse_intent(raw: str):
    action = parse_action(raw or "")
    if not isinstance(action, dict):
        return None
    intent = action.get("intent")
    return intent if intent in INTENT_LABELS else None


async def llm_classify(llm: OpenAIChatLLM, sem, text: str):
    async with sem:
        t0 = time.perf_counter()
        try:
            raw = await llm.complete(
                [
                    {"role": "system", "content": ROUTER_PROMPT},
                    {"role": "user", "content": text},
                ]
            )
            intent = parse_intent(raw)
            error = None if intent else f"解析失败: {raw[:80]}"
        except Exception as exc:
            intent, error = None, str(exc)[:120]
        return intent, error, time.perf_counter() - t0


async def hybrid_classify(router: Router, sem, text: str):
    async with sem:
        intent, _conf, _esc = await router.route(text)
    return intent


async def main_async(args):
    llm = OpenAIChatLLM()
    if not llm.available():
        print("未检测到 LLM 配置：请确认 .env 已填 OPENAI_API_KEY / OPENAI_BASE_URL")
        return 1

    meta, cases = load_golden(Path(args.dataset))
    if not args.full:
        cases = cases[: args.limit]

    sem = asyncio.Semaphore(args.concurrency)
    print(f"数据集：{meta.get('name', args.dataset)}")
    print(f"评测语料：{len(cases)} 条（规则 vs LLM vs 混合）")

    llm_results = await asyncio.gather(
        *(llm_classify(llm, sem, c["query"]) for c in cases), return_exceptions=False
    )

    counter = {"calls": 0}
    orig_complete = llm_mod.OpenAIChatLLM.complete

    async def counted_complete(self, messages):
        counter["calls"] += 1
        return await orig_complete(self, messages)

    llm_mod.OpenAIChatLLM.complete = counted_complete
    try:
        router = Router(use_llm=True)
        hybrid_results = await asyncio.gather(
            *(hybrid_classify(router, sem, c["query"]) for c in cases)
        )
    finally:
        llm_mod.OpenAIChatLLM.complete = orig_complete

    rule_correct = llm_correct = hybrid_correct = 0
    per = {}
    rows = []
    llm_lat = []
    for idx, (c, (llm_intent, llm_error, lat)) in enumerate(zip(cases, llm_results)):
        rule_intent, _ = detect_intent_rule(c["query"])
        hybrid_intent = hybrid_results[idx]
        rule_ok = rule_intent == c["intent"]
        llm_ok = llm_intent == c["intent"]
        hybrid_ok = hybrid_intent == c["intent"]
        rule_correct += int(rule_ok)
        llm_correct += int(llm_ok)
        hybrid_correct += int(hybrid_ok)
        llm_lat.append(lat)
        bucket = per.setdefault(c["intent"], {"total": 0, "rule": 0, "llm": 0, "hybrid": 0})
        bucket["total"] += 1
        bucket["rule"] += int(rule_ok)
        bucket["llm"] += int(llm_ok)
        bucket["hybrid"] += int(hybrid_ok)
        if not (rule_ok and llm_ok and hybrid_ok):
            rows.append({
                "id": c["id"], "query": c["query"], "expect": c["intent"],
                "rule": rule_intent, "rule_ok": rule_ok,
                "llm": llm_intent, "llm_error": llm_error, "llm_ok": llm_ok,
                "hybrid": hybrid_intent, "hybrid_ok": hybrid_ok,
            })

    total = len(cases)
    avg_lat = sum(llm_lat) / len(llm_lat) if llm_lat else 0
    print(f"\n规则：{rule_correct}/{total} = {rule_correct / total:.1%}")
    print(f"LLM ：{llm_correct}/{total} = {llm_correct / total:.1%} ｜ 全量调用 {total} 次 ｜ 平均单次 {avg_lat:.2f}s")
    print(f"混合：{hybrid_correct}/{total} = {hybrid_correct / total:.1%} ｜ 实际 LLM 调用 {counter['calls']} 次（触发率 {counter['calls'] / total:.0%}）")

    print("\n分意图：")
    for intent, label in INTENT_LABELS.items():
        b = per.get(intent, {"total": 0, "rule": 0, "llm": 0, "hybrid": 0})
        if b["total"]:
            print(f"  {label}: 规则 {b['rule']}/{b['total']} | LLM {b['llm']}/{b['total']} | 混合 {b['hybrid']}/{b['total']}")

    print(f"\n不一致用例 {len(rows)} 条（前 15）：")
    for r in rows[:15]:
        print(f"  #{r['id']} {r['query']} | 期望={r['expect']} 规则={r['rule']} LLM={r['llm'] or r['llm_error']} 混合={r['hybrid']}")

    report = {
        "name": "规则 vs LLM vs 混合路由 意图对比",
        "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "dataset": meta.get("name", args.dataset),
        "total": total,
        "rule_accuracy": round(rule_correct / total, 4),
        "llm_accuracy": round(llm_correct / total, 4),
        "hybrid_accuracy": round(hybrid_correct / total, 4),
        "hybrid_llm_calls": counter["calls"],
        "hybrid_llm_trigger_rate": round(counter["calls"] / total, 4),
        "per_intent": per,
        "diff_rows": rows,
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    name = "independent" if "independent" in str(args.dataset) else "latest"
    out = REPORT_DIR / f"llm_vs_rule_{name}.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n报告已落档：{out}")
    return 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default=str(ROOT / "docs" / "golden_set.json"),
                        help="评测集路径；独立人工集用 docs/independent_golden.json")
    parser.add_argument("--limit", type=int, default=60)
    parser.add_argument("--concurrency", type=int, default=6)
    parser.add_argument("--full", action="store_true", help="全量")
    args = parser.parse_args()
    sys.exit(asyncio.run(main_async(args)))


if __name__ == "__main__":
    main()
