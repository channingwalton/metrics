/**
 * dependency-cruiser config — TS/JS dependency rules + cycle detection.
 * Balanced default: the high-value rules from dependency-cruiser's own
 * `--init` recommended set, plus an example layering rule.
 * Run via: bin/analyse.sh  (or: depcruise --config <this> src)
 * Docs: https://github.com/sverweij/dependency-cruiser/blob/main/doc/rules-reference.md
 */
module.exports = {
  forbidden: [
    {
      name: "no-circular",
      severity: "error",
      comment:
        "Circular dependencies make code hard to reason about, test and tree-shake.",
      from: {},
      to: { circular: true },
    },
    {
      name: "no-orphans",
      severity: "warn",
      comment: "Unreachable modules are usually dead code or a missing export.",
      from: {
        orphan: true,
        pathNot: [
          "(^|/)\\.[^/]+\\.(js|cjs|mjs|ts|json)$", // dotfiles, configs
          "\\.d\\.ts$",
          "(^|/)tsconfig\\.json$",
          "(^|/)(babel|webpack)\\.config\\.(js|cjs|mjs|ts)$",
        ],
      },
      to: {},
    },
    {
      name: "no-deprecated-core",
      severity: "warn",
      comment: "Don't depend on deprecated Node core modules.",
      from: {},
      to: { dependencyTypes: ["core"], path: ["^(punycode|domain|sys)$"] },
    },
    {
      name: "not-to-unresolvable",
      severity: "error",
      comment: "A dependency that can't be resolved is a broken import.",
      from: {},
      to: { couldNotResolve: true },
    },
    {
      name: "no-non-package-json",
      severity: "error",
      comment: "Don't import npm packages that aren't declared in package.json.",
      from: {},
      to: { dependencyTypes: ["npm-no-pkg", "npm-unknown"] },
    },
    {
      name: "not-to-dev-dep",
      severity: "error",
      comment: "Production code must not depend on devDependencies.",
      from: { path: "^(src|lib)", pathNot: "\\.(spec|test)\\.(js|ts|tsx)$" },
      to: { dependencyTypes: ["npm-dev"] },
    },
    {
      name: "not-to-test",
      severity: "error",
      comment: "Production code must not import test files.",
      from: { pathNot: "\\.(spec|test)\\.(js|ts|tsx)$" },
      to: { path: "\\.(spec|test)\\.(js|ts|tsx)$" },
    },
    {
      // Example architectural layering rule — adapt the paths to your layout.
      name: "domain-not-to-infra",
      severity: "error",
      comment: "Domain layer must not depend on infrastructure.",
      from: { path: "(^|/)domain/" },
      to: { path: "(^|/)(infra|infrastructure)/" },
    },
  ],
  options: {
    doNotFollow: { path: "node_modules" },
    // Skip generated/vendored output so complexity & cycle reports reflect source.
    exclude: { path: "(^|/)(dist|build|out|coverage|\\.next|\\.turbo)/|\\.min\\.js$" },
    tsPreCompilationDeps: true,
    // Honour tsconfig path aliases if present.
    // tsConfig: { fileName: "tsconfig.json" },
    reporterOptions: {
      dot: { collapsePattern: "node_modules/(@[^/]+/[^/]+|[^/]+)" },
    },
  },
};
