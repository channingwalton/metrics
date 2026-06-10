#!/usr/bin/env python3
"""Aggregate per-tool reports in a reports dir into a single summary.md.

Usage: aggregate.py <reports_dir> <target_dir>

Reads whatever reports are present (all optional) and produces one Markdown
read-out covering every sensor that ran: size/complexity, per-function
cyclomatic complexity, duplication, code smells, and dependency-rule
violations. Missing reports are silently skipped.
"""
import csv
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from report_common import (
    CCN_WARN, actionlint_findings, ast_grep_findings, betterleaks_findings,
    brakeman_findings, checkov_findings, hadolint_findings, load_json,
    osv_findings, ruff_findings, shellcheck_findings, spotbugs_findings,
    syft_packages, triggered_check_rules, triggered_rules,
)


# --------------------------------------------------------------- metrics ---
def scc_section(out: Path) -> str:
    data = load_json(out / "scc.json")
    if not data:
        return ""
    rows = sorted(data, key=lambda d: d.get("Code", 0), reverse=True)
    tot_code = sum(d.get("Code", 0) for d in data)
    tot_files = sum(d.get("Count", 0) for d in data)
    lines = [
        "## Size (scc)\n",
        f"- **{tot_files:,} files**, **{tot_code:,} lines of code**\n",
        "\n| Language | Files | Code | Complexity* |",
        "|---|--:|--:|--:|",
    ]
    for d in rows[:12]:
        lines.append(
            f"| {d.get('Name','?')} | {d.get('Count',0):,} | "
            f"{d.get('Code',0):,} | {d.get('Complexity',0):,} |"
        )
    lines.append(
        "\n_*scc's complexity is a per-language keyword heuristic that tracks "
        "size; it is shown per language but deliberately not summed. Use the "
        "lizard distribution below for a complexity signal._"
    )
    return "\n".join(lines) + "\n"


def lizard_section(out: Path) -> str:
    p = out / "lizard.csv"
    if not p.exists():
        return ""
    hotspots = []
    try:
        with p.open(newline="") as f:
            for row in csv.reader(f):
                # nloc,ccn,token,param,length,location,file,function,...
                if len(row) < 8:
                    continue
                try:
                    ccn = int(row[1])
                except ValueError:
                    continue
                hotspots.append((ccn, int(row[0]), row[7].strip('"'), row[6]))
    except Exception:
        return ""
    if not hotspots:
        return ""
    hotspots.sort(reverse=True)
    ccns = [h[0] for h in hotspots]
    n = len(ccns)
    over = [h for h in hotspots if h[0] >= CCN_WARN]
    tot_ccn = sum(ccns)
    tot_nloc = sum(h[1] for h in hotspots) or 1

    def pctile(vals, q):  # vals sorted desc; nearest-rank
        s = sorted(vals)
        k = max(0, min(len(s) - 1, int(round(q * (len(s) - 1)))))
        return s[k]

    lines = [
        "## Cyclomatic complexity distribution (lizard)\n",
        f"- **{n} functions** analysed\n",
        f"- **max {max(ccns)}**, **p95 {pctile(ccns, 0.95)}**, "
        f"**median {pctile(ccns, 0.5)}**, **mean {tot_ccn/n:.1f}**\n",
        f"- **{len(over)}** function(s) at or above CCN {CCN_WARN} "
        f"({100*len(over)/n:.0f}%)\n",
        f"- density **{tot_ccn/tot_nloc:.2f}** CCN per line of code\n",
        "\nMost complex functions:\n",
        "\n| CCN | NLOC | Function | File |",
        "|--:|--:|---|---|",
    ]
    for ccn, nloc, fn, fl in hotspots[:15]:
        lines.append(f"| {ccn} | {nloc} | `{fn}` | {fl} |")
    return "\n".join(lines) + "\n"


