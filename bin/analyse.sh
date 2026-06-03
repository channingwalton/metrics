#!/usr/bin/env bash
# Run all available static-analysis sensors over a target repo.
# Usage: bin/analyse.sh [--config DIR] [--reports DIR] [--sbt] [TARGET_DIR]
#   --config DIR   directory of tool rule configs (default: <project>/config)
#   --reports DIR  top-level reports folder; runs land in DIR/<timestamp>/ with a
#                  DIR/latest symlink (default: ./reports in the current directory)
#   --sbt          for sbt projects, also run scalafix/scapegoat (compiles; slow)
#   TARGET_DIR     repo to analyse (default: current directory)
#
# Detects which languages are present and which tools are installed, runs only
# what applies, writes one report per tool into <reports>/<timestamp>/, and
# aggregates a summary.md. Missing tools are skipped, never fatal.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="${PYTHON:-python3}"   # keep in step with install.sh

# --- args -------------------------------------------------------------------
CONF="$HERE/config"
REPORTS_DIR="$PWD/reports"
TARGET_ARG=""
RUN_SBT=0
while [ $# -gt 0 ]; do
  case "$1" in
    --config) CONF="$2"; shift 2 ;;
    --config=*) CONF="${1#*=}"; shift ;;
    --reports) REPORTS_DIR="$2"; shift 2 ;;
    --reports=*) REPORTS_DIR="${1#*=}"; shift ;;
    --sbt) RUN_SBT=1; shift ;;
    -h|--help) sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    -*) echo "unknown option: $1" >&2; exit 2 ;;
    *) TARGET_ARG="$1"; shift ;;
  esac
done
TARGET="$(cd "${TARGET_ARG:-$PWD}" 2>/dev/null && pwd)" || { echo "no such target dir: ${TARGET_ARG:-$PWD}" >&2; exit 2; }
CONF_IN="$CONF"
CONF="$(cd "$CONF_IN" 2>/dev/null && pwd)" || { echo "no such config dir: $CONF_IN" >&2; exit 2; }
mkdir -p "$REPORTS_DIR" 2>/dev/null || { echo "cannot create reports dir: $REPORTS_DIR" >&2; exit 2; }
REPORTS_DIR="$(cd "$REPORTS_DIR" && pwd)"

STAMP="$(date +%Y%m%d-%H%M%S)"
OUT="$REPORTS_DIR/$STAMP"
mkdir -p "$OUT"
ln -sfn "$OUT" "$REPORTS_DIR/latest"

say()  { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
skip() { printf '\033[1;33m  - skip: %s\033[0m\n' "$*"; }
ok()   { printf '\033[1;32m  ✓ %s\033[0m\n' "$*"; }
warn() { printf '\033[1;31m  ✗ %s\033[0m\n' "$*"; }
have() { command -v "$1" >/dev/null 2>&1; }

FAILED=()   # labels of sensors that ran but produced no valid output

# keep FILE KIND LABEL OKMSG
# Validate a sensor's output: keep it and print OKMSG if valid, otherwise delete
# the (empty/corrupt) file, warn, and record the failure. KIND = json|xml|text.
keep() {
  local file="$1" kind="$2" label="$3" okmsg="$4" valid=0
  if [ -s "$file" ]; then
    case "$kind" in
      json) "$PY" -c 'import json,sys; json.load(open(sys.argv[1]))' "$file" 2>/dev/null && valid=1 ;;
      xml)  "$PY" -c 'import xml.etree.ElementTree as ET,sys; ET.parse(sys.argv[1])' "$file" 2>/dev/null && valid=1 ;;
      text) valid=1 ;;
    esac
  fi
  if [ "$valid" = 1 ]; then ok "$okmsg"
  else rm -f "$file"; warn "$label failed (no valid output)"; FAILED+=("$label"); fi
}

# Generated/vendored directories excluded from every sensor. Override with
# EXCLUDE_DIRS="dir1 dir2 ..." in the environment.
IFS=' ' read -r -a IGNORE_DIRS <<< "${EXCLUDE_DIRS:-node_modules .git build dist out target .gradle .idea vendor coverage .next .turbo .venv __pycache__}"

# Build the per-tool exclude arguments from IGNORE_DIRS (+ minified files).
FIND_PRUNE=(); SCC_EXCLUDE=""; LIZARD_X=(-x "*.min.js"); AG_GLOBS=(--globs '!**/*.min.js'); SG_EXCLUDE=(--exclude '*.min.js')
for d in "${IGNORE_DIRS[@]}"; do
  FIND_PRUNE+=( -not -path "*/$d/*" )
  SCC_EXCLUDE="${SCC_EXCLUDE:+$SCC_EXCLUDE,}$d"
  LIZARD_X+=( -x "*/$d/*" )
  AG_GLOBS+=( --globs "!**/$d/**" )
  SG_EXCLUDE+=( --exclude "$d" )
