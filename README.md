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

# ...or point at your own rule configs
bin/analyse.sh --config /path/to/configs /path/to/your/repo

# 3. read the summary
open reports/latest/summary.md
```

`--config DIR` overrides the rule-config directory (default: this project's
`config/`); `DIR` must mirror its layout (`ast-grep/`, `semgrep/`, `detekt/`,
etc.). The target repo defaults to the current directory.

`--sbt` additionally runs scalafix and scapegoat on sbt projects (it compiles,
so it's slow and off by default). They need the matching sbt plugins added to
the project; scapegoat is Scala 2.x only, so on a Scala 3 repo lean on lizard +
ast-grep + the compiler's own `-Wall`/`-Wunused` flags instead.

`analyse.sh` detects which languages are present and which tools are installed,
runs only what applies, and writes one report per tool plus an aggregated
`summary.md` into `reports/<timestamp>/` (symlinked as `reports/latest/`).
Missing tools are skipped with a note, never a hard failure.

## What runs

| Sensor | Tool | Languages | Output |
|---|---|---|---|
| Size / complexity / DRYness | `scc` | ~250 languages | `scc.json` |
| Cyclomatic complexity per function | `lizard` | C/C++, Java, Scala, Ruby, JS/TS, Go, Rust, Swift, … | `lizard.csv` |
| Dependency rules (custom) | `ast-grep` | tree-sitter languages | `ast-grep.json` |
| Dependency rules (custom, alt) | `semgrep` | ~30 languages | `semgrep.json` |
| Complexity / smells | `detekt` | Kotlin | `detekt.xml` |
| Complexity / duplication | `pmd` + `cpd` | Java, others | `pmd.xml`, `cpd.xml` |
| Dependency rules + cycles | `dependency-cruiser` | JS/TS | `depcruise.json` |
| Module graph / cycles | `madge` | JS/TS | `madge.json` |
| Complexity / churn / smells | `rubycritic` (`flog`, `reek`, `flay`) | Ruby | `rubycritic/` |

Architectural dependency-rule tools that require a build (ArchUnit for the JVM,
Konsist for Kotlin, packwerk for Ruby) ship as **example configs** under
`config/` rather than being run standalone — see `docs/TOOLS.md`.

## Layout

```
bin/        install.sh, analyse.sh, aggregate.py
config/     rule configs per tool (ast-grep, dependency-cruiser, semgrep,
            detekt, pmd, archunit, konsist, packwerk)
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
| `detekt/detekt.yml` | detekt | Kotlin complexity thresholds (CCN/cognitive 15, long method/params), applied with `--build-upon-default-config` |
| `pmd/ruleset.xml` | PMD | Java quickstart minus the noisiest rules, complexity pinned to CCN 15 |

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

## Appendix: glossary

Acronyms and metrics used in this toolkit and its reports.

| Term | Expansion | Meaning |
|---|---|---|
| **CCN** | Cyclomatic Complexity Number | McCabe's count of independent paths through a function (≈ branch/loop decision points + 1). A lower bound on the number of tests needed to cover it. Higher = harder to understand and test. |
| **NLOC** | Non-comment Lines Of Code | Source lines excluding blanks and comments; lizard's per-function size measure. |
| **LOC** | Lines Of Code | Source lines (scc's "Code" column excludes blanks and comments). |
| **McCabe** | — | The author of cyclomatic complexity; "McCabe complexity" = CCN. |
| **COCOMO** | Constructive Cost Model | Boehm's model estimating effort/cost/schedule from LOC; scc reports it as a rough order-of-magnitude figure. |
| **DRYness** | "Don't Repeat Yourself"-ness | scc's measure of how unique the lines are; low DRYness signals duplication. |
| **CPD** | Copy/Paste Detector | PMD's tool for finding duplicated code blocks over a token threshold. |
| **ABC** | Assignments, Branches, Conditions | The complexity metric Ruby's flog reports (related to, but not identical to, CCN). |
| **AST** | Abstract Syntax Tree | The parsed structure of code; ast-grep/semgrep match rules against it. |
| **p95 / p90** | 95th / 90th percentile | The value below which 95% (or 90%) of functions fall — used to describe the complexity *distribution* rather than a single total. |
| **median** | 50th percentile | The middle value; half of functions are below it. |
| **density (CCN/LOC)** | — | Total CCN divided by lines of code; complexity normalised for size, so big and small codebases are comparable. |
| **Ca** | Afferent coupling | Number of things that depend *on* a module (incoming). |
| **Ce** | Efferent coupling | Number of things a module depends *on* (outgoing). |
| **Instability (I)** | — | `Ce / (Ca + Ce)`, 0–1. High = easy to change but depended on by little; low = stable, hard to change safely. |
| **Abstractness (A)** | — | Ratio of abstract types to all types in a package, 0–1. |
| **churn** | — | How often a file changes in version control; high churn + high complexity = a refactoring priority. |
| **SARIF** | Static Analysis Results Interchange Format | A standard JSON format for analysis findings (e.g. detekt can emit it). |
| **CI** | Continuous Integration | Automated build/test pipeline where these sensors typically run. |
| **dependency rule** | — | A constraint on which modules may depend on which (forbidden edges, layering, no cycles) — Böckeler's second sensor type. |
