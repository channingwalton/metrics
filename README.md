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

# 3. read the summary
open reports/latest/summary.md
```

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
config/     example rule configs per tool (ast-grep, dependency-cruiser,
            semgrep, archunit, konsist, packwerk)
docs/       TOOLS.md — recommendation & comparison
reports/    generated output (git-ignored)
```
