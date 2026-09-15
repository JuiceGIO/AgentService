"""安全审计：发布前自动检查仓库是否包含密钥/敏感文件。

检查项：
1) 高置信密钥（OpenAI sk- / AWS AKIA / GitHub token / 私钥块）
2) 是否跟踪了 .env / *.pem / *.key 等敏感文件
3) .gitignore 是否覆盖 .env、.venv、logs、backend/data
4) 中危线索（password/token/api_key=...）仅列 INFO 供人工复核（演示凭据允许）

用法：python scripts/security_audit.py
"""

import json
import re
import subprocess
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPORT_DIR = ROOT / "docs"

HIGH_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9]{16,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"-----BEGIN (RSA|EC|OPENSSH|PRIVATE) KEY-----"),
]
INFO_PATTERN = re.compile(
    r"(?i)(api[_-]?key|secret|token|password|passwd)\s*[:=]\s*(\S+)"
)
PLACEHOLDER = {"your-api-key", "xxx", "changeme", "example", "postgres", "demo", "none", "null", "true", "false"}
SENSITIVE_NAMES = (".env", ".pem", ".key", ".p12", ".pfx", "id_rsa", "credentials")
INFO_IGNORE = {"scripts/security_audit.py", "docs/security_audit_latest.json"}


def tracked_files() -> list:
    out = subprocess.run(
        ["git", "-c", f"safe.directory={ROOT}", "-C", str(ROOT), "ls-files"],
        capture_output=True, text=True, encoding="utf-8", timeout=30,
    )
    return [p for p in out.stdout.splitlines() if p]


def main():
    files = tracked_files()
    high_hits = []
    info_hits = []
    sensitive_tracked = []

    for rel in files:
        name = Path(rel).name.lower()
        if any(name.startswith(s) or name.endswith(s) for s in SENSITIVE_NAMES) and rel != ".env.example":
            sensitive_tracked.append(rel)
        path = ROOT / rel
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            for pat in HIGH_PATTERNS:
                if pat.search(line):
                    high_hits.append(f"{rel}:{lineno}: {line.strip()[:120]}")
            m = INFO_PATTERN.search(line)
            if m:
                value = m.group(2).strip("\"'` ,;")
                low = value.lower().strip("{}")
                if low not in PLACEHOLDER and len(value) >= 6 and not value.startswith(("${", "<")):
                    if rel not in INFO_IGNORE:
                        info_hits.append(f"{rel}:{lineno}: {line.strip()[:120]}")

    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    coverage = {
        ".env": ".env" in gitignore,
        ".venv": ".venv" in gitignore,
        "logs": "logs" in gitignore,
        "backend/data": "backend/data" in gitignore,
    }

    report = {
        "name": "安全审计",
        "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "tracked_files": len(files),
        "high_risk_secrets": high_hits,
        "sensitive_tracked": sensitive_tracked,
        "gitignore_coverage": coverage,
        "info_review": info_hits,
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    out = REPORT_DIR / "security_audit_latest.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"跟踪文件数：{len(files)}")
    print(f"高置信密钥：{len(high_hits)} 处")
    for h in high_hits:
        print("  !", h)
    print(f"敏感文件被跟踪：{len(sensitive_tracked)} 个")
    for s in sensitive_tracked:
        print("  !", s)
    print("gitignore 覆盖：", coverage)
    print(f"待人工复核 INFO：{len(info_hits)} 条")
    for i in info_hits[:15]:
        print("  ?", i)
    print(f"报告已落档：{out}")

    ok = not high_hits and not sensitive_tracked and all(coverage.values())
    print("\n审计结论：", "通过（含演示凭据等 INFO 需人工确认）" if ok else "未通过")
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
