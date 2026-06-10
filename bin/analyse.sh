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
LOGDIR="$OUT/.logs"
mkdir -p "$LOGDIR"
ln -sfn "$OUT" "$REPORTS_DIR/latest"

say()  { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
skip() { printf '\033[1;33m  - skip: %s\033[0m\n' "$*"; }
ok()   { printf '\033[1;32m  ✓ %s\033[0m\n' "$*"; }
warn() { printf '\033[1;31m  ✗ %s\033[0m\n' "$*"; }
have() { command -v "$1" >/dev/null 2>&1; }

FAILED=()   # labels of sensors that ran but produced no valid output

# errlog LABEL -> the stderr log path for a sensor (redirect its 2> here).
errlog() { printf '%s/%s.err' "$LOGDIR" "$1"; }

# keep FILE KIND LABEL OKMSG [RC]
# Validate a sensor's output: keep it (+OKMSG) if valid, else delete the
# empty/corrupt file, retain its stderr log, warn, and record the failure.
# KIND = json|xml (validity = parses; non-zero rc from "findings" is fine) or
# text (validity = the tool exited 0; an empty file is allowed). RC defaults 0.
# Each sensor must redirect 2> "$(errlog LABEL)".
keep() {
  local file="$1" kind="$2" label="$3" okmsg="$4" rc="${5:-0}" log valid=0
  log="$(errlog "$label")"
  case "$kind" in
    json) [ -s "$file" ] && "$PY" -c 'import json,sys; json.load(open(sys.argv[1]))' "$file" 2>/dev/null && valid=1 ;;
    xml)  [ -s "$file" ] && "$PY" -c 'import xml.etree.ElementTree as ET,sys; ET.parse(sys.argv[1])' "$file" 2>/dev/null && valid=1 ;;
    text) [ "$rc" = 0 ] && valid=1 ;;
  esac
  if [ "$valid" = 1 ]; then ok "$okmsg"; rm -f "$log"
  else
    rm -f "$file"
    [ -s "$log" ] || echo "(no stderr captured)" > "$log"
    warn "$label failed — see .logs/$label.err"
    FAILED+=("$label")
  fi
}

# record_fail LABEL : mark a non-keep sensor (e.g. rubycritic) as failed.
record_fail() {
  local label="$1" log; log="$(errlog "$label")"
  [ -s "$log" ] || echo "(no stderr captured)" > "$log"
  warn "$label failed — see .logs/$label.err"
  FAILED+=("$label")
}

# Generated/vendored directories excluded from every sensor. Override with
# EXCLUDE_DIRS="dir1 dir2 ..." in the environment.
IFS=' ' read -r -a IGNORE_DIRS <<< "${EXCLUDE_DIRS:-node_modules .git build dist out target .gradle .idea vendor coverage .next .turbo .venv __pycache__}"

# Build the per-tool exclude arguments from IGNORE_DIRS (+ minified files).
FIND_PRUNE=(); SCC_EXCLUDE=""; LIZARD_X=(-x "*.min.js"); AG_GLOBS=(--globs '!**/*.min.js'); SG_EXCLUDE=(--exclude '*.min.js')
RUFF_EXCLUDE=(); CHECKOV_SKIP=()
SYFT_EXCLUDE=(--exclude '**/*.min.js')
for d in "${IGNORE_DIRS[@]}"; do
  FIND_PRUNE+=( -not -path "*/$d/*" )
  SCC_EXCLUDE="${SCC_EXCLUDE:+$SCC_EXCLUDE,}$d"
  LIZARD_X+=( -x "*/$d/*" )
  AG_GLOBS+=( --globs "!**/$d/**" )
  SG_EXCLUDE+=( --exclude "$d" )
  RUFF_EXCLUDE+=( --exclude "$d" )
  CHECKOV_SKIP+=( --skip-path "$d" )
  SYFT_EXCLUDE+=( --exclude "**/$d/**" )
done
DETEKT_EXC="$(printf '**/%s/**,' "${IGNORE_DIRS[@]}")"; DETEKT_EXC="${DETEKT_EXC%,}"

# present LANG_GLOB -> 0 if any matching file exists under TARGET
present() { find "$TARGET" -type f \( "$@" \) "${FIND_PRUNE[@]}" -print -quit 2>/dev/null | grep -q .; }

# rails_app -> 0 if TARGET looks like a Rails app.
rails_app() { [ -f "$TARGET/config/application.rb" ] || [ -f "$TARGET/config/environment.rb" ]; }

