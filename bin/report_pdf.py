#!/usr/bin/env python3
"""Render a static-analysis reports dir into a graphical PDF.

Usage: report_pdf.py <reports_dir> [target_label]

Reads scc.json + lizard.csv (and optional dependency-rule reports) and produces
report.pdf with summary stat cards, a language size chart, a complexity
distribution histogram, and a top-hotspots chart + table.

Requires: matplotlib, reportlab (installed by bin/install.sh).
"""
import csv
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

from report_common import (
    CCN_WARN, actionlint_findings, ast_grep_findings, betterleaks_findings,
    brakeman_findings, cargo_audit_findings, cargo_clippy_findings,
    checkov_findings, hadolint_findings, load_json, osv_findings,
    ruff_findings, shellcheck_findings, spotbugs_findings, syft_packages,
    triggered_check_rules, triggered_rules,
)

INK = "#1f2933"
ACCENT = "#2f6f8f"
WARN = "#c2410c"
GRID = "#e2e8f0"

plt.rcParams.update({
    "font.size": 11,
    "axes.edgecolor": INK,
    "axes.linewidth": 0.8,
    "axes.grid": True,
    "grid.color": GRID,
    "axes.axisbelow": True,
    "figure.dpi": 150,
})


# ------------------------------------------------------------- read data ---
def read_scc(out):
    data = load_json(out / "scc.json") or []
    langs = sorted(
        ((d.get("Name", "?"), d.get("Code", 0)) for d in data),
        key=lambda t: t[1], reverse=True,
    )
    files = sum(d.get("Count", 0) for d in data)
    loc = sum(d.get("Code", 0) for d in data)
    return langs, files, loc


def read_lizard(out):
    p = out / "lizard.csv"
    rows = []
    if p.exists():
        with p.open(newline="") as f:
            for r in csv.reader(f):
                if len(r) < 8:
                    continue
                try:
                    rows.append((int(r[1]), int(r[0]), r[7].strip('"'),
                                 Path(r[6]).name))
                except ValueError:
                    continue
    rows.sort(reverse=True)
    return rows


def _short(path, n=3):
    parts = Path(path).parts
    return "/".join(parts[-n:]) if len(parts) > n else str(path)


def pick(d, *names, default=""):
    if not isinstance(d, dict):
        return default
    for name in names:
        if name in d and d[name] not in (None, ""):
            return d[name]
    return default


def count_json_rules(findings, *keys, default="?"):
    c = Counter()
    for f in findings:
        c[pick(f, *keys, default=default)] += 1
    return c


def read_ast_grep(out):
    return [(d.get("ruleId", "?"), _short(d.get("file", "?")),
             d.get("range", {}).get("start", {}).get("line", "?"))
            for d in ast_grep_findings(out)]


def read_semgrep(out):
    data = load_json(out / "semgrep.json")
    if not data:
        return []
    return [
        (r.get("check_id", "?").split(".")[-1], _short(r.get("path", "?")),
         r.get("start", {}).get("line", "?"))
        for r in data.get("results", [])
    ]


def read_depcruise(out):
    d = load_json(out / "depcruise.json")
    if not d:
        return None
    s = d.get("summary", {})
    return s.get("error", 0), s.get("warn", 0)


def read_madge(out):
    d = load_json(out / "madge-circular.json")
    return None if d is None else len(d)


def _count_xml(out, fname, tag, attr):
    p = out / fname
    if not p.exists():
        return None
    try:
        root = ET.parse(p).getroot()
    except Exception:
        return None
    c = Counter()
    for el in root.iter():
        if el.tag.endswith(tag):
            c[(el.get(attr, "?") or "?").split(".")[-1]] += 1
    return c


def read_failures(out):
    p = out / ".failures"
    if not p.exists():
        return []
    rows = []
    for label in p.read_text().splitlines():
        label = label.strip()
        if not label:
            continue
        log = out / ".logs" / f"{label}.err"
        reason = ""
        if log.exists():
            lines = [ln.strip() for ln in log.read_text().splitlines() if ln.strip()]
            reason = " ".join(lines[-2:])
        rows.append((label, reason or f"See .logs/{label}.err"))
    return rows


