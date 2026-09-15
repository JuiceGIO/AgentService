"""评测 v2-golden：golden set（200 条）意图识别基线（规则引擎），结果落档 docs/eval_reports/。"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.agent.router import INTENT_LABELS, detect_intent_rule

GOLDEN = ROOT / "docs" / "golden_set.json"
REPORT_DIR = ROOT / "docs" / "eval_reports"


def main():
    data = json.loads(GOLDEN.read_text(encoding="utf-8"))
    cases = data["cases"]
    correct = 0
    per_intent = {}
    for c in cases:
        intent, _conf = detect_intent_rule(c["query"])
        ok = intent == c["intent"]
        correct += int(ok)
        bucket = per_intent.setdefault(c["intent"], {"total": 0, "correct": 0})
        bucket["total"] += 1
        bucket["correct"] += int(ok)

    total = len(cases)
    acc = correct / total
    print(f"评测集：{total} 条，正确 {correct} 条，意图准确率 {acc:.1%}")
    for intent, label in INTENT_LABELS.items():
        b = per_intent.get(intent, {"total": 0, "correct": 0})
        acc_i = b["correct"] / b["total"] if b["total"] else 0
        print(f"  {label}: {b['correct']}/{b['total']} = {acc_i:.1%}")

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report = {
        "name": "意图识别基线（200 条，语义口径 v1，规则引擎）",
        "date": "2026-09-03",
        "total": total,
        "correct": correct,
        "accuracy": round(acc, 4),
        "per_intent": {k: v for k, v in per_intent.items()},
    }
    out = REPORT_DIR / "golden200_rule_baseline.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"报告已落档：{out}")
    sys.exit(0 if acc >= 0.7 else 1)


if __name__ == "__main__":
    main()