dependency_manifest_present() {
  present -name 'package-lock.json' -o -name 'yarn.lock' -o \
    -name 'pnpm-lock.yaml' -o -name 'bun.lock' -o -name 'bun.lockb' -o \
    -name 'Gemfile.lock' -o -name 'go.mod' -o -name 'Cargo.lock' -o \
    -name 'Pipfile.lock' -o -name 'poetry.lock' -o -name 'requirements*.txt' -o \
    -name 'pom.xml' -o -name 'build.gradle' -o -name 'build.gradle.kts' -o \
    -name 'gradle.lockfile' -o -name 'build.sbt' -o \
    -name 'project.assets.json' -o -name 'packages.lock.json' -o \
    -name 'composer.lock' -o -name 'mix.lock' -o -name 'deno.lock'
}

say "Target:  $TARGET"
say "Config:  $CONF"
say "Reports: $OUT"
say "Ignored: ${IGNORE_DIRS[*]}"

# ---------------------------------------------------------------- polyglot ---
if have scc; then
  scc --format json --exclude-dir "$SCC_EXCLUDE" -M '\.min\.js$' --output "$OUT/scc.json" "$TARGET" 2> "$(errlog scc)" || true
  scc --exclude-dir "$SCC_EXCLUDE" -M '\.min\.js$' "$TARGET" > "$OUT/scc.txt" 2>/dev/null || true
  keep "$OUT/scc.json" json scc "scc.json (size/complexity/COCOMO)"
else skip "scc (size/complexity)"; fi

if have lizard; then
  # CSV: nloc,ccn,token,param,length,location,file,function,...
  lizard "$TARGET" "${LIZARD_X[@]}" --csv > "$OUT/lizard.csv" 2> "$(errlog lizard)"; LZ_RC=$?
  lizard "$TARGET" "${LIZARD_X[@]}" --warnings_only > "$OUT/lizard-warnings.txt" 2>/dev/null || true
  keep "$OUT/lizard.csv" text lizard "lizard.csv (per-function CCN)" "$LZ_RC"
else skip "lizard (cyclomatic complexity)"; fi

# shell scripts
if present -name '*.sh' -o -name '*.bash' -o -name '*.bats'; then
  if have shellcheck; then
    SH_LIST="$OUT/.shell-files"
    find "$TARGET" -type f \( -name '*.sh' -o -name '*.bash' -o -name '*.bats' \) "${FIND_PRUNE[@]}" > "$SH_LIST" 2>/dev/null || true
    if [ -s "$SH_LIST" ]; then
      SH_FILES=()
      while IFS= read -r f; do SH_FILES+=( "$f" ); done < "$SH_LIST"
      shellcheck --format=json "${SH_FILES[@]}" > "$OUT/shellcheck.json" 2> "$(errlog shellcheck)" || true
      keep "$OUT/shellcheck.json" json shellcheck "shellcheck.json (shell script findings)"
    else skip "shellcheck (no shell files after exclusions)"; fi
    rm -f "$SH_LIST"
  else skip "shellcheck (shell scripts present, tool missing)"; fi
fi

# GitHub Actions workflows
if present -path '*/.github/workflows/*.yml' -o -path '*/.github/workflows/*.yaml'; then
  if have actionlint; then
    (cd "$TARGET" && actionlint -format '{{json .}}' > "$OUT/actionlint.json" 2> "$(errlog actionlint)") || true
    keep "$OUT/actionlint.json" json actionlint "actionlint.json (GitHub Actions workflows)"
  else skip "actionlint (GitHub Actions workflows present, tool missing)"; fi
fi

# Dockerfiles
if present -name 'Dockerfile' -o -name 'Dockerfile.*' -o -name '*.Dockerfile' -o -iname '*.dockerfile'; then
  if have hadolint; then
    DOCKER_LIST="$OUT/.dockerfiles"
    find "$TARGET" -type f \( -name 'Dockerfile' -o -name 'Dockerfile.*' -o -name '*.Dockerfile' -o -iname '*.dockerfile' \) "${FIND_PRUNE[@]}" > "$DOCKER_LIST" 2>/dev/null || true
    if [ -s "$DOCKER_LIST" ]; then
      DOCKER_FILES=()
      while IFS= read -r f; do DOCKER_FILES+=( "$f" ); done < "$DOCKER_LIST"
      hadolint --format json "${DOCKER_FILES[@]}" > "$OUT/hadolint.json" 2> "$(errlog hadolint)" || true
      keep "$OUT/hadolint.json" json hadolint "hadolint.json (Dockerfile findings)"
    else skip "hadolint (no Dockerfiles after exclusions)"; fi
    rm -f "$DOCKER_LIST"
  else skip "hadolint (Dockerfiles present, tool missing)"; fi
fi

# Python lint
if present -name '*.py'; then
  if have ruff; then
    RUFFCFG=(); [ -f "$CONF/ruff/ruff.toml" ] && RUFFCFG=(--config "$CONF/ruff/ruff.toml")
    ruff check --output-format json "${RUFFCFG[@]}" "${RUFF_EXCLUDE[@]}" "$TARGET" > "$OUT/ruff.json" 2> "$(errlog ruff)" || true
    keep "$OUT/ruff.json" json ruff "ruff.json (Python lint findings)"
  else skip "ruff (Python present, tool missing)"; fi