done
DETEKT_EXC="$(printf '**/%s/**,' "${IGNORE_DIRS[@]}")"; DETEKT_EXC="${DETEKT_EXC%,}"

# present LANG_GLOB -> 0 if any matching file exists under TARGET
present() { find "$TARGET" -type f \( "$@" \) "${FIND_PRUNE[@]}" -print -quit 2>/dev/null | grep -q .; }

say "Target:  $TARGET"
say "Config:  $CONF"
say "Reports: $OUT"
say "Ignored: ${IGNORE_DIRS[*]}"

# ---------------------------------------------------------------- polyglot ---
if have scc; then
  scc --format json --exclude-dir "$SCC_EXCLUDE" -M '\.min\.js$' --output "$OUT/scc.json" "$TARGET" 2>/dev/null || true
  scc --exclude-dir "$SCC_EXCLUDE" -M '\.min\.js$' "$TARGET" > "$OUT/scc.txt" 2>/dev/null || true
  keep "$OUT/scc.json" json scc "scc.json (size/complexity/COCOMO)"
else skip "scc (size/complexity)"; fi

if have lizard; then
  # CSV: nloc,ccn,token,param,length,location,file,function,...
  lizard "$TARGET" "${LIZARD_X[@]}" --csv > "$OUT/lizard.csv" 2>/dev/null || true
  lizard "$TARGET" "${LIZARD_X[@]}" --warnings_only > "$OUT/lizard-warnings.txt" 2>/dev/null || true
  keep "$OUT/lizard.csv" text lizard "lizard.csv (per-function CCN)"
else skip "lizard (cyclomatic complexity)"; fi

# dependency rules — custom YAML rules under config/ast-grep/rules
if have ast-grep; then
  if [ -f "$CONF/ast-grep/sgconfig.yml" ]; then
    # --json (array) always writes valid JSON ([] when clean), so we can tell a
    # genuine "no violations" apart from a tool failure.
    (cd "$CONF/ast-grep" && ast-grep scan --config sgconfig.yml "${AG_GLOBS[@]}" --json "$TARGET" > "$OUT/ast-grep.json" 2>/dev/null) || true
    keep "$OUT/ast-grep.json" json ast-grep "ast-grep.json (dependency rules)"
  else skip "ast-grep (no sgconfig.yml)"; fi
else skip "ast-grep (dependency rules)"; fi

if have semgrep && [ -f "$CONF/semgrep/import-rules.yml" ]; then
  semgrep --config "$CONF/semgrep/import-rules.yml" "${SG_EXCLUDE[@]}" --json --quiet "$TARGET" > "$OUT/semgrep.json" 2>/dev/null || true
  keep "$OUT/semgrep.json" json semgrep "semgrep.json (dependency rules)"
else skip "semgrep (dependency rules)"; fi

# ------------------------------------------------------------------ Kotlin ---
if present -name '*.kt' -o -name '*.kts'; then
  if have detekt; then
    DKCFG=""; [ -f "$CONF/detekt/detekt.yml" ] && DKCFG="--config $CONF/detekt/detekt.yml --build-upon-default-config"
    detekt --input "$TARGET" --excludes "$DETEKT_EXC" $DKCFG --report xml:"$OUT/detekt.xml" >/dev/null 2>&1 || true
    keep "$OUT/detekt.xml" xml detekt "detekt.xml (Kotlin complexity/smells)"
  else skip "detekt (Kotlin present, tool missing)"; fi
fi

# -------------------------------------------------------------------- Java ---
if present -name '*.java'; then
  if have pmd; then
    PMDRULES="rulesets/java/quickstart.xml"; [ -f "$CONF/pmd/ruleset.xml" ] && PMDRULES="$CONF/pmd/ruleset.xml"
    # PMD/CPD have no glob-exclude, so pass an explicit file list honouring IGNORE_DIRS.
    JAVA_LIST="$OUT/.java-files"
    find "$TARGET" -type f -name '*.java' "${FIND_PRUNE[@]}" > "$JAVA_LIST" 2>/dev/null || true
    if [ -s "$JAVA_LIST" ]; then
      pmd check --file-list "$JAVA_LIST" -R "$PMDRULES" -f xml -r "$OUT/pmd.xml" >/dev/null 2>&1 || true
      keep "$OUT/pmd.xml" xml pmd "pmd.xml (Java rules)"
      pmd cpd --file-list "$JAVA_LIST" --minimum-tokens 100 --language java --format xml > "$OUT/cpd.xml" 2>/dev/null || true
      keep "$OUT/cpd.xml" xml cpd "cpd.xml (Java duplication)"
    else skip "pmd/cpd (no Java files after exclusions)"; fi
    rm -f "$JAVA_LIST"
  else skip "pmd (Java present, tool missing)"; fi
