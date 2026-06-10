# Tool selection & comparison

Goal: open-source static analysis "sensors" producing machine-readable reports,
covering **metrics** (complexity, size, coupling) and **dependency rules**
(architectural constraints), across Scala, Kotlin, Java, Ruby, TypeScript/JS,
and "many more" — hence a tree-sitter / polyglot backbone.

The two sensor types map directly onto Böckeler's framing: ordinary metrics are
local complexity/size measures; *dependency rules* build a graph over
modules/packages and check user-defined constraints (forbidden edges, layering,
cycles).

## 1. Polyglot backbone (run everywhere)

These cover the long tail of languages with zero per-language setup. Prefer
these first; add per-language tools only where they buy real depth.

| Tool | Sensor type | What it gives | Why chosen |
|---|---|---|---|
| **scc** | Metrics | LOC, comment ratio, an estimated complexity score, COCOMO cost, and DRYness/uniqueness — across ~250 languages, very fast, native JSON. | Best single "how big / how complex overall" sensor; trivial to run in CI. |
| **lizard** | Metrics | *True* cyclomatic complexity (CCN) and token/parameter counts **per function**, with threshold warnings. Supports C/C++, Java, C#, JS, Python, Ruby, PHP, Swift, **Scala**, Go, Lua, Rust, TypeScript, and more. | The per-function complexity workhorse; flags hotspots scc's heuristic can't. (No Kotlin — use detekt there.) |
| **ShellCheck** | Quality | Static analysis for shell scripts; catches quoting, portability, syntax, and semantic traps. | High signal for the glue scripts that run builds and agents. JSON output is easy to aggregate. |
| **actionlint** | Quality / security | Static checker for GitHub Actions workflow files, including expression checks and unsafe workflow patterns. | CI config is code; workflow breakage blocks delivery and can create supply-chain risk. |
| **hadolint** | Quality / security | Dockerfile linting with ShellCheck coverage for inline shell in `RUN` instructions. | Containers are common deployment glue, and Dockerfile mistakes often escape language linters. |
| **checkov** | Security | IaC and workflow security checks for Terraform, Kubernetes, Dockerfile, GitHub Actions, and related formats. | Adds cloud/config posture checks without needing the target project to compile. |
| **betterleaks** | Security | Secrets scanner for files, git, stdin, GitHub, GitLab, S3-compatible sources; supports JSON/SARIF output and CEL filters. | Better primary secrets sensor than Gitleaks now: same lineage, active development, richer filtering/validation. |
| **OSV-Scanner** | Security | Known-vulnerability checks for dependency lockfiles, manifests, SBOMs, and container images; JSON/SARIF output. | Fills the dependency-CVE gap left by IaC/secrets scanners, using the open OSV advisory database. |
| **Syft** | Supply chain inventory | SBOM/package inventory for source trees, filesystems, archives, and container images; Syft JSON/CycloneDX/SPDX output. | Gives agents the package inventory behind dependency risk, even when no vulnerability is currently reported. |
| **ast-grep** | Dependency rules | Structural search/lint over tree-sitter ASTs; custom rules in YAML. Use it to express "no import of X from Y", banned APIs, layering checks — in *any* tree-sitter language. | The polyglot way to do architectural dependency rules without a per-language framework. Fast (Rust), JSON output. |
| **semgrep** | Dependency rules | Same idea as ast-grep with a larger curated rule registry and ~30 languages; richer pattern logic (metavariables, taint). | Good alternative/complement to ast-grep for import-direction and forbidden-dependency rules; strong security overlap. |

Why two dependency-rule tools: `ast-grep` is lighter and easier for bespoke
import rules; `semgrep` has a bigger ecosystem and cross-file dataflow. Start
with `ast-grep`; reach for `semgrep` when you need its registry or taint
tracking.

### Limits of the polyglot layer

ast-grep/semgrep see *imports and call sites*, not a resolved
package-dependency graph. For true afferent/efferent coupling, instability,
abstractness and cycle-detection over a compiled module graph you still want a
JVM-aware tool (below). The polyglot rules catch the common "forbidden edge"
cases cheaply; the JVM tools catch the structural ones precisely.

## 2. Per-language depth

### Scala (JVM)
- **scalafix** — semantic + syntactic rules; can encode dependency rules.
- **scapegoat** — compiler-plugin inspections (code smells, complexity).
- **scalastyle** — style + size/complexity thresholds.
- **sbt-dependency-graph** / **sbt** `moduleGraph` — module dependency graphs.
- Complexity per method is also covered by **lizard** (no build needed), which
  is why the scaffold uses lizard for Scala and leaves scalafix/scapegoat as
  build-integrated recommendations (they need sbt + compilation).