def detekt_section(out: Path) -> str:
    p = out / "detekt.xml"
    if not p.exists():
        return ""
    try:
        root = ET.parse(p).getroot()
    except Exception:
        return ""
    by_rule = Counter()
    total = 0
    for f in root.iter("file"):
        for e in f.iter("error"):
            by_rule[e.get("source", "?").split(".")[-1]] += 1
            total += 1
    if total == 0:
        return "## Kotlin (detekt)\n\n- No findings.\n"
    lines = [
        "## Kotlin complexity & smells (detekt)\n",
        f"- **{total} finding(s)** — top rules:\n",
        "\n| Rule | Count |", "|---|--:|",
    ]
    for rule, n in by_rule.most_common(10):
        lines.append(f"| {rule} | {n} |")
    lines.append(CSV_NOTE)
    return "\n".join(lines) + "\n"


CSV_NOTE = "\n_Per-violation file:line locations are in `findings.csv`._"


def pick(d, *names, default=""):
    if not isinstance(d, dict):
        return default
    for name in names:
        if name in d and d[name] not in (None, ""):
            return d[name]
    return default


def count_findings_section(out: Path, title: str, filename: str, findings, rule_fn,
                           no_msg: str) -> str:
    if not (out / filename).exists():
        return ""
    if not findings:
        return f"## {title}\n\n- {no_msg}\n"
    by_rule = Counter(rule_fn(f) or "?" for f in findings)
    lines = [
        f"## {title}\n",
        f"- **{len(findings)} finding(s)** — top rules:\n",
        "\n| Rule | Count |", "|---|--:|",
    ]
    for rule, n in by_rule.most_common(10):
        lines.append(f"| {rule} | {n} |")
    lines.append(CSV_NOTE)
    return "\n".join(lines) + "\n"


def pmd_section(out: Path) -> str:
    p = out / "pmd.xml"
    if not p.exists():
        return ""
    try:
        root = ET.parse(p).getroot()
    except Exception:
        return ""
    by_rule = Counter()
    for f in root.iter():
        if not f.tag.endswith("file"):
            continue
        for v in f:
            if v.tag.endswith("violation"):
                by_rule[v.get("rule", "?")] += 1
    total = sum(by_rule.values())
    if total == 0:
        return "## Java (PMD)\n\n- No violations.\n"
    lines = [
        "## Java rules (PMD)\n",
        f"- **{total} violation(s)** — top rules:\n",
        "\n| Rule | Count |", "|---|--:|",
    ]
    for rule, n in by_rule.most_common(10):
        lines.append(f"| {rule} | {n} |")
    lines.append(CSV_NOTE)
    return "\n".join(lines) + "\n"


def cpd_section(out: Path) -> str:
    p = out / "cpd.xml"
    if not p.exists():
        return ""
    try:
        root = ET.parse(p).getroot()
    except Exception:
        return ""
    dups = [el for el in root.iter() if el.tag.endswith("duplication")]
    if not dups:
        return "## Duplication (CPD)\n\n- No duplicate blocks over threshold.\n"
    tot_lines = sum(int(d.get("lines", 0)) for d in dups)
    return (
        "## Duplication (CPD)\n\n"
        f"- **{len(dups)} duplicate block(s)**, **{tot_lines} lines** total\n"
        + CSV_NOTE + "\n")


def scapegoat_section(out: Path) -> str:
    p = out / "scapegoat.xml"
    if not p.exists():
        return ""
    try:
        root = ET.parse(p).getroot()
    except Exception:
        return ""
    by_level = Counter()
    by_insp = Counter()
    total = 0
    for el in root.iter():
        if el.tag.endswith("warning"):
            by_level[el.get("level", "?")] += 1
            by_insp[el.get("inspection", "?").split(".")[-1]] += 1
            total += 1
    if total == 0:
        return "## Scala (scapegoat)\n\n- No warnings.\n"
    levels = ", ".join(f"{n} {lv.lower()}" for lv, n in by_level.most_common())
    lines = [
        "## Scala inspections (scapegoat)\n",
        f"- **{total} warning(s)** — {levels}\n",
        "\n| Inspection | Count |", "|---|--:|",
    ]
    for insp, n in by_insp.most_common(15):
        lines.append(f"| {insp} | {n} |")
    return "\n".join(lines) + "\n"


