#!/usr/bin/env python3
"""Render a static-analysis reports dir into a graphical PDF.

Usage: report_pdf.py <reports_dir> [target_label]

Reads scc.json + lizard.csv (and optional dependency-rule reports) and produces
report.pdf with summary stat cards, a language size chart, a complexity
distribution histogram, and a top-hotspots chart + table.

Requires: matplotlib, reportlab (installed by bin/install.sh).
"""
import csv
import json
import sys
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

CCN_WARN = 15
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


def load_json(p):
    try:
        return json.loads(Path(p).read_text())
    except Exception:
        return None


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


def count_dep_violations(out):
    n = 0
    p = out / "ast-grep.json"
    if p.exists():
        for line in p.read_text().splitlines():
            line = line.strip().rstrip(",")
            if line and line not in "[]":
                try:
                    json.loads(line); n += 1
                except Exception:
                    pass
    dc = load_json(out / "depcruise.json")
    if dc:
        n += dc.get("summary", {}).get("error", 0)
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

    doc.build(story)
    print(f"wrote {out/'report.pdf'}")


def main():
    out = Path(sys.argv[1])
    target = sys.argv[2] if len(sys.argv) > 2 else out.name
    build(out, target)


if __name__ == "__main__":
    main()
