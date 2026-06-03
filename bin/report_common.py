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


def _as_list(data, *keys):
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in keys:
            value = data.get(key)
            if isinstance(value, list):
                return value
    return []


def _pick(d, *names, default=""):
    if not isinstance(d, dict):
        return default
    for name in names:
        if name in d and d[name] not in (None, ""):
            return d[name]
    return default


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


def shellcheck_findings(out):
    return _as_list(load_json(Path(out) / "shellcheck.json"), "comments")


def actionlint_findings(out):
    return _as_list(load_json(Path(out) / "actionlint.json"), "errors")


def hadolint_findings(out):
    return _as_list(load_json(Path(out) / "hadolint.json"), "results")


def ruff_findings(out):
    return _as_list(load_json(Path(out) / "ruff.json"), "results")


def checkov_findings(out):
    """Return failed Checkov checks from either single-run or multi-run JSON."""
    data = load_json(Path(out) / "checkov.json")
    runs = data if isinstance(data, list) else [data] if isinstance(data, dict) else []
    findings = []
    for run in runs:
        if not isinstance(run, dict):
            continue
        results = run.get("results", {})
        if isinstance(results, dict):
            findings.extend(results.get("failed_checks", []) or [])
        findings.extend(run.get("failed_checks", []) or [])
    return findings


def betterleaks_findings(out):
    data = load_json(Path(out) / "betterleaks.json")
    return _as_list(data, "findings", "Findings", "results", "Results", "leaks", "Leaks")


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


def triggered_check_rules(out):
    """Distinct quality/security rule ids that fired -> (tool, description)."""
    rules = {}

    for f in shellcheck_findings(out):
        code = _pick(f, "code")
        rid = f"SC{code}" if code else "shellcheck"
        rules.setdefault(rid, ("ShellCheck", _pick(f, "message")))

    for f in actionlint_findings(out):
        rid = _pick(f, "kind", "Kind", default="actionlint")
        rules.setdefault(rid, ("actionlint", _pick(f, "message", "Message")))

    for f in hadolint_findings(out):
        rid = _pick(f, "code", "Code", default="hadolint")
        rules.setdefault(rid, ("hadolint", _pick(f, "message", "Message")))

    for f in ruff_findings(out):
        rid = _pick(f, "code", "Code", default="ruff")
        rules.setdefault(rid, ("Ruff", _pick(f, "message", "Message")))

    for f in checkov_findings(out):
        rid = _pick(f, "check_id", "checkId", default="checkov")
        rules.setdefault(rid, ("Checkov", _pick(f, "check_name", "checkName", "message")))

    for f in betterleaks_findings(out):
        rid = _pick(f, "RuleID", "rule_id", "ruleId", "rule", default="betterleaks")
        rules.setdefault(rid, ("Betterleaks", _pick(f, "Description", "description", "message")))

    return rules
