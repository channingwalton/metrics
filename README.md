# metrics — a static analysis sensor toolkit

A toolkit of open-source static analysis tools that emit machine-readable
reports for use as "sensors" for coding agents, in the sense of Birgitta
Böckeler's [Sensors for coding agents](https://martinfowler.com/articles/sensors-for-coding-agents.html#StaticCodeAnalysisDependencyRules)
(published on martinfowler.com).

It treats static analysis as two distinct sensor types:

1. **Metrics sensors** — size and complexity per file/function: cyclomatic
   complexity, LOC, maintainability, duplication, coupling/instability.
2. **Dependency-rule sensors** — architectural constraints: forbidden edges
   ("`domain` must not import `infra`"), enforced layering, no cycles.

The toolkit is **polyglot-first**: a small set of language-agnostic tools
(built on tree-sitter and similar) run over any repo, and **per-language**
tools are layered on top where deeper analysis is available.

See [`docs/TOOLS.md`](docs/TOOLS.md) for the full tool comparison and rationale.

## Quick start

```bash
# 1. install the tools (macOS / Linux)
bin/install.sh

# 2. run all available sensors over a target repo
bin/analyse.sh /path/to/your/repo

# ...or point at your own rule configs / reports location
bin/analyse.sh --config /path/to/configs --reports /path/to/reports /path/to/your/repo

# 3. read the summary
open reports/latest/summary.md
```

`--config DIR` overrides the rule-config directory (default: this project's
`config/`); `DIR` must mirror its layout (`ast-grep/`, `semgrep/`, `detekt/`,
etc.). The target repo defaults to the current directory.

`--reports DIR` sets the top-level reports folder; each run lands in
`DIR/<timestamp>/` with a `DIR/latest` symlink. Default is `./reports` in the
current directory.