def scalafix_section(out: Path) -> str:
    p = out / "scalafix.txt"
    if not p.exists():
        return ""
    txt = p.read_text()
    errs = txt.lower().count("error")
    if errs == 0:
        return "## Scala lint (scalafix)\n\n- No rule violations.\n"
    return f"## Scala lint (scalafix)\n\n- **{errs}** line(s) mentioning errors; see `scalafix.txt`.\n"


def rubycritic_section(out: Path) -> str:
    d = out / "rubycritic"
    if not d.exists():
        return ""
    js = list(d.rglob("*.json"))
    if not js:
        return "## Ruby (rubycritic)\n\n- Report written to `rubycritic/`.\n"
    data = load_json(js[0])
    mods = data if isinstance(data, list) else data.get("analysed_modules", []) if isinstance(data, dict) else []
    if not mods:
        return "## Ruby (rubycritic)\n\n- Report written to `rubycritic/`.\n"
    def score(m):
        return m.get("complexity", 0) or 0
    mods = sorted(mods, key=score, reverse=True)
    lines = [
        "## Ruby complexity & smells (rubycritic)\n",
        f"- **{len(mods)} modules** analysed\n",
        "\n| Rating | Complexity | Churn | File |", "|---|--:|--:|---|",
    ]
    for m in mods[:15]:
        lines.append(
            f"| {m.get('rating','?')} | {m.get('complexity','?')} | "
            f"{m.get('churn','?')} | {m.get('path') or m.get('name','?')} |"
        )
    return "\n".join(lines) + "\n"


def shellcheck_section(out: Path) -> str:
    return count_findings_section(
        out, "Shell scripts (ShellCheck)", "shellcheck.json", shellcheck_findings(out),
        lambda f: f"SC{pick(f, 'code')}", "No shell issues.")


def actionlint_section(out: Path) -> str:
    return count_findings_section(
        out, "GitHub Actions (actionlint)", "actionlint.json", actionlint_findings(out),
        lambda f: pick(f, "kind", "Kind", default="actionlint"),
        "No workflow issues.")


def hadolint_section(out: Path) -> str:
    return count_findings_section(
        out, "Dockerfiles (hadolint)", "hadolint.json", hadolint_findings(out),
        lambda f: pick(f, "code", "Code", default="hadolint"),
        "No Dockerfile issues.")


def ruff_section(out: Path) -> str:
    return count_findings_section(
        out, "Python quality (Ruff)", "ruff.json", ruff_findings(out),
        lambda f: pick(f, "code", "Code", default="ruff"),
        "No Python lint findings.")


def checkov_section(out: Path) -> str:
    return count_findings_section(
        out, "IaC security (Checkov)", "checkov.json", checkov_findings(out),
        lambda f: pick(f, "check_id", "checkId", default="checkov"),
        "No failed IaC checks.")


def betterleaks_section(out: Path) -> str:
    return count_findings_section(
        out, "Secrets (Betterleaks)", "betterleaks.json", betterleaks_findings(out),
        lambda f: pick(f, "RuleID", "rule_id", "ruleId", "rule", default="betterleaks"),
        "No secrets found.")


def osv_section(out: Path) -> str:
    return count_findings_section(
        out, "Dependency vulnerabilities (OSV-Scanner)", "osv-scanner.json",
        osv_findings(out), lambda f: pick(f, "id", default="osv"),
        "No vulnerable dependencies found.")


def syft_section(out: Path) -> str:
    if not (out / "syft.json").exists():
        return ""
    packages = syft_packages(out)
    if not packages:
        return "## SBOM inventory (Syft)\n\n- No packages found.\n"
    by_type = Counter(pick(p, "type", default="?") for p in packages)
    lines = [
        "## SBOM inventory (Syft)\n",
        f"- **{len(packages)} package(s)** found\n",
        "\n| Package type | Count |", "|---|--:|",
    ]
    for typ, n in by_type.most_common(12):
        lines.append(f"| {typ} | {n} |")
    return "\n".join(lines) + "\n"