def read_cpd(out):
    p = out / "cpd.xml"
    if not p.exists():
        return None
    try:
        root = ET.parse(p).getroot()
    except Exception:
        return None
    dups = [el for el in root.iter() if el.tag.endswith("duplication")]
    return len(dups), sum(int(d.get("lines", 0)) for d in dups)


def read_findings_count(out):
    p = out / "findings.csv"
    if not p.exists():
        return None
    try:
        with p.open(newline="") as f:
            return max(0, sum(1 for _ in csv.reader(f)) - 1)
    except Exception:
        return None


def read_detekt(out):
    return _count_xml(out, "detekt.xml", "error", "source")


def read_pmd(out):
    return _count_xml(out, "pmd.xml", "violation", "rule")


def read_scapegoat(out):
    return _count_xml(out, "scapegoat.xml", "warning", "inspection")


def read_rubycritic(out):
    d = out / "rubycritic"
    if not d.exists():
        return []
    js = list(d.rglob("*.json"))
    if not js:
        return []
    data = load_json(js[0])
    mods = data if isinstance(data, list) else (
        data.get("analysed_modules", []) if isinstance(data, dict) else [])
    mods = sorted(mods, key=lambda m: m.get("complexity", 0) or 0, reverse=True)
    return [(m.get("rating", "?"), m.get("complexity", "?"),
             m.get("churn", "?"), _short(m.get("path") or m.get("name", "?")))
            for m in mods]


def read_shellcheck(out):
    c = Counter()
    for f in shellcheck_findings(out):
        code = pick(f, "code", default="shellcheck")
        c[f"SC{code}" if code != "shellcheck" else code] += 1
    return c


def read_actionlint(out):
    return count_json_rules(actionlint_findings(out), "kind", "Kind", default="actionlint")


def read_hadolint(out):
    return count_json_rules(hadolint_findings(out), "code", "Code", default="hadolint")


def read_ruff(out):
    return count_json_rules(ruff_findings(out), "code", "Code", default="ruff")


def read_cargo_clippy(out):
    return count_json_rules(
        cargo_clippy_findings(out), "code", default="cargo-clippy")


def read_checkov(out):
    return count_json_rules(checkov_findings(out), "check_id", "checkId", default="checkov")


def read_betterleaks(out):
    return count_json_rules(
        betterleaks_findings(out), "RuleID", "rule_id", "ruleId", "rule",
        default="betterleaks")


def read_osv(out):
    return count_json_rules(osv_findings(out), "id", default="osv")


def read_cargo_audit(out):
    return count_json_rules(cargo_audit_findings(out), "id", default="cargo-audit")


def read_syft(out):
    c = Counter()
    for pkg in syft_packages(out):
        c[pick(pkg, "type", default="?")] += 1
    return c


def read_brakeman(out):
    return count_json_rules(
        brakeman_findings(out), "warning_type", "check_name", default="brakeman")


def read_spotbugs(out):
    return count_json_rules(spotbugs_findings(out), "type", default="spotbugs")


def count_dep_violations(out):
    n = len(read_ast_grep(out)) + len(read_semgrep(out))
    dc = read_depcruise(out)
    if dc:
        n += dc[0]
    return n


# ---------------------------------------------------------------- charts ---
def chart_languages(langs, path):
    top = langs[:10]
    if not top:
        return False
    names = [t[0] for t in top][::-1]
    vals = [t[1] for t in top][::-1]
    fig, ax = plt.subplots(figsize=(7, max(2.2, 0.5 * len(top))))
    ax.barh(names, vals, color=ACCENT)
    ax.set_xlabel("Lines of code")
    ax.set_title("Code size by language", loc="left", fontweight="bold")
    ax.grid(axis="y", visible=False)
    for i, v in enumerate(vals):
        ax.text(v, i, f" {v:,}", va="center", fontsize=9, color=INK)
    fig.tight_layout()
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return True


def chart_distribution(rows, path):
    if not rows:
        return False
    ccns = [r[0] for r in rows]
    fig, ax = plt.subplots(figsize=(7, 3.2))
    hi = max(max(ccns), CCN_WARN + 1)
    ax.hist(ccns, bins=range(1, hi + 2), color=ACCENT, edgecolor="white")
    ax.axvline(CCN_WARN, color=WARN, linestyle="--", linewidth=1.5)
    ax.text(CCN_WARN, ax.get_ylim()[1] * 0.92, f" threshold {CCN_WARN}",
            color=WARN, fontsize=9)
    ax.set_xlabel("Cyclomatic complexity (CCN)")
    ax.set_ylabel("Functions")
    ax.set_title("Complexity distribution", loc="left", fontweight="bold")
    ax.grid(axis="x", visible=False)
    fig.tight_layout()
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return True


