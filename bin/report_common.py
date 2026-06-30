"""Shared helpers for parsing a reports directory.

Imported by aggregate.py (markdown/CSV) and report_pdf.py (PDF) so the report
parsing lives in one place.
"""
import json
import xml.etree.ElementTree as ET
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


def cargo_clippy_findings(out):
    return _as_list(load_json(Path(out) / "cargo-clippy.json"), "results")


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


def syft_packages(out):
    data = load_json(Path(out) / "syft.json")
    return _as_list(data, "artifacts", "packages", "components")


def _osv_vuln_severity(vuln):
    severity = _pick(vuln, "severity", default=[])
    if isinstance(severity, list):
        for item in severity:
            if isinstance(item, dict) and item.get("score"):
                return item.get("score")
    db = _pick(vuln, "database_specific", default={})
    if isinstance(db, dict):
        return _pick(db, "severity")
    return _pick(vuln, "severity")


def _osv_group_finding(source, package, ids, vuln):
    name = _pick(package, "name", default="?")
    version = _pick(package, "version")
    ecosystem = _pick(package, "ecosystem")
    primary = ids[0] if ids else _pick(vuln, "id", default="osv")
    summary = _pick(vuln, "summary", "details")
    return {
        "id": primary,
        "ids": ids or [primary],
        "package": name,
        "version": version,
        "ecosystem": ecosystem,
        "source": source,
        "severity": _osv_vuln_severity(vuln),
        "message": summary,
    }


def osv_findings(out):
    data = load_json(Path(out) / "osv-scanner.json")
    findings = []
    for result in _as_list(data, "results"):
        if not isinstance(result, dict):
            continue
        source = _pick(_pick(result, "source", default={}), "path")
        for entry in _as_list(result.get("packages", [])):
            if not isinstance(entry, dict):
                continue
            package = _pick(entry, "package", default={})
            vulns = _as_list(entry.get("vulnerabilities", []))
            by_id = {v.get("id"): v for v in vulns if isinstance(v, dict) and v.get("id")}
            groups = _as_list(entry.get("groups", []))
            if groups:
                for group in groups:
                    ids = group.get("ids", []) if isinstance(group, dict) else []
                    vuln = next((by_id[i] for i in ids if i in by_id), {})
                    findings.append(_osv_group_finding(source, package, ids, vuln))
            else:
                for vuln in vulns:
                    ids = [vuln.get("id", "osv")] if isinstance(vuln, dict) else ["osv"]
                    findings.append(_osv_group_finding(source, package, ids, vuln))
    return findings


def cargo_audit_findings(out):
    data = load_json(Path(out) / "cargo-audit.json")
    runs = data.get("runs", []) if isinstance(data, dict) else []
    findings = []
    for run in runs:
        if not isinstance(run, dict):
            continue
        source = _pick(run, "source")
        report = _pick(run, "report", default={})
        if not isinstance(report, dict):
            continue
        vulnerabilities = _pick(report, "vulnerabilities", default={})
        for item in _as_list(vulnerabilities, "list"):
            if not isinstance(item, dict):
                continue
            advisory = _pick(item, "advisory", default={})
            package = _pick(item, "package", default={})
            aliases = _pick(advisory, "aliases", default=[])
            rid = _pick(advisory, "id")
            if not rid and isinstance(aliases, list) and aliases:
                rid = aliases[0]
            findings.append({
                "id": rid or "cargo-audit",
                "package": _pick(package, "name", default="?"),
                "version": _pick(package, "version"),
                "source": source,
                "severity": _pick(advisory, "severity"),
                "message": _pick(advisory, "title", "description"),
            })
    return findings


def brakeman_findings(out):
    return _as_list(load_json(Path(out) / "brakeman.json"), "warnings")


def spotbugs_findings(out):
    p = Path(out) / "spotbugs.xml"
    if not p.exists():
        return []
    try:
        root = ET.parse(p).getroot()
    except Exception:
        return []
    findings = []
    for bug in root.iter():
        if not bug.tag.endswith("BugInstance"):
            continue
        source = None
        for child in bug.iter():
            if child.tag.endswith("SourceLine"):
                source = child
                break
        findings.append({
            "type": bug.get("type", "spotbugs"),
            "category": bug.get("category", ""),
            "priority": bug.get("priority", ""),
            "rank": bug.get("rank", ""),
            "message": bug.get("message", ""),
            "file": source.get("sourcepath", source.get("sourcefile", "")) if source is not None else "",
            "line": source.get("start", "") if source is not None else "",
        })
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

    for f in cargo_clippy_findings(out):
        rid = _pick(f, "code", default="cargo-clippy")
        rules.setdefault(rid, ("cargo clippy", _pick(f, "message")))

    for f in checkov_findings(out):
        rid = _pick(f, "check_id", "checkId", default="checkov")
        rules.setdefault(rid, ("Checkov", _pick(f, "check_name", "checkName", "message")))

    for f in betterleaks_findings(out):
        rid = _pick(f, "RuleID", "rule_id", "ruleId", "rule", default="betterleaks")
        rules.setdefault(rid, ("Betterleaks", _pick(f, "Description", "description", "message")))

    for f in osv_findings(out):
        rid = _pick(f, "id", default="osv")
        package = _pick(f, "package")
        version = _pick(f, "version")
        package_desc = f"{package}@{version}" if version else package
        message = _pick(f, "message")
        desc = f"{package_desc} - {message}" if message else package_desc
        rules.setdefault(rid, ("OSV-Scanner", desc))

    for f in cargo_audit_findings(out):
        rid = _pick(f, "id", default="cargo-audit")
        package = _pick(f, "package")
        version = _pick(f, "version")
        package_desc = f"{package}@{version}" if version else package
        message = _pick(f, "message")
        desc = f"{package_desc} - {message}" if message else package_desc
        rules.setdefault(rid, ("cargo audit", desc))

    for f in brakeman_findings(out):
        rid = str(_pick(f, "warning_code", "check_name", default="brakeman"))
        rules.setdefault(rid, ("Brakeman", _pick(f, "message")))

    for f in spotbugs_findings(out):
        rid = _pick(f, "type", default="spotbugs")
        rules.setdefault(rid, ("SpotBugs", _pick(f, "message", "category")))

    return rules