def brakeman_section(out: Path) -> str:
    return count_findings_section(
        out, "Rails security (Brakeman)", "brakeman.json", brakeman_findings(out),
        lambda f: pick(f, "warning_type", "check_name", default="brakeman"),
        "No Rails security warnings.")


def spotbugs_section(out: Path) -> str:
    return count_findings_section(
        out, "JVM bytecode bugs (SpotBugs)", "spotbugs.xml", spotbugs_findings(out),
        lambda f: pick(f, "type", default="spotbugs"),
        "No SpotBugs findings.")


# ----------------------------------------------------- dependency rules ---
def ast_grep_section(out: Path) -> str:
    if not (out / "ast-grep.json").exists():
        return ""
    findings = ast_grep_findings(out)
    if not findings:
        return "## Dependency rules (ast-grep)\n\n- No violations found.\n"
    by_rule = Counter(f.get("ruleId", "?") for f in findings)
    lines = [
        "## Dependency rules (ast-grep)\n",
        f"- **{len(findings)} rule violation(s)**\n",
        "\n| Rule | Count |", "|---|--:|",
    ]
    for rule, n in by_rule.most_common():
        lines.append(f"| {rule} | {n} |")
    lines.append(CSV_NOTE)
    return "\n".join(lines) + "\n"


def semgrep_section(out: Path) -> str:
    data = load_json(out / "semgrep.json")
    if not data:
        return ""
    results = data.get("results", [])
    if not results:
        return "## Dependency rules (semgrep)\n\n- No matches.\n"
    by_rule = Counter(r.get("check_id", "?").split(".")[-1] for r in results)
    lines = [
        "## Dependency rules (semgrep)\n",
        f"- **{len(results)} match(es)**\n",
        "\n| Rule | Count |", "|---|--:|",
    ]
    for rule, n in by_rule.most_common():
        lines.append(f"| {rule} | {n} |")
    lines.append(CSV_NOTE)
    return "\n".join(lines) + "\n"


def depcruise_section(out: Path) -> str:
    data = load_json(out / "depcruise.json")
    if not data:
        return ""
    summary = data.get("summary", {})
    err = summary.get("error", 0)
    warn = summary.get("warn", 0)
    viols = summary.get("violations", [])
    lines = [
        "## Dependency rules (dependency-cruiser)\n",
        f"- **{err} error(s)**, **{warn} warning(s)** against configured rules\n",
    ]
    if viols:
        by_rule = Counter(v.get("rule", {}).get("name", "?") for v in viols)
        lines += ["\n| Rule | Count |", "|---|--:|"]
        for rule, n in by_rule.most_common():
            lines.append(f"| {rule} | {n} |")
        lines.append(CSV_NOTE)
    return "\n".join(lines) + "\n"


def madge_section(out: Path) -> str:
    data = load_json(out / "madge-circular.json")
    if data is None:
        return ""
    n = len(data)
    body = "- No circular dependencies.\n" if n == 0 else f"- **{n} circular dependency chain(s)** detected.\n"
    return "## Cycles (madge)\n\n" + body


