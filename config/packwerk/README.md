# packwerk — Ruby package-boundary / dependency rules

packwerk enforces dependency rules between Ruby "packages" (directories with a
`package.yml`). It needs the package layout in your app, so it ships here as an
example rather than being run standalone by `analyse.sh`.

Docs: https://github.com/Shopify/packwerk

## Setup

```bash
gem install packwerk          # (already installed by bin/install.sh)
bin/packwerk init             # generates packwerk.yml + an root package.yml
```

## Root `packwerk.yml`

```yaml
include:
  - "**/*.{rb,rake,erb}"
exclude:
  - "{bin,node_modules,script,tmp,vendor}/**/*"
```

## A package with dependency rules — `app/domain/package.yml`

```yaml
enforce_dependencies: true   # this package may only depend on its declared deps
enforce_privacy: true        # other packages may only use this package's public API
dependencies:
  - "."                      # e.g. domain depends only on the root, NOT on infra
```

`app/infrastructure/package.yml` would list `app/domain` as a dependency,
encoding the same "infra may depend on domain, not vice-versa" rule as the
ArchUnit/Konsist examples.

## Check

```bash
bin/packwerk check
```

Returns non-zero on any boundary violation — wire it into CI as a sensor.
