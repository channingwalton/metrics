#!/usr/bin/env bash
# Run all available static-analysis sensors over a target repo.
# Usage: bin/analyse.sh [--config DIR] [TARGET_DIR]
#   --config DIR   directory of tool rule configs (default: <project>/config)
#   TARGET_DIR     repo to analyse (default: current directory)
#
# Detects which languages are present and which tools are installed, runs only
# what applies, writes one report per tool into reports/<timestamp>/, and
# aggregates a summary.md. Missing tools are skipped, never fatal.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="${PYTHON:-python3}"   # keep in step with install.sh

# --- args -------------------------------------------------------------------
CONF="$HERE/config"
TARGET_ARG=""
while [ $# -gt 0 ]; do
  case "$1" in
    --config) CONF="$2"; shift 2 ;;
    --config=*) CONF="${1#*=}"; shift ;;
    -h|--help) sed -n '2,9p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    -*) echo "unknown option: $1" >&2; exit 2 ;;
    *) TARGET_ARG="$1"; shift ;;
  esac
done
TARGET="$(cd "${TARGET_ARG:-$PWD}" 2>/dev/null && pwd)" || { echo "no such target dir: ${TARGET_ARG:-$PWD}" >&2; exit 2; }
CONF_IN="$CONF"
CONF="$(cd "$CONF_IN" 2>/dev/null && pwd)" || { echo "no such config dir: $CONF_IN" >&2; exit 2; }

STAMP="$(date +%Y%m%d-%H%M%S)"
OUT="$HERE/reports/$STAMP"
mkdir -p "$OUT"
ln -sfn "$OUT" "$HERE/reports/latest"