### Kotlin (JVM)
- **detekt** — the standard: complexity (cyclomatic, cognitive), long methods,
  too-many-params, smells. Has a standalone CLI (`detekt-cli`) — *runnable
  without Gradle*, so the scaffold runs it directly. XML/SARIF/HTML output.
- **Konsist** — Kotlin-native architecture testing: layering, package
  structure, dependency direction, naming. Runs as unit tests (needs the build).
  Shipped as an example test in `config/konsist/`.
- **ArchUnit** also works on Kotlin (JVM bytecode) with the caveat that
  Kotlin-only features (extension/top-level functions) aren't fully modelled.

### Java / JVM
- **PMD** — complexity rules, plus **CPD** copy-paste/duplication detector;
  standalone CLI, runnable without a build → used directly by the scaffold.
- **SpotBugs** — bytecode-level bug detection for compiled JVM classes, with
  optional plugins such as FindSecBugs for security patterns. The scaffold runs
  it only when compiled class directories already exist; it does not build the
  project.
- **ArchUnit** — the JVM dependency-rule tool: package/class/layer dependencies,
  cyclic-dependency checks, slices. Runs as tests against compiled bytecode.
  Example in `config/archunit/`.
- **jdepend** — classic afferent/efferent coupling, instability, abstractness,
  distance-from-main-sequence. Good for the stability metrics;
  largely subsumed by ArchUnit for rule enforcement but still useful for the raw
  numbers.
- **checkstyle** — style + some size/complexity metrics.

### Python
- **Ruff** — fast Python linting, with Pyflakes, selected pycodestyle errors,
  bugbear checks, and McCabe complexity. The scaffold keeps it focused on
  correctness/maintainability and ignores formatting churn.

### Ruby
- **flog** — ABC complexity per method (Ruby's de-facto complexity score).
- **reek** — code smells (incl. coupling-related: feature envy, data clumps).
- **flay** — structural duplication.
- **rubycritic** — aggregates flog + reek + flay + churn into one report (and a
  graded score). The scaffold runs rubycritic so you get all three at once.
- **brakeman** — Rails-specific static security scanner for SQL injection, XSS,
  command injection, and related framework vulnerabilities. The scaffold runs it
  only when a Rails app is detected.
- **packwerk** — Shopify's package-boundary / dependency-rule enforcer
  (the Ruby analogue of ArchUnit). Needs a `package.yml` layout; example in
  `config/packwerk/`.

### TypeScript / JavaScript
- **dependency-cruiser** — *the* JS/TS dependency-rule tool: declarative
  `forbidden`/`allowed` rules, orphan detection, circular-dependency errors,
  graph visualisation. Runs standalone via `npx` → used by the scaffold.
- **madge** — quick circular-dependency detection and dependency graphs.
- **eslint** with `eslint-plugin-import` / `complexity` rule — import layering
  and per-function complexity, if you already run eslint.

## 3. Curated catalogues (to extend coverage)

For any language not above, pick a tool from these and add a wrapper in
`bin/analyse.sh`:
- `analysis-tools-dev/static-analysis` — tagged by language and capability
  (metrics, complexity, dependency).
- `lukehutch/awesome-static-analysis`.

## 4. Mapping to the two sensor types

| Sensor type | Polyglot | JVM | Ruby | TS/JS |
|---|---|---|---|---|
| Complexity / size metric | scc, lizard | detekt, PMD, scalafix | flog, rubycritic | eslint `complexity`, scc |
| Coupling / instability | (via ast-grep import counts) | jdepend, ArchUnit metrics | reek | dependency-cruiser metrics |
| Dependency *rule* (forbidden edge / layering / no-cycle) | ast-grep, semgrep | ArchUnit, Konsist | packwerk | dependency-cruiser, madge |
| Config / security hygiene | ShellCheck, actionlint, hadolint, checkov, betterleaks, OSV-Scanner, Syft | SpotBugs / FindSecBugs | brakeman | eslint security plugins (optional future) |

Treat each row/column cell as an independent sensor a coding agent can poll;
the scaffold's `summary.md` is the aggregated read-out.

## 5. Appendix: glossary

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
| **Distance from main sequence (D)** | — | jdepend's `|A + I − 1|`: how far a package is from the ideal abstractness/instability balance. |
| **churn** | — | How often a file changes in version control; high churn + high complexity = a refactoring priority. |
| **SARIF** | Static Analysis Results Interchange Format | A standard JSON format for analysis findings (e.g. detekt can emit it). |
| **CI** | Continuous Integration | Automated build/test pipeline where these sensors typically run. |
| **dependency rule** | — | A constraint on which modules may depend on which (forbidden edges, layering, no cycles) — the article's second sensor type. |
