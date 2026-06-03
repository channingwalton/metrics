/**
 * dependency-cruiser config — TS/JS dependency rules + cycle detection.
 * Run via: bin/analyse.sh  (or: depcruise --config <this> src)
 * Docs: https://github.com/sverweij/dependency-cruiser
 */
module.exports = {
  forbidden: [
    {
      name: "no-circular",
      severity: "error",
      comment: "Circular dependencies make code hard to reason about and test.",
      from: {},
      to: { circular: true },
    },
    {
      name: "domain-not-to-infra",
      severity: "error",
      comment: "Domain layer must not depend on infrastructure.",
      from: { path: "(^|/)domain/" },
      to: { path: "(^|/)(infra|infrastructure)/" },
    },
    {
      name: "no-orphans",
      severity: "warn",
      comment: "Unreachable modules are usually dead code.",
      from: { orphan: true, pathNot: "\\.(d\\.ts|test\\.ts|spec\\.ts)$" },
      to: {},
    },
  ],
  options: {
    doNotFollow: { path: "node_modules" },
    tsPreCompilationDeps: true,
  },
};