fi

# IaC / workflow security
if present -name '*.tf' -o -name '*.tf.json' -o -name '*.bicep' -o -name 'Dockerfile' -o -name 'Dockerfile.*' -o -name '*.Dockerfile' -o -iname '*.dockerfile' -o -name 'Chart.yaml' -o -iname 'kustomization.yaml' -o -name 'serverless.yml' -o -name 'serverless.yaml' -o -path '*/.github/workflows/*.yml' -o -path '*/.github/workflows/*.yaml'; then
  if have checkov; then
    checkov --directory "$TARGET" --output json --quiet "${CHECKOV_SKIP[@]}" > "$OUT/checkov.json" 2> "$(errlog checkov)" || true
    keep "$OUT/checkov.json" json checkov "checkov.json (IaC security findings)"
  else skip "checkov (IaC/workflow files present, tool missing)"; fi
fi

# secrets
if have betterleaks; then
  betterleaks dir "$TARGET" --max-target-megabytes 20 --report-path "$OUT/betterleaks.json" --report-format json --exit-code 0 > /dev/null 2> "$(errlog betterleaks)" || true
  keep "$OUT/betterleaks.json" json betterleaks "betterleaks.json (secret scanning findings)"
else skip "betterleaks (secret scanning)"; fi

# dependency vulnerabilities
if dependency_manifest_present; then
  if have osv-scanner; then
    osv-scanner scan --format json "$TARGET" > "$OUT/osv-scanner.json" 2> "$(errlog osv-scanner)" || true
    keep "$OUT/osv-scanner.json" json osv-scanner "osv-scanner.json (dependency vulnerabilities)"
  else skip "osv-scanner (dependency manifests present, tool missing)"; fi
fi

# software bill of materials
if have syft; then
  syft dir:"$TARGET" -o syft-json "${SYFT_EXCLUDE[@]}" > "$OUT/syft.json" 2> "$(errlog syft)" || true
  keep "$OUT/syft.json" json syft "syft.json (SBOM package inventory)"
else skip "syft (SBOM inventory)"; fi

# dependency rules — custom YAML rules under config/ast-grep/rules
if have ast-grep; then
  if [ -f "$CONF/ast-grep/sgconfig.yml" ]; then
    # --json (array) always writes valid JSON ([] when clean), so we can tell a
    # genuine "no violations" apart from a tool failure.
    (cd "$CONF/ast-grep" && ast-grep scan --config sgconfig.yml "${AG_GLOBS[@]}" --json "$TARGET" > "$OUT/ast-grep.json" 2> "$(errlog ast-grep)") || true
    keep "$OUT/ast-grep.json" json ast-grep "ast-grep.json (dependency rules)"
  else skip "ast-grep (no sgconfig.yml)"; fi
else skip "ast-grep (dependency rules)"; fi

if have semgrep && [ -f "$CONF/semgrep/import-rules.yml" ]; then
  semgrep --config "$CONF/semgrep/import-rules.yml" "${SG_EXCLUDE[@]}" --json --quiet "$TARGET" > "$OUT/semgrep.json" 2> "$(errlog semgrep)" || true
  keep "$OUT/semgrep.json" json semgrep "semgrep.json (dependency rules)"
else skip "semgrep (dependency rules)"; fi

# ------------------------------------------------------------------ Kotlin ---
if present -name '*.kt' -o -name '*.kts'; then
  if have detekt; then
    DKCFG=""; [ -f "$CONF/detekt/detekt.yml" ] && DKCFG="--config $CONF/detekt/detekt.yml --build-upon-default-config"
    detekt --input "$TARGET" --excludes "$DETEKT_EXC" $DKCFG --report xml:"$OUT/detekt.xml" >/dev/null 2> "$(errlog detekt)" || true
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
      pmd check --file-list "$JAVA_LIST" -R "$PMDRULES" -f xml -r "$OUT/pmd.xml" >/dev/null 2> "$(errlog pmd)" || true
      keep "$OUT/pmd.xml" xml pmd "pmd.xml (Java rules)"
      pmd cpd --file-list "$JAVA_LIST" --minimum-tokens 100 --language java --format xml > "$OUT/cpd.xml" 2> "$(errlog cpd)" || true
      keep "$OUT/cpd.xml" xml cpd "cpd.xml (Java duplication)"
    else skip "pmd/cpd (no Java files after exclusions)"; fi
    rm -f "$JAVA_LIST"
  else skip "pmd (Java present, tool missing)"; fi
fi