def chart_hotspots(rows, path):
    top = rows[:12]
    if not top:
        return False
    labels = [f"{fn}  ({fl})" for _, _, fn, fl in top][::-1]
    vals = [c for c, _, _, _ in top][::-1]
    cols = [WARN if v >= CCN_WARN else ACCENT for v in vals]
    fig, ax = plt.subplots(figsize=(7, max(2.5, 0.45 * len(top))))
    ax.barh(labels, vals, color=cols)
    ax.set_xlabel("Cyclomatic complexity (CCN)")
    ax.set_title("Most complex functions", loc="left", fontweight="bold")
    ax.grid(axis="y", visible=False)
    for i, v in enumerate(vals):
        ax.text(v, i, f" {v}", va="center", fontsize=9, color=INK)
    fig.tight_layout()
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return True


# ------------------------------------------------------------------ pdf ---
def pctile(vals, q):
    s = sorted(vals)
    if not s:
        return 0
    k = max(0, min(len(s) - 1, int(round(q * (len(s) - 1)))))
    return s[k]


def build(out: Path, target: str):
    langs, files, loc = read_scc(out)
    rows = read_lizard(out)
    deps = count_dep_violations(out)
    failures = read_failures(out)
    all_findings = read_findings_count(out)

    imgdir = out / ".charts"
    imgdir.mkdir(exist_ok=True)
    have_lang = chart_languages(langs, imgdir / "lang.png")
    have_dist = chart_distribution(rows, imgdir / "dist.png")
    have_hot = chart_hotspots(rows, imgdir / "hot.png")

    ccns = [r[0] for r in rows]
    nloc = sum(r[1] for r in rows) or 1
    over = [c for c in ccns if c >= CCN_WARN]

    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=styles["Title"], textColor=colors.HexColor(INK))
    h2 = ParagraphStyle("h2", parent=styles["Heading2"], textColor=colors.HexColor(ACCENT))
    meta = ParagraphStyle("meta", parent=styles["Normal"], textColor=colors.grey, fontSize=9)

    doc = SimpleDocTemplate(
        str(out / "report.pdf"), pagesize=A4,
        leftMargin=1.8 * cm, rightMargin=1.8 * cm,
        topMargin=1.6 * cm, bottomMargin=1.6 * cm,
        title="Static analysis report",
    )
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    story = [
        Paragraph("Static analysis report", h1),
        Paragraph(f"Target: <b>{target}</b> &nbsp;·&nbsp; Generated: {now}", meta),
        Spacer(1, 0.5 * cm),
    ]

    # stat cards
    val_style = ParagraphStyle("val", parent=styles["Normal"], fontSize=16,
                               leading=20, textColor=colors.HexColor(INK))
    lab_style = ParagraphStyle("lab", parent=styles["Normal"], fontSize=8,
                               leading=11, textColor=colors.HexColor("#64748b"),
                               spaceBefore=2)

    def card(label, value):
        return [Paragraph(f"<b>{value}</b>", val_style), Paragraph(label, lab_style)]

    cells = [
        card("Files", f"{files:,}"),
        card("Lines of code", f"{loc:,}"),
        card("Functions", f"{len(ccns):,}"),
        card("Max CCN", f"{max(ccns) if ccns else 0}"),
        card("p95 CCN", f"{pctile(ccns, 0.95)}"),
        card(f"≥ CCN {CCN_WARN}", f"{len(over)}"),
        card("CCN / LOC", f"{sum(ccns)/nloc:.2f}"),
        card("Dep-rule breaches", f"{deps}"),
    ]
    # 4 cards per row
    grid = [cells[0:4], cells[4:8]]
    t = Table(grid, colWidths=[4.2 * cm] * 4)
    t.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor(GRID)),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor(GRID)),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
    ]))
    story += [t, Spacer(1, 0.6 * cm)]

    full = 17 * cm
    for ok, name, img in (
        (have_lang, "Size", "lang.png"),
        (have_dist, "Complexity distribution", "dist.png"),
        (have_hot, "Hotspots", "hot.png"),
    ):
        if ok:
            im = Image(str(imgdir / img))
            im._restrictSize(full, 11 * cm)
            story += [im, Spacer(1, 0.5 * cm)]

    # hotspot table
    if rows:
        story += [Spacer(1, 0.2 * cm), Paragraph("Most complex functions", h2)]
        data = [["CCN", "NLOC", "Function", "File"]]
        for c, n, fn, fl in rows[:15]:
            data.append([str(c), str(n), fn, fl])
        tt = Table(data, colWidths=[1.6 * cm, 1.6 * cm, 7 * cm, 6 * cm])
        tt.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(ACCENT)),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f1f5f9")]),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor(GRID)),
            ("ALIGN", (0, 0), (1, -1), "RIGHT"),
        ]))
        # flag rows over threshold
        for i, (c, *_rest) in enumerate(rows[:15], start=1):
            if c >= CCN_WARN:
                tt.setStyle(TableStyle([("TEXTCOLOR", (0, i), (0, i), colors.HexColor(WARN))]))
        story.append(tt)

    cpd = read_cpd(out)
    if cpd is not None:
        story += [Spacer(1, 0.5 * cm), Paragraph("Duplication", h2)]
        blocks, lines = cpd
        if blocks:
            story.append(Paragraph(
                f"<b>{blocks}</b> duplicate block(s), <b>{lines}</b> lines total. "
                "Full locations are in findings.csv.", meta))
        else:
            story.append(Paragraph("No duplicate blocks over threshold.", meta))

    # styles shared by finding tables
    cellp = ParagraphStyle("cellp", parent=styles["Normal"], fontSize=8, leading=10)

    def finding_table(headers, data_rows, widths):
        rows = [[Paragraph(f"<b>{h}</b>", cellp) for h in headers]]
        rows += [[Paragraph(str(c), cellp) for c in r] for r in data_rows]
        tbl = Table(rows, colWidths=widths, repeatRows=1)
        tbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(ACCENT)),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f1f5f9")]),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor(GRID)),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        return tbl

    if failures:
        story += [Spacer(1, 0.5 * cm), Paragraph("Sensors that failed", h2)]
        frows = [(label, reason) for label, reason in failures]
        story += [finding_table(["Sensor", "Last log lines"], frows,
                                [4 * cm, 13 * cm])]

    # --- dependency-rule findings (summary; detail in findings.csv) ---------
    ag = read_ast_grep(out)
    sg = read_semgrep(out)
    dc = read_depcruise(out)
    mad = read_madge(out)
    story += [Spacer(1, 0.5 * cm), Paragraph("Dependency-rule findings", h2)]
    notes = []
    if dc is not None:
        notes.append(f"dependency-cruiser: <b>{dc[0]}</b> error(s), <b>{dc[1]}</b> warning(s)")
    if mad is not None:
        notes.append(f"madge: <b>{mad}</b> circular dependency chain(s)")
    if notes:
        story.append(Paragraph(" &nbsp;·&nbsp; ".join(notes), meta))
        story.append(Spacer(1, 0.2 * cm))
    rule_counts = Counter(("ast-grep", r) for r, _, _ in ag)
    rule_counts.update(("semgrep", r) for r, _, _ in sg)
    if rule_counts:
        crows = [(tool, rule, n) for (tool, rule), n in rule_counts.most_common()]
        story.append(finding_table(["Tool", "Rule", "Count"], crows,
                                    [3 * cm, 10 * cm, 2 * cm]))
    elif not notes:
        story.append(Paragraph("No dependency-rule violations found.", meta))
    else:
        story.append(Paragraph("No forbidden-import / layering violations found.", meta))

    # --- code-quality findings ----------------------------------------------
    detekt, pmd, scape = read_detekt(out), read_pmd(out), read_scapegoat(out)
    shell, actions, docker = read_shellcheck(out), read_actionlint(out), read_hadolint(out)
    ruff, clippy = read_ruff(out), read_cargo_clippy(out)
    checkov, secrets = read_checkov(out), read_betterleaks(out)
    osv, cargo_audit, syft = read_osv(out), read_cargo_audit(out), read_syft(out)
    brakeman, spotbugs = read_brakeman(out), read_spotbugs(out)
    ruby = read_rubycritic(out)
    quality_blocks = []
    for title, counts in (("Kotlin (detekt)", detekt), ("Java (PMD)", pmd),
                          ("Scala (scapegoat)", scape),
                          ("JVM bytecode (SpotBugs)", spotbugs),
                          ("Shell (ShellCheck)", shell),
                          ("GitHub Actions (actionlint)", actions),
                          ("Dockerfiles (hadolint)", docker),
                          ("Python (Ruff)", ruff),
                          ("Rust (cargo clippy)", clippy),
                          ("IaC security (Checkov)", checkov),
                          ("Secrets (Betterleaks)", secrets),
                          ("Dependency vulnerabilities (OSV-Scanner)", osv),
                          ("Rust dependency vulnerabilities (cargo audit)", cargo_audit),
                          ("Rails security (Brakeman)", brakeman)):
        if counts:
            quality_blocks.append((title,
                finding_table(["Rule", "Count"],
                              [(k, v) for k, v in counts.most_common(12)],
                              [13 * cm, 4 * cm])))
        elif {
            "Kotlin (detekt)": "detekt.xml",
            "Java (PMD)": "pmd.xml",
            "Scala (scapegoat)": "scapegoat.xml",
            "JVM bytecode (SpotBugs)": "spotbugs.xml",
            "Shell (ShellCheck)": "shellcheck.json",
            "GitHub Actions (actionlint)": "actionlint.json",
            "Dockerfiles (hadolint)": "hadolint.json",
            "Python (Ruff)": "ruff.json",
            "Rust (cargo clippy)": "cargo-clippy.json",
            "IaC security (Checkov)": "checkov.json",
            "Secrets (Betterleaks)": "betterleaks.json",
            "Dependency vulnerabilities (OSV-Scanner)": "osv-scanner.json",
            "Rust dependency vulnerabilities (cargo audit)": "cargo-audit.json",
            "Rails security (Brakeman)": "brakeman.json",
        }[title] in {p.name for p in out.iterdir()}:
            quality_blocks.append((title, Paragraph("No findings.", meta)))
    if syft:
        quality_blocks.append(("SBOM inventory (Syft)",
            finding_table(["Package type", "Count"],
                          [(k, v) for k, v in syft.most_common(12)],
                          [13 * cm, 4 * cm])))
    if ruby:
        quality_blocks.append(("Ruby (rubycritic)",
            finding_table(["Rating", "Complexity", "Churn", "File"], ruby[:12],
                          [2 * cm, 2.5 * cm, 2 * cm, 10.5 * cm])))
    if quality_blocks:
        story += [Spacer(1, 0.5 * cm), Paragraph("Quality and security findings", h2)]
        for title, block in quality_blocks:
            story += [Spacer(1, 0.15 * cm),
                      Paragraph(f"<b>{title}</b>", cellp), block]

    if all_findings is not None:
        story += [Spacer(1, 0.5 * cm), Paragraph("All findings", h2),
                  Paragraph(
                      f"<b>{all_findings}</b> machine-readable finding(s) in "
                      "findings.csv.", meta)]

    # legend
    story += [Spacer(1, 0.5 * cm), Paragraph("Legend", h2)]
    legend = [
        ("CCN", f"Cyclomatic complexity — independent paths through a function; "
                f"higher = harder to test. Flagged at ≥ {CCN_WARN}."),
        ("NLOC", "Non-comment lines of code, per function."),
        ("LOC", "Lines of code (excludes blanks and comments)."),
        ("max / p95 / median / mean", "The CCN distribution across all functions, not a sum."),
        ("CCN / LOC", "Total CCN ÷ lines of code; complexity normalised for size."),
        ("Complexity (scc)", "A per-language keyword heuristic that tracks size; not summed."),
        ("Dep-rule breaches", "Violated dependency rules (forbidden import, layer violation, or cycle)."),
    ]
    cell = ParagraphStyle("cell", parent=styles["Normal"], fontSize=9, leading=12)
    ldata = [[Paragraph(f"<b>{t}</b>", cell), Paragraph(m, cell)] for t, m in legend]
    lt = Table(ldata, colWidths=[4.5 * cm, 12.5 * cm])
    lt.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.white, colors.HexColor("#f1f5f9")]),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor(GRID)),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(lt)

    # definitions for the dependency rules that actually fired
    fired = triggered_rules(out)
    if fired:
        story += [Spacer(1, 0.3 * cm),
                  Paragraph("<b>Dependency rules triggered in this report</b>", cellp)]
        rrows = [[Paragraph(f"<b>{rid}</b>", cellp), Paragraph(tool, cellp),
                  Paragraph(desc, cellp)]
                 for rid, (tool, desc) in sorted(fired.items())]
        rt = Table([[Paragraph("<b>Rule</b>", cellp), Paragraph("<b>Tool</b>", cellp),
                     Paragraph("<b>Meaning</b>", cellp)]] + rrows,
                   colWidths=[4.5 * cm, 3 * cm, 9.5 * cm])
        rt.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(ACCENT)),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f1f5f9")]),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor(GRID)),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        story.append(rt)

    checks = triggered_check_rules(out)
    if checks:
        story += [Spacer(1, 0.3 * cm),
                  Paragraph("<b>Quality/security check codes triggered in this report</b>",
                            cellp)]
        crows = [[Paragraph(f"<b>{rid}</b>", cellp), Paragraph(tool, cellp),
                  Paragraph(desc, cellp)]
                 for rid, (tool, desc) in sorted(checks.items())]
        ct = Table([[Paragraph("<b>Code</b>", cellp), Paragraph("<b>Tool</b>", cellp),
                     Paragraph("<b>Meaning</b>", cellp)]] + crows,
                   colWidths=[4.5 * cm, 3 * cm, 9.5 * cm])
        ct.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(ACCENT)),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f1f5f9")]),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor(GRID)),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        story.append(ct)

    # --- reports reference --------------------------------------------------
    story += [Spacer(1, 0.5 * cm), Paragraph("Reports", h2),
              Paragraph("This PDF is a summary. Full, navigable detail is in the "
                        "companion files (same folder):", meta), Spacer(1, 0.2 * cm)]
    desc = {
        "findings.csv": "Every violation, one row each (category, tool, severity, rule, file, line, message) — load in an editor/CI to jump to source.",
        "summary.md": "Markdown version of this report.",
        "scc.json": "Per-language size & complexity.",
        "lizard.csv": "Per-function cyclomatic complexity.",
        "pmd.xml": "Full PMD violations.",
        "cpd.xml": "Duplicate code blocks with the duplicated fragments.",
        "detekt.xml": "Full detekt findings.",
        "scapegoat.xml": "Full scapegoat warnings.",
        "shellcheck.json": "Shell script findings.",
        "actionlint.json": "GitHub Actions workflow findings.",
        "hadolint.json": "Dockerfile findings.",
        "ruff.json": "Python lint findings.",
        "cargo-clippy.json": "Rust lint findings.",
        "checkov.json": "IaC security findings.",
        "betterleaks.json": "Secret scanning findings.",
        "osv-scanner.json": "Dependency vulnerability findings.",
        "cargo-audit.json": "Rust dependency vulnerability findings.",
        "syft.json": "SBOM package inventory.",
        "brakeman.json": "Rails security findings.",
        "spotbugs.xml": "JVM bytecode bug/security findings.",
        "ast-grep.json": "Dependency-rule violations.",
        "semgrep.json": "Dependency-rule / quality matches.",
        "depcruise.json": "Dependency-cruiser violations.",
        "madge-circular.json": "Circular dependency chains.",
        "rubycritic/": "Ruby complexity, churn & smells.",
    }
    rrows = []
    for name, d in desc.items():
        if (out / name.rstrip("/")).exists():
            rrows.append([Paragraph(f"<b>{name}</b>", cellp), Paragraph(d, cellp)])
    if rrows:
        rtab = Table(rrows, colWidths=[3.8 * cm, 13.2 * cm])
        rtab.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.white, colors.HexColor("#f1f5f9")]),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor(GRID)),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(rtab)

    doc.build(story)
    print(f"wrote {out/'report.pdf'}")


def main():
    out = Path(sys.argv[1])
    target = sys.argv[2] if len(sys.argv) > 2 else out.name
    build(out, target)


if __name__ == "__main__":
    main()