say()  { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
skip() { printf '\033[1;33m  - skip: %s\033[0m\n' "$*"; }
ok()   { printf '\033[1;32m  ✓ %s\033[0m\n' "$*"; }
have() { command -v "$1" >/dev/null 2>&1; }
# present LANG_GLOB -> 0 if any matching file exists under TARGET
present() { find "$TARGET" -type f \( "$@" \) -not -path '*/node_modules/*' -not -path '*/.git/*' -print -quit 2>/dev/null | grep -q .; }

say "Target:  $TARGET"
say "Config:  $CONF"
say "Reports: $OUT"

# ---------------------------------------------------------------- polyglot ---
if have scc; then
  scc --format json --output "$OUT/scc.json" "$TARGET" 2>/dev/null && ok "scc.json (size/complexity/COCOMO)"
  scc "$TARGET" > "$OUT/scc.txt" 2>/dev/null
else skip "scc (size/complexity)"; fi

if have lizard; then
  # CSV: nloc,ccn,token,param,length,location,file,function,...
  lizard "$TARGET" --csv > "$OUT/lizard.csv" 2>/dev/null && ok "lizard.csv (per-function CCN)"
  lizard "$TARGET" --warnings_only > "$OUT/lizard-warnings.txt" 2>/dev/null
else skip "lizard (cyclomatic complexity)"; fi

# dependency rules — custom YAML rules under config/ast-grep/rules
if have ast-grep; then
  if [ -f "$CONF/ast-grep/sgconfig.yml" ]; then
    # ast-grep exits non-zero when it FINDS violations, so don't gate on rc.
    (cd "$CONF/ast-grep" && ast-grep scan --config sgconfig.yml --json=stream "$TARGET" > "$OUT/ast-grep.json" 2>/dev/null) || true
    [ -f "$OUT/ast-grep.json" ] && ok "ast-grep.json (dependency rules)"
  else skip "ast-grep (no sgconfig.yml)"; fi
else skip "ast-grep (dependency rules)"; fi

if have semgrep && [ -f "$CONF/semgrep/import-rules.yml" ]; then
  semgrep --config "$CONF/semgrep/import-rules.yml" --json --quiet "$TARGET" > "$OUT/semgrep.json" 2>/dev/null || true
  [ -s "$OUT/semgrep.json" ] && ok "semgrep.json (dependency rules)"
else skip "semgrep (dependency rules)"; fi

# ------------------------------------------------------------------ Kotlin ---
if present -name '*.kt' -o -name '*.kts'; then
  if have detekt; then
    DKCFG=""; [ -f "$CONF/detekt/detekt.yml" ] && DKCFG="--config $CONF/detekt/detekt.yml --build-upon-default-config"
    detekt --input "$TARGET" $DKCFG --report xml:"$OUT/detekt.xml" >/dev/null 2>&1
    [ -f "$OUT/detekt.xml" ] && ok "detekt.xml (Kotlin complexity/smells)"
  else skip "detekt (Kotlin present, tool missing)"; fi
fi

# -------------------------------------------------------------------- Java ---
if present -name '*.java'; then
  if have pmd; then
    PMDRULES="rulesets/java/quickstart.xml"; [ -f "$CONF/pmd/ruleset.xml" ] && PMDRULES="$CONF/pmd/ruleset.xml"
    pmd check -d "$TARGET" -R "$PMDRULES" -f xml -r "$OUT/pmd.xml" >/dev/null 2>&1
    [ -s "$OUT/pmd.xml" ] && ok "pmd.xml (Java rules)"
    pmd cpd --dir "$TARGET" --minimum-tokens 100 --language java --format xml > "$OUT/cpd.xml" 2>/dev/null
    [ -s "$OUT/cpd.xml" ] && ok "cpd.xml (Java duplication)"
  else skip "pmd (Java present, tool missing)"; fi
fi

# ----------------------------------------------------------------- TS / JS ---
if present -name '*.ts' -o -name '*.tsx' -o -name '*.js' -o -name '*.jsx'; then
  if have depcruise; then
    CFG=""; [ -f "$CONF/dependency-cruiser/.dependency-cruiser.cjs" ] && CFG="--config $CONF/dependency-cruiser/.dependency-cruiser.cjs"
    depcruise $CFG --output-type json "$TARGET" > "$OUT/depcruise.json" 2>/dev/null
    [ -s "$OUT/depcruise.json" ] && ok "depcruise.json (TS/JS dependency rules + cycles)"
  else skip "dependency-cruiser (TS/JS present, tool missing)"; fi
  if have madge; then
    madge --circular --json "$TARGET" > "$OUT/madge-circular.json" 2>/dev/null || true
    [ -s "$OUT/madge-circular.json" ] && ok "madge-circular.json (cycles)"
  else skip "madge"; fi
fi

# ------------------------------------------------------------------- Ruby ---
if present -name '*.rb'; then
  if have rubycritic; then
    rubycritic --no-browser -f json -p "$OUT/rubycritic" "$TARGET" >/dev/null 2>&1 && ok "rubycritic/ (Ruby complexity/churn/smells)"
  else skip "rubycritic (Ruby present, tool missing)"; fi
fi

# ------------------------------------------------------------------ Scala ---
# Complexity covered by lizard above. scalafix/scapegoat need sbt — see docs.
if present -name '*.scala'; then
  skip "scalafix/scapegoat (Scala: build-integrated; lizard covers CCN. See docs/TOOLS.md)"
fi

# -------------------------------------------------------------- aggregate ---
say "Aggregating summary"
"$PY" "$HERE/bin/aggregate.py" "$OUT" "$TARGET" && ok "summary.md"

# graphical PDF (skipped if matplotlib/reportlab missing)
if "$PY" -c 'import matplotlib, reportlab' 2>/dev/null; then
  "$PY" "$HERE/bin/report_pdf.py" "$OUT" "$TARGET" >/dev/null 2>&1 && ok "report.pdf"
else
  skip "report.pdf ($PY -m pip install matplotlib reportlab)"
fi
say "Open: $OUT/summary.md  |  $OUT/report.pdf"