# JVM bytecode bug/security checks. SpotBugs needs compiled classes, so it only
# runs when build outputs already exist; the wrapper does not compile projects.
if present -name '*.java' -o -name '*.kt' -o -name '*.kts' -o -name '*.scala'; then
  if have spotbugs; then
    SPOTBUGS_INPUTS=()
    while IFS= read -r d; do SPOTBUGS_INPUTS+=( "$d" ); done < <(
      find "$TARGET" -type d \( \
        -path '*/target/classes' -o \
        -path '*/target/scala-*/classes' -o \
        -path '*/build/classes/java/main' -o \
        -path '*/build/classes/kotlin/main' -o \
        -path '*/build/classes/scala/main' -o \
        -path '*/out/production/*' -o \
        -path '*/classes' \
      \) -print 2>/dev/null | sort -u
    )
    if [ ${#SPOTBUGS_INPUTS[@]} -gt 0 ]; then
      SPOTBUGS_ARGS=(-textui -xml:withMessages="$OUT/spotbugs.xml" -effort:default -medium)
      [ -n "${SPOTBUGS_PLUGIN_LIST:-}" ] && SPOTBUGS_ARGS+=( -pluginList "$SPOTBUGS_PLUGIN_LIST" )
      spotbugs "${SPOTBUGS_ARGS[@]}" "${SPOTBUGS_INPUTS[@]}" >/dev/null 2> "$(errlog spotbugs)" || true
      keep "$OUT/spotbugs.xml" xml spotbugs "spotbugs.xml (JVM bytecode bug/security findings)"
    else skip "spotbugs (JVM sources present, no compiled classes found)"; fi
  else skip "spotbugs (JVM sources present, tool missing)"; fi
fi

# ----------------------------------------------------------------- TS / JS ---
if present -name '*.ts' -o -name '*.tsx' -o -name '*.js' -o -name '*.jsx'; then
  if have depcruise; then
    CFG=""; [ -f "$CONF/dependency-cruiser/.dependency-cruiser.cjs" ] && CFG="--config $CONF/dependency-cruiser/.dependency-cruiser.cjs"
    depcruise $CFG --output-type json "$TARGET" > "$OUT/depcruise.json" 2> "$(errlog dependency-cruiser)" || true
    keep "$OUT/depcruise.json" json dependency-cruiser "depcruise.json (TS/JS dependency rules + cycles)"
  else skip "dependency-cruiser (TS/JS present, tool missing)"; fi
  if have madge; then
    madge --circular --json "$TARGET" > "$OUT/madge-circular.json" 2> "$(errlog madge)" || true
    keep "$OUT/madge-circular.json" json madge "madge-circular.json (cycles)"
  else skip "madge"; fi
fi

# ------------------------------------------------------------------- Ruby ---
if present -name '*.rb'; then
  if have rubycritic; then
    if rubycritic --no-browser -f json -p "$OUT/rubycritic" "$TARGET" >/dev/null 2> "$(errlog rubycritic)"; then
      ok "rubycritic/ (Ruby complexity/churn/smells)"; rm -f "$(errlog rubycritic)"
    else record_fail rubycritic; fi
  else skip "rubycritic (Ruby present, tool missing)"; fi
  if rails_app; then
    if have brakeman; then
      brakeman -q --no-exit-on-warn --no-exit-on-error -f json -o "$OUT/brakeman.json" -p "$TARGET" >/dev/null 2> "$(errlog brakeman)" || true
      keep "$OUT/brakeman.json" json brakeman "brakeman.json (Rails security findings)"
    else skip "brakeman (Rails app present, tool missing)"; fi
  else skip "brakeman (Ruby present, no Rails app detected)"; fi
fi

# ------------------------------------------------------------------ Scala ---
# Complexity covered by lizard above. scalafix/scapegoat need sbt to compile, so
# they run only with --sbt and only when the target is an sbt project.
if present -name '*.scala'; then
  if [ "$RUN_SBT" = "1" ] && [ -f "$TARGET/build.sbt" ] && have sbt; then
    say "Scala: running sbt (compiles — this can be slow)"
    # scapegoat: Scala 2.x only; harmless no-op / failure on Scala 3 (captured).
    (cd "$TARGET" && sbt -batch -error scapegoat > "$(errlog scapegoat)" 2>&1) || true
    SG="$(find "$TARGET" -path '*scapegoat-report/scapegoat.xml' -print -quit 2>/dev/null)"
    if [ -n "$SG" ]; then cp "$SG" "$OUT/scapegoat.xml"; ok "scapegoat.xml (Scala inspections)"; rm -f "$(errlog scapegoat)"
    else skip "scapegoat (no report — Scala 3 or plugin not added; see docs)"; fi
    # scalafix: needs the sbt-scalafix plugin + a .scalafix.conf in the project.
    if (cd "$TARGET" && sbt -batch -error "scalafixAll --check" > "$OUT/scalafix.txt" 2>/dev/null); then
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
