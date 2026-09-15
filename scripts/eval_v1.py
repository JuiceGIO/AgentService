"""评测 v1：
1) 意图识别基线：golden_set 110 条（规则引擎）→ 准确率 + 分意图
2) 单 Agent(ReAct·规则) vs 多 Agent(编排器) 对比实验（18 个场景，强制规则模式保证可复现）
   指标：回答覆盖(expect_contains)、转人工判定一致、工具零错误、平均步数/耗时
运行：.\\backend\\.venv\\Scripts\\python.exe scripts\\eval_v1.py
"""

import asyncio
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.agent.orchestrator import MultiAgentOrchestrator  # noqa: E402
from app.agent.react import ReActAgent  # noqa: E402
from app.agent.router import INTENT_LABELS, Router, detect_intent_rule  # noqa: E402
from app.agent.tools import MCPToolRegistry  # noqa: E402

GOLDEN = ROOT / "docs" / "golden_set.json"
SCENARIOS = ROOT / "docs" / "compare_scenarios.json"
REPORT_DIR = ROOT / "docs" / "eval_reports"


def run_golden() -> tuple:
    data = json.loads(GOLDEN.read_text(encoding="utf-8"))
    cases = data["cases"]
    correct = 0
    per_intent = {}
    for c in cases:
        intent, _ = detect_intent_rule(c["query"])
        ok = intent == c["intent"]
        correct += int(ok)
        bucket = per_intent.setdefault(c["intent"], {"total": 0, "correct": 0})
        bucket["total"] += 1
        bucket["correct"] += int(ok)

    total = len(cases)
    acc = correct / total
    lines = [f"golden set：{total} 条，正确 {correct} 条，意图准确率 {acc:.1%}"]
    for intent, label in INTENT_LABELS.items():
        b = per_intent.get(intent, {"total": 0, "correct": 0})
        acc_i = b["correct"] / b["total"] if b["total"] else 0
        lines.append(f"  {label}: {b['correct']}/{b['total']} = {acc_i:.1%}")
    result = {
        "total": total,
        "correct": correct,
        "accuracy": round(acc, 4),
        "per_intent": {k: v for k, v in per_intent.items()},
    }
    return result, "\n".join(lines)


def step_has_error(steps: list) -> bool:
    return any(
        "error" in str(s.get("result") or {}) or "超时" in str(s.get("result") or {})
        for s in steps
    )


async def run_comparison() -> tuple:
    scenarios = json.loads(SCENARIOS.read_text(encoding="utf-8"))["scenarios"]
    rows = []
    agg = {
        "single": {"covered": 0, "escalate_ok": 0, "tool_error": 0, "steps": 0, "seconds": 0.0},
        "multi": {"covered": 0, "escalate_ok": 0, "tool_error": 0, "steps": 0, "seconds": 0.0},
    }

    async with MCPToolRegistry() as registry:
        for sc in scenarios:
            row = {
                "id": sc["id"],
                "query": sc["query"],
                "expected_intent": sc["intent"],
                "expected_escalate": sc["escalate"],
            }
            for kind in ("single", "multi"):
                start = time.perf_counter()
                if kind == "single":
                    agent = ReActAgent(registry, use_llm=False)
                    res = await agent.run(sc["query"])
                else:
                    orch = MultiAgentOrchestrator(registry, router=Router(use_llm=False))
                    res = await orch.run(sc["query"])
                elapsed = round(time.perf_counter() - start, 3)
                reply = res.reply
                covered = any(p in reply for p in sc["expect_contains"])
                escalate_ok = res.escalated == sc["escalate"]
                err = step_has_error(res.steps)
                row[kind] = {
                    "reply": reply[:100],
                    "covered": covered,
                    "escalate": res.escalated,
                    "escalate_ok": escalate_ok,
                    "steps": len(res.steps),
                    "tool_error": err,
                    "seconds": elapsed,
                }
                agg[kind]["covered"] += int(covered)
                agg[kind]["escalate_ok"] += int(escalate_ok)
                agg[kind]["tool_error"] += int(err)
                agg[kind]["steps"] += len(res.steps)
                agg[kind]["seconds"] += elapsed
            rows.append(row)

    n = len(scenarios)
    summary = {}
    for kind, a in agg.items():
        summary[kind] = {
            "coverage_rate": round(a["covered"] / n, 4),
            "escalate_accuracy": round(a["escalate_ok"] / n, 4),
            "tool_error_rate": round(a["tool_error"] / n, 4),
            "avg_steps": round(a["steps"] / n, 2),
            "total_seconds": round(a["seconds"], 2),
            "avg_seconds": round(a["seconds"] / n, 3),
        }
    return {"scenario_count": n, "summary": summary, "rows": rows}, rows


def print_rows(rows: list) -> None:
    print(f"\n{'场景':<5}{'预期':<14}{'单Agent(覆盖/转人工/错/步)':<28}{'多Agent(覆盖/转人工/错/步)'}")
    for r in rows:
        s = r["single"]
        m = r["multi"]
        print(
            f"{r['id']:<5}{r['expected_intent']:<12}"
            f"{('Y' if s['covered'] else 'N'):<2}{('Y' if s['escalate_ok'] else 'N'):<4}"
            f"{('E' if s['tool_error'] else '.'):<3}{s['steps']:<3}"
            f"{('Y' if m['covered'] else 'N'):<2}{('Y' if m['escalate_ok'] else 'N'):<4}"
            f"{('E' if m['tool_error'] else '.'):<3}{m['steps']}"
        )


async def main_async():
    golden, golden_text = run_golden()
    print(golden_text)
    print("\n--- 单 Agent vs 多 Agent 对比（Y=达标 N=不达标 E=工具错误）---")
    comparison, rows = await run_comparison()
    print_rows(rows)
    print("\n汇总：")
    for kind, s in comparison["summary"].items():
        print(
            f"  {kind:<7} 回答覆盖 {s['coverage_rate']:.1%} | 转人工判定一致 {s['escalate_accuracy']:.1%} "
            f"| 工具错误率 {s['tool_error_rate']:.1%} | 平均步数 {s['avg_steps']} | 平均耗时 {s['avg_seconds']}s"
        )

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report = {
        "name": "评测 v3（200 条语义口径 golden + 单 Agent vs 多 Agent 对比）",
        "date": "2026-09-03",
        "golden": golden,
        "comparison": comparison,
    }
    out = REPORT_DIR / "golden200_eval_v2.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n报告已落档：{out}")

    ok = (
        golden["accuracy"] >= 0.85
        and comparison["summary"]["single"]["coverage_rate"] >= 0.75
        and comparison["summary"]["multi"]["coverage_rate"] >= 0.75
    )
    return ok


def main():
    ok = asyncio.run(main_async())
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
