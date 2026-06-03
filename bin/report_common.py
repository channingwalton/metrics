"""Shared helpers for parsing a reports directory.

Imported by aggregate.py (markdown/CSV) and report_pdf.py (PDF) so the report
parsing lives in one place.
"""
import json
from pathlib import Path

CCN_WARN = 15  # cyclomatic-complexity threshold for a "hotspot"

# dependency-cruiser's output carries only the rule name, so describe them here.
DEPCRUISE_DESC = {
    "no-circular": "Circular dependency between modules.",
    "no-orphans": "Module not reachable from anywhere (likely dead code).",
    "no-deprecated-core": "Depends on a deprecated Node core module.",
    "not-to-unresolvable": "Imports a module that cannot be resolved.",
    "no-non-package-json": "Imports an npm package not declared in package.json.",
    "not-to-dev-dep": "Production code depends on a devDependency.",
    "not-to-test": "Production code imports a test file.",
    "domain-not-to-infra": "Domain layer depends on infrastructure.",
}


def load_json(p):
    try:
        return json.loads(Path(p).read_text())
    except Exception:
        return None


def ast_grep_findings(out):
    """Return ast-grep finding dicts. Tolerant of both the `--json` array form
    and the older `--json=stream` (one object per line) form."""
    p = Path(out) / "ast-grep.json"
    if not p.exists():
        return []
    txt = p.read_text().strip()
    if not txt:
        return []
    try:  # array form
        data = json.loads(txt)
        if isinstance(data, list):
            return data
    except Exception:
        pass
    findings = []  # stream form
    for line in txt.splitlines():
        line = line.strip().rstrip(",")
        if not line or line in "[]":
            continue
        try:
            findings.append(json.loads(line))
        except Exception:
            pass
    return findings


def triggered_rules(out):
    """Distinct dependency-rule ids that fired -> (tool, description)."""
    out = Path(out)
    rules = {}
    for d in ast_grep_findings(out):
        rules.setdefault(d.get("ruleId", "?"), ("ast-grep", d.get("message", "")))
    sg = load_json(out / "semgrep.json")
    if sg:
        for r in sg.get("results", []):
            rid = r.get("check_id", "?").split(".")[-1]
            rules.setdefault(rid, ("semgrep", r.get("extra", {}).get("message", "")))
    dc = load_json(out / "depcruise.json")
    if dc:
        for v in dc.get("summary", {}).get("violations", []):
            name = v.get("rule", {}).get("name", "?")
            rules.setdefault(name, ("dependency-cruiser", DEPCRUISE_DESC.get(name, "")))
    return rules