`--sbt` additionally runs scalafix and scapegoat on sbt projects (it compiles,
so it's slow and off by default). They need the matching sbt plugins added to
the project; scapegoat is Scala 2.x only, so on a Scala 3 repo lean on lizard +
ast-grep + the compiler's own `-Wall`/`-Wunused` flags instead.

`analyse.sh` detects which languages are present and which tools are installed,
runs only what applies, and writes one report per tool plus an aggregated
`summary.md` into `reports/<timestamp>/` under the current directory (symlinked
as `reports/latest/`; change the reports folder with `--reports`). Missing tools
are skipped with a note, never a hard failure.

## Output files

Each run writes to `reports/<timestamp>/` (the `reports` folder defaults to the
current directory; override with `--reports DIR`) and updates `reports/latest/`.
`summary.md` and `report.pdf` are summaries; `findings.csv` holds the full
navigable detail; the rest are the raw per-tool reports. Files only appear when
the matching tool ran. A sensor that runs but produces no valid output is
dropped (not listed) and called out under a **Sensors that failed** heading in
`summary.md`, which embeds the captured stderr so you can see why; the full log
is kept at `.logs/<tool>.err`. If the summary itself can't be written, the run
prints an error and exits non-zero.

| File | What it is |
|---|---|
| `summary.md` | Markdown summary — counts, complexity distribution, top rules |
| `report.pdf` | Visual summary — stat cards, charts, hotspots |
| `findings.csv` | **Every violation, one row each** (`category, tool, severity, rule, file, line, message`) — load in an editor/CI to jump to source |
| `scc.json` / `scc.txt` | Per-language size & complexity |
| `lizard.csv` | Per-function cyclomatic complexity |
| `lizard-warnings.txt` | Functions over the complexity threshold |
| `shellcheck.json` | Shell script findings |
| `actionlint.json` | GitHub Actions workflow findings |
| `hadolint.json` | Dockerfile findings |
| `ruff.json` | Python lint findings |
| `checkov.json` | IaC / workflow security findings |
| `betterleaks.json` | Secret scanning findings |
| `ast-grep.json` | Dependency-rule violations (custom rules) |
| `semgrep.json` | Dependency-rule / quality matches |
| `detekt.xml` | Kotlin complexity & smell findings |
| `pmd.xml` / `cpd.xml` | Java rule violations / duplicate code blocks |
| `depcruise.json` | JS/TS dependency-rule violations + cycles |
| `madge-circular.json` | JS/TS circular dependency chains |
| `rubycritic/` | Ruby complexity, churn & smells (HTML/JSON) |
| `scapegoat.xml` / `scalafix.txt` | Scala inspections / lint (only with `--sbt`) |

## What runs

| Sensor | Tool | Languages | Output |
|---|---|---|---|
| Size / complexity / DRYness | `scc` | ~250 languages | `scc.json` |
| Cyclomatic complexity per function | `lizard` | C/C++, Java, Scala, Ruby, JS/TS, Go, Rust, Swift, … | `lizard.csv` |
| Shell correctness | `shellcheck` | sh, bash, ksh | `shellcheck.json` |
| Workflow correctness | `actionlint` | GitHub Actions YAML | `actionlint.json` |
| Dockerfile correctness | `hadolint` | Dockerfile | `hadolint.json` |
| Python correctness / complexity | `ruff` | Python | `ruff.json` |
| IaC / workflow security | `checkov` | Terraform, Kubernetes, Dockerfile, GitHub Actions, etc. | `checkov.json` |
| Secret scanning | `betterleaks` | Any text repo | `betterleaks.json` |
| Dependency rules (custom) | `ast-grep` | tree-sitter languages | `ast-grep.json` |
| Dependency rules (custom, alt) | `semgrep` | ~30 languages | `semgrep.json` |
| Complexity / smells | `detekt` | Kotlin | `detekt.xml` |
| Complexity / duplication | `pmd` + `cpd` | Java, others | `pmd.xml`, `cpd.xml` |
| Dependency rules + cycles | `dependency-cruiser` | JS/TS | `depcruise.json` |
| Module graph / cycles | `madge` | JS/TS | `madge-circular.json` |
| Complexity / churn / smells | `rubycritic` (`flog`, `reek`, `flay`) | Ruby | `rubycritic/` |

Architectural dependency-rule tools that require a build (ArchUnit for the JVM,
Konsist for Kotlin, packwerk for Ruby) ship as **example configs** under
`config/` rather than being run standalone — see `docs/TOOLS.md`.

## Layout

```
bin/        install.sh, analyse.sh, aggregate.py
config/     rule configs per tool (ast-grep, dependency-cruiser, semgrep,
            ruff, detekt, pmd, archunit, konsist, packwerk)
docs/       TOOLS.md — recommendation & comparison
reports/    generated output (git-ignored)
```

## Configuration

`config/` ships **balanced, ready-to-use defaults** — sensible rules that flag
real problems without burying a fresh repo in warnings. `analyse.sh` picks them
up automatically; tune or delete rules as suits your codebase.

Two kinds of config live here:

**Run automatically by `analyse.sh`:**

| Config | Tool | What it sets |
|---|---|---|
| `ast-grep/rules/layering.yml` | ast-grep | "domain must not import infra" as a forbidden-edge rule for TS/Scala/Java/Kotlin/Python |
| `ast-grep/rules/quality.yml` | ast-grep | high-confidence checks: no focused tests, no stray `console.log`/`println`, no `printStackTrace` |
| `semgrep/import-rules.yml` | semgrep | layering rules + empty-catch / focused-test / raw-SQL-in-controller checks |
| `dependency-cruiser/.dependency-cruiser.cjs` | dependency-cruiser | no cycles, no orphans, no dev-dep/test leakage into prod, domain↛infra |
| `ruff/ruff.toml` | Ruff | Python correctness rules + McCabe complexity 15 |
| `detekt/detekt.yml` | detekt | Kotlin complexity thresholds (CCN/cognitive 15, long method/params), applied with `--build-upon-default-config` |
| `pmd/ruleset.xml` | PMD | Java quickstart minus the noisiest rules, complexity pinned to CCN 15 |

Also run automatically, without project-local config: ShellCheck, actionlint,
hadolint, Checkov, and Betterleaks. Betterleaks scans the current filesystem
state with its built-in rules; validation is not enabled by default.

**Build-integrated examples** (copy into your project's test suite/app — they
need compilation or a package layout, so `analyse.sh` does not run them):

| Config | Tool | Purpose |
|---|---|---|
| `archunit/LayeredArchitectureTest.java` | ArchUnit | JVM layering, no-cycles, no field injection, naming |
| `konsist/ArchitectureKonsistTest.kt` | Konsist | Kotlin-native layering, framework-free domain, naming |
| `packwerk/` | packwerk | Ruby package boundaries — root `packwerk.yml` + `example/*/package.yml` |

**Adapting the rules.** The layering rules assume packages named `domain`,
`application`, `infrastructure` (and `web`/`api`). Search the config files for
those names and the `infra|infrastructure` regex, and swap in your own layer
names and paths. Each file is commented with what to change.

**Excluded paths.** Every sensor skips generated/vendored code so the metrics
reflect real source: `node_modules`, `.git`, `build`, `dist`, `out`, `target`,
`.gradle`, `.idea`, `vendor`, `coverage`, `.next`, `.turbo`, `.venv`,
`__pycache__`, plus `*.min.js`. Override the directory list per run with the
`EXCLUDE_DIRS` env var, e.g. `EXCLUDE_DIRS="node_modules dist generated"
bin/analyse.sh <repo>`. Tests are **not** excluded — they're analysed like
production code.