fi

# ----------------------------------------------------------------- TS / JS ---
if present -name '*.ts' -o -name '*.tsx' -o -name '*.js' -o -name '*.jsx'; then
  if have depcruise; then
    CFG=""; [ -f "$CONF/dependency-cruiser/.dependency-cruiser.cjs" ] && CFG="--config $CONF/dependency-cruiser/.dependency-cruiser.cjs"
    depcruise $CFG --output-type json "$TARGET" > "$OUT/depcruise.json" 2>/dev/null || true
    keep "$OUT/depcruise.json" json dependency-cruiser "depcruise.json (TS/JS dependency rules + cycles)"
  else skip "dependency-cruiser (TS/JS present, tool missing)"; fi
  if have madge; then
    madge --circular --json "$TARGET" > "$OUT/madge-circular.json" 2>/dev/null || true
    keep "$OUT/madge-circular.json" json madge "madge-circular.json (cycles)"
  else skip "madge"; fi
fi

# ------------------------------------------------------------------- Ruby ---
if present -name '*.rb'; then
  if have rubycritic; then
    rubycritic --no-browser -f json -p "$OUT/rubycritic" "$TARGET" >/dev/null 2>&1 && ok "rubycritic/ (Ruby complexity/churn/smells)"
  else skip "rubycritic (Ruby present, tool missing)"; fi
fi

# ------------------------------------------------------------------ Scala ---
# Complexity covered by lizard above. scalafix/scapegoat need sbt to compile, so
# they run only with --sbt and only when the target is an sbt project.
if present -name '*.scala'; then
  if [ "$RUN_SBT" = "1" ] && [ -f "$TARGET/build.sbt" ] && have sbt; then
    say "Scala: running sbt (compiles — this can be slow)"
    # scapegoat: Scala 2.x only; harmless no-op / failure on Scala 3 (captured).
    (cd "$TARGET" && sbt -batch -error scapegoat >/dev/null 2>&1) || true
    SG="$(find "$TARGET" -path '*scapegoat-report/scapegoat.xml' -print -quit 2>/dev/null)"
    if [ -n "$SG" ]; then cp "$SG" "$OUT/scapegoat.xml"; ok "scapegoat.xml (Scala inspections)"
    else skip "scapegoat (no report — Scala 3 or plugin not added; see docs)"; fi
    # scalafix: needs the sbt-scalafix plugin + a .scalafix.conf in the project.
    if (cd "$TARGET" && sbt -batch -error "scalafixAll --check" > "$OUT/scalafix.txt" 2>&1); then
      ok "scalafix.txt (no rule violations)"
    elif [ -s "$OUT/scalafix.txt" ]; then ok "scalafix.txt (output captured)"
    else skip "scalafix (plugin/.scalafix.conf not set up; see docs)"; fi
  elif [ "$RUN_SBT" = "1" ]; then
    skip "scalafix/scapegoat (--sbt set but no build.sbt or sbt not installed)"
  else
    skip "scalafix/scapegoat (pass --sbt for sbt projects; lizard covers CCN)"
  fi
fi

# record failed sensors so the summary can report them
if [ ${#FAILED[@]} -gt 0 ]; then printf '%s\n' "${FAILED[@]}" > "$OUT/.failures"; fi

# -------------------------------------------------------------- aggregate ---
say "Aggregating summary"
AGG_OK=0
if "$PY" "$HERE/bin/aggregate.py" "$OUT" "$TARGET"; then ok "summary.md"; AGG_OK=1
else warn "aggregation failed — summary.md not written"; fi

# graphical PDF (independent of the markdown; skipped if libs missing)
if "$PY" -c 'import matplotlib, reportlab' 2>/dev/null; then
  if "$PY" "$HERE/bin/report_pdf.py" "$OUT" "$TARGET" >/dev/null 2>&1; then ok "report.pdf"
  else warn "report.pdf generation failed"; fi
else
  skip "report.pdf ($PY -m pip install matplotlib reportlab)"
fi

# Point only at files that actually exist.
say "Reports in: $OUT"
[ -f "$OUT/summary.md" ]   && say "  summary:  $OUT/summary.md"
[ -f "$OUT/report.pdf" ]   && say "  pdf:      $OUT/report.pdf"
[ -f "$OUT/findings.csv" ] && say "  findings: $OUT/findings.csv"
[ ${#FAILED[@]} -gt 0 ]    && warn "sensors that failed: ${FAILED[*]}"

# Fail the run if the summary could not be produced.
[ "$AGG_OK" = 1 ] || exit 1
