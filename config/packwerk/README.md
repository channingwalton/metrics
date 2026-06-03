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

## Ready-made examples

This directory ships concrete configs you can copy in:

- `packwerk.yml` → app root
- `example/domain/package.yml` → `app/domain/package.yml` (depends on nothing)
- `example/infrastructure/package.yml` → `app/infrastructure/package.yml`
  (depends on `app/domain`)

Together they encode the same "infra may depend on domain, not vice-versa" rule
as the ArchUnit and Konsist examples. `enforce_privacy: true` additionally
restricts other packages to each package's public API (`app/<pkg>/public/**`).

## Check

```bash
bin/packwerk check
```

Returns non-zero on any boundary violation — wire it into CI as a sensor.