# ------------------------------------------------------ machine-readable ---
def write_findings_csv(out: Path) -> int:
    """Write findings.csv: one row per violation across all sensors.
    Columns: category, tool, severity, rule, file, line, message."""
    rows = []

    def xml_root(name):
        p = out / name
        if not p.exists():
            return None
        try:
            return ET.parse(p).getroot()
        except Exception:
            return None

    # lizard — functions at/above the complexity threshold
    lz = out / "lizard.csv"
    if lz.exists():
        with lz.open(newline="") as f:
            for r in csv.reader(f):
                if len(r) < 10:
                    continue
                try:
                    ccn = int(r[1])
                except ValueError:
                    continue
                if ccn >= CCN_WARN:
                    rows.append(("complexity", "lizard", "warning", "high-complexity",
                                 r[6], r[9], f"CCN {ccn} in {r[7]}"))

    # detekt (checkstyle xml)
    root = xml_root("detekt.xml")
    if root is not None:
        for fl in root.iter("file"):
            for e in fl.iter("error"):
                rows.append(("quality", "detekt", e.get("severity", ""),
                             e.get("source", "?").split(".")[-1],
                             fl.get("name", "?"), e.get("line", ""), e.get("message", "")))

    # pmd
    root = xml_root("pmd.xml")
    if root is not None:
        for fl in root.iter():
            if not fl.tag.endswith("file"):
                continue
            for v in fl:
                if v.tag.endswith("violation"):
                    rows.append(("quality", "pmd", v.get("priority", ""),
                                 v.get("rule", "?"), fl.get("name", "?"),
                                 v.get("beginline", ""), (v.text or "").strip()))

    # shellcheck
    for f in shellcheck_findings(out):
        rows.append(("quality", "shellcheck", pick(f, "level"),
                     f"SC{pick(f, 'code')}", pick(f, "file"),
                     pick(f, "line"), pick(f, "message")))

    # actionlint
    for f in actionlint_findings(out):
        rows.append(("quality", "actionlint", "error",
                     pick(f, "kind", "Kind", default="actionlint"),
                     pick(f, "filepath", "Filepath", "file", "File"),
                     pick(f, "line", "Line"), pick(f, "message", "Message")))

    # hadolint
    for f in hadolint_findings(out):
        rows.append(("quality", "hadolint", pick(f, "level", "Level"),
                     pick(f, "code", "Code", default="hadolint"),
                     pick(f, "file", "File"), pick(f, "line", "Line"),
                     pick(f, "message", "Message")))

    # ruff
    for f in ruff_findings(out):
        loc = pick(f, "location", default={})
        line = pick(loc, "row", "line") if isinstance(loc, dict) else ""
        rows.append(("quality", "ruff", "",
                     pick(f, "code", "Code", default="ruff"),
                     pick(f, "filename", "file"), line,
                     pick(f, "message", "Message")))

    # checkov
    for f in checkov_findings(out):
        rng = pick(f, "file_line_range", "fileLineRange", default=[])
        line = rng[0] if isinstance(rng, list) and rng else pick(f, "line")
        rows.append(("security", "checkov", pick(f, "severity", "Severity"),
                     pick(f, "check_id", "checkId", default="checkov"),
                     pick(f, "file_path", "filePath", "file"),
                     line, pick(f, "check_name", "checkName", "message")))

    # betterleaks
    for f in betterleaks_findings(out):
        validation = pick(f, "Validation", "validation", default={})
        result = pick(validation, "result") if isinstance(validation, dict) else ""
        rows.append(("security", "betterleaks", result,
                     pick(f, "RuleID", "rule_id", "ruleId", "rule", default="betterleaks"),
                     pick(f, "File", "file", "path"),
                     pick(f, "StartLine", "start_line", "line"),
                     pick(f, "Description", "description", "message")))

    # osv-scanner
    for f in osv_findings(out):
        package = pick(f, "package")
        version = pick(f, "version")
        ecosystem = pick(f, "ecosystem")
        rows.append(("security", "osv-scanner", pick(f, "severity"),
                     pick(f, "id", default="osv"), pick(f, "source"), "",
                     f"{package}@{version} ({ecosystem}) {pick(f, 'message')}"))

    # brakeman
    for f in brakeman_findings(out):
        rows.append(("security", "brakeman", pick(f, "confidence"),
                     pick(f, "warning_code", "check_name", default="brakeman"),
                     pick(f, "file"), pick(f, "line"), pick(f, "message")))

    # spotbugs
    for f in spotbugs_findings(out):
        category = "security" if pick(f, "category").upper() == "SECURITY" else "quality"
        rows.append((category, "spotbugs", pick(f, "priority"),
                     pick(f, "type", default="spotbugs"),
                     pick(f, "file"), pick(f, "line"), pick(f, "message")))

    # cpd duplication — one row per location, sharing a block id
    root = xml_root("cpd.xml")
    if root is not None:
        blk = 0
        for d in root.iter():
            if not d.tag.endswith("duplication"):
                continue
            blk += 1
            files = [(c.get("path"), c.get("line")) for c in d if c.tag.endswith("file")]
            others = ", ".join(p for p, _ in files)
            for path, line in files:
                rows.append(("duplication", "cpd", "", f"duplicate-block-{blk}",
                             path, line,
                             f"{d.get('lines')}-line / {d.get('tokens')}-token block shared by: {others}"))

    # scapegoat
    root = xml_root("scapegoat.xml")
    if root is not None:
        for w in root.iter():
            if w.tag.endswith("warning"):
                rows.append(("quality", "scapegoat", w.get("level", ""),
                             w.get("inspection", "?").split(".")[-1],
                             w.get("file", "?"), w.get("line", ""), w.get("text", "")))

    # ast-grep
    for d in ast_grep_findings(out):
        rows.append(("dependency", "ast-grep", d.get("severity", ""),
                     d.get("ruleId", "?"), d.get("file", "?"),
                     d.get("range", {}).get("start", {}).get("line", ""),
                     d.get("message", "")))

    # semgrep
    sg = load_json(out / "semgrep.json")
    if sg:
        for r in sg.get("results", []):
            rows.append(("dependency", "semgrep", r.get("extra", {}).get("severity", ""),
                         r.get("check_id", "?").split(".")[-1], r.get("path", "?"),
                         r.get("start", {}).get("line", ""),
                         r.get("extra", {}).get("message", "")))

    # dependency-cruiser
    dc = load_json(out / "depcruise.json")
    if dc:
        for v in dc.get("summary", {}).get("violations", []):
            to = v.get("to", v.get("unresolvedTo", ""))
            rows.append(("dependency", "dependency-cruiser", v.get("rule", {}).get("severity", ""),
                         v.get("rule", {}).get("name", "?"), v.get("from", "?"), "",
                         f"{v.get('from','?')} -> {to}" if to else v.get("from", "?")))

    # madge cycles
    mad = load_json(out / "madge-circular.json")
    if mad:
        for chain in mad:
            if isinstance(chain, list) and chain:
                rows.append(("dependency", "madge", "warning", "circular",
                             chain[0], "", " -> ".join(chain)))

    with (out / "findings.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["category", "tool", "severity", "rule", "file", "line", "message"])
        w.writerows(rows)
    return len(rows)


# ----------------------------------------------------------------- legend ---
LEGEND = [
    ("CCN", "Cyclomatic complexity — independent paths through a function; "
            f"higher = harder to test. Flagged at ≥ {CCN_WARN}."),
    ("NLOC", "Non-comment lines of code, per function."),
    ("LOC", "Lines of code (excludes blanks and comments)."),
    ("max / p95 / median / mean", "The CCN distribution across all functions, "
            "not a sum."),
    ("density (CCN / LOC)", "Total CCN ÷ lines of code; complexity "
            "normalised for size."),
    ("Complexity* (scc)", "A per-language keyword heuristic that tracks size; "
            "shown per language, not summed."),
    ("Dep-rule breach", "A violated dependency rule (forbidden import, layer "
            "violation, or cycle)."),
    ("churn", "How often a file changes in version control (rubycritic)."),
]


def legend_section(out: Path) -> str:
    lines = [
        "## Legend\n",
        "| Term | Meaning |", "|---|---|",
    ]
    for term, meaning in LEGEND:
        lines.append(f"| **{term}** | {meaning} |")

    fired = triggered_rules(out)
    if fired:
        lines += [
            "\n**Dependency rules triggered in this report:**\n",
            "| Rule | Tool | Meaning |", "|---|---|---|",
        ]
        for rid in sorted(fired):
            tool, desc = fired[rid]
            lines.append(f"| `{rid}` | {tool} | {desc} |")

    checks = triggered_check_rules(out)
    if checks:
        lines += [
            "\n**Quality/security check codes triggered in this report:**\n",
            "| Code | Tool | Meaning |", "|---|---|---|",
        ]
        for rid in sorted(checks):
            tool, desc = checks[rid]
            lines.append(f"| `{rid}` | {tool} | {desc} |")

    lines.append("\n_Full glossary: `docs/TOOLS.md` § Appendix._")
    return "\n".join(lines) + "\n"


# ------------------------------------------------------------------ main ---
def main():
    out = Path(sys.argv[1])
    target = sys.argv[2] if len(sys.argv) > 2 else "?"
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    parts = [
        "# Static analysis summary\n",
        f"_Target:_ `{target}`  \n_Generated:_ {now}\n",
    ]
    failures = out / ".failures"
    if failures.exists():
        failed = [ln.strip() for ln in failures.read_text().splitlines() if ln.strip()]
        if failed:
            block = ["## ⚠ Sensors that failed\n",
                     "These tools ran but produced no valid output, so their "
                     "results are **missing** from this report:\n"]
            for label in failed:
                log = out / ".logs" / f"{label}.err"
                reason = ""
                if log.exists():
                    lines = [ln for ln in log.read_text().splitlines() if ln.strip()]
                    if lines:
                        reason = "\n  ```\n" + "\n".join(
                            "  " + ln for ln in lines[-8:]) + "\n  ```"
                block.append(f"- **`{label}`** — see `.logs/{label}.err`{reason}")
            parts.append("\n".join(block) + "\n")
    for fn in (
        scc_section, lizard_section, detekt_section, pmd_section, cpd_section,
        scapegoat_section, scalafix_section, rubycritic_section,
        shellcheck_section, actionlint_section, hadolint_section, ruff_section,
        checkov_section, betterleaks_section, osv_section, syft_section,
        brakeman_section, spotbugs_section,
        ast_grep_section, semgrep_section, depcruise_section, madge_section,
    ):
        try:
            s = fn(out)
        except Exception as e:  # never let one parser break the report
            s = f"## {fn.__name__.replace('_section','')}\n\n- (failed to parse: {e})\n"
        if s:
            parts.append(s)

    try:
        n_find = write_findings_csv(out)
    except Exception as e:
        n_find = -1
        print(f"findings.csv failed: {e}", file=sys.stderr)
    if n_find >= 0:
        parts.append(
            "## All findings\n\n"
            f"- **{n_find}** machine-readable finding(s) in `findings.csv` "
            "(columns: category, tool, severity, rule, file, line, message) — "
            "load it into your editor/CI to jump to each violation.\n")

    parts.append(legend_section(out))

    desc = {
        "findings.csv": "every violation as one row — load in an editor/CI to jump to source",
        "scc.json": "per-language size & complexity",
        "scc.txt": "size & complexity, human-readable",
        "lizard.csv": "per-function cyclomatic complexity",
        "lizard-warnings.txt": "functions over the complexity threshold",
        "pmd.xml": "full PMD violations",
        "cpd.xml": "duplicate blocks with the duplicated code fragments",
        "detekt.xml": "full detekt findings",
        "scapegoat.xml": "full scapegoat warnings",
        "scalafix.txt": "scalafix output",
        "shellcheck.json": "shell script findings",
        "actionlint.json": "GitHub Actions workflow findings",
        "hadolint.json": "Dockerfile findings",
        "ruff.json": "Python lint findings",
        "checkov.json": "IaC security findings",
        "betterleaks.json": "secret scanning findings",
        "osv-scanner.json": "dependency vulnerability findings",
        "syft.json": "SBOM package inventory",
        "brakeman.json": "Rails security findings",
        "spotbugs.xml": "JVM bytecode bug/security findings",
        "ast-grep.json": "dependency-rule violations",
        "semgrep.json": "dependency-rule / quality matches",
        "depcruise.json": "dependency-cruiser violations",
        "madge-circular.json": "circular dependency chains",
        "rubycritic": "Ruby complexity, churn & smells",
        "report.pdf": "visual summary",
    }
    produced = sorted(p.name for p in out.iterdir()
                      if p.name != "summary.md" and not p.name.startswith("."))
    parts.append("## Reports produced\n\n_This summary points at the files below; "
                 "`findings.csv` has the full navigable detail._\n\n"
                 + "\n".join(f"- `{n}`" + (f" — {desc[n]}" if n in desc else "")
                             for n in produced) + "\n")

    (out / "summary.md").write_text("\n".join(parts))
    print(f"wrote {out/'summary.md'}")


if __name__ == "__main__":
    main()
