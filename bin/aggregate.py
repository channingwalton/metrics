#!/usr/bin/env python3
"""Aggregate per-tool reports in a reports dir into a single summary.md.

Usage: aggregate.py <reports_dir> <target_dir>

Reads whatever reports are present (all optional) and produces one Markdown
read-out covering every sensor that ran: size/complexity, per-function
cyclomatic complexity, duplication, code smells, and dependency-rule
violations. Missing reports are silently skipped.
"""
import csv
import json
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

CCN_WARN = 15  # cyclomatic-complexity threshold for "hotspot"


def load_json(p: Path):
    try:
        return json.loads(p.read_text())
    except Exception:
        return None


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
        f"- **{total} finding(s)**\n",
        "\n| Rule | Count |", "|---|--:|",
    ]
    for rule, n in by_rule.most_common(15):
        lines.append(f"| {rule} | {n} |")
    return "\n".join(lines) + "\n"


def pmd_section(out: Path) -> str:
    p = out / "pmd.xml"
    if not p.exists():
        return ""
    try:
        root = ET.parse(p).getroot()
    except Exception:
        return ""
    # strip namespace
    by_rule = Counter()
    total = 0
    for el in root.iter():
        if el.tag.endswith("violation"):
            by_rule[el.get("rule", "?")] += 1
            total += 1
    if total == 0:
        return "## Java (PMD)\n\n- No violations.\n"
    lines = [
        "## Java rules (PMD)\n",
        f"- **{total} violation(s)**\n",
        "\n| Rule | Count |", "|---|--:|",
    ]
    for rule, n in by_rule.most_common(15):
        lines.append(f"| {rule} | {n} |")
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
        f"- **{len(dups)} duplicate block(s)**, **{tot_lines} lines** total.\n"
    )


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


# ----------------------------------------------------- dependency rules ---
def ast_grep_section(out: Path) -> str:
    p = out / "ast-grep.json"
    if not p.exists():
        return ""
    findings = []
    txt = p.read_text().strip()
    for line in txt.splitlines():  # --json=stream → one object per line
        line = line.strip().rstrip(",")
        if not line or line in "[]":
            continue
        try:
            findings.append(json.loads(line))
        except Exception:
            pass
    if not findings:
        try:
            findings = json.loads(txt)
        except Exception:
            findings = []
    if not findings:
        return "## Dependency rules (ast-grep)\n\n- No violations found.\n"
    lines = [
        "## Dependency rules (ast-grep)\n",
        f"- **{len(findings)} rule violation(s)**\n",
        "\n| Rule | File | Line |", "|---|---|--:|",
    ]
    for f in findings[:30]:
        rng = f.get("range", {}).get("start", {})
        lines.append(
            f"| {f.get('ruleId','?')} | {f.get('file','?')} | {rng.get('line','?')} |"
        )
    return "\n".join(lines) + "\n"


def semgrep_section(out: Path) -> str:
    data = load_json(out / "semgrep.json")
    if not data:
        return ""
    results = data.get("results", [])
    if not results:
        return "## Dependency rules (semgrep)\n\n- No matches.\n"
    lines = [
        "## Dependency rules (semgrep)\n",
        f"- **{len(results)} match(es)**\n",
        "\n| Rule | File | Line |", "|---|---|--:|",
    ]
    for r in results[:30]:
        lines.append(
            f"| {r.get('check_id','?').split('.')[-1]} | {r.get('path','?')} "
            f"| {r.get('start',{}).get('line','?')} |"
        )
    return "\n".join(lines) + "\n"


def depcruise_section(out: Path) -> str:
    data = load_json(out / "depcruise.json")
    if not data:
        return ""
    summary = data.get("summary", {})
    err = summary.get("error", 0)
    warn = summary.get("warn", 0)
    return (
        "## Dependency rules (dependency-cruiser)\n\n"
        f"- **{err} error(s)**, **{warn} warning(s)** against configured rules.\n"
    )


def madge_section(out: Path) -> str:
    data = load_json(out / "madge-circular.json")
    if data is None:
        return ""
    n = len(data)
    body = "- No circular dependencies.\n" if n == 0 else f"- **{n} circular dependency chain(s)** detected.\n"
    return "## Cycles (madge)\n\n" + body


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


def legend_section() -> str:
    lines = [
        "## Legend\n",
        "| Term | Meaning |", "|---|---|",
    ]
    for term, meaning in LEGEND:
        lines.append(f"| **{term}** | {meaning} |")
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
    for fn in (
        scc_section, lizard_section, detekt_section, pmd_section, cpd_section,
        scapegoat_section, scalafix_section, rubycritic_section,
        ast_grep_section, semgrep_section, depcruise_section, madge_section,
    ):
        try:
            s = fn(out)
        except Exception as e:  # never let one parser break the report
            s = f"## {fn.__name__.replace('_section','')}\n\n- (failed to parse: {e})\n"
        if s:
            parts.append(s)

    parts.append(legend_section())

    produced = sorted(p.name for p in out.iterdir() if p.name != "summary.md")
    parts.append("## Reports produced\n\n" + "\n".join(f"- `{n}`" for n in produced) + "\n")

    (out / "summary.md").write_text("\n".join(parts))
    print(f"wrote {out/'summary.md'}")


if __name__ == "__main__":
    main()
