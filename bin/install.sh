#!/usr/bin/env bash
# Install the static-analysis sensor toolkit.
# Polyglot tools are required; per-language tools are optional and only used
# when the matching language is present in a target repo.
set -uo pipefail

say() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m  ! %s\033[0m\n' "$*"; }
have() { command -v "$1" >/dev/null 2>&1; }

OS="$(uname -s)"

# --- package-manager helpers -------------------------------------------------
brew_install() { have brew && brew list "$1" >/dev/null 2>&1 || brew install "$1"; }

# --- polyglot backbone (required) -------------------------------------------
say "Polyglot backbone: scc, lizard, ast-grep, semgrep"
if [ "$OS" = "Darwin" ] && have brew; then
  brew_install scc
  brew_install ast-grep
  brew_install semgrep
else
  warn "Non-macOS or no Homebrew: install scc, ast-grep, semgrep manually."
  warn "  scc:       https://github.com/boyter/scc/releases"
  warn "  ast-grep:  pip install ast-grep-cli   (or cargo install ast-grep)"
  warn "  semgrep:   pip install semgrep"
  have ast-grep || pip install ast-grep-cli --break-system-packages -q || true
  have semgrep  || pip install semgrep --break-system-packages -q || true
fi
have lizard || pip install lizard --break-system-packages -q || pipx install lizard

say "PDF report deps: matplotlib, reportlab"
python3 -c 'import matplotlib, reportlab' 2>/dev/null || \
  pip install matplotlib reportlab --break-system-packages -q || \
  warn "Install manually: pip install matplotlib reportlab"

# --- per-language (optional) -------------------------------------------------
say "Kotlin: detekt (CLI)"
if [ "$OS" = "Darwin" ] && have brew; then brew_install detekt; else
  warn "Install detekt-cli: https://detekt.dev/docs/gettingstarted/cli"
fi

say "Java/JVM: pmd (includes cpd)"
if [ "$OS" = "Darwin" ] && have brew; then brew_install pmd; else
  warn "Install PMD: https://pmd.github.io  (brew install pmd / sdkman)"
fi

say "TS/JS: dependency-cruiser, madge"
if have npm; then
  npm install -g dependency-cruiser madge >/dev/null 2>&1 || warn "npm global install failed"
else
  warn "npm not found; skipping dependency-cruiser & madge"
fi

say "Ruby: rubycritic (flog, reek, flay), packwerk"
if have gem; then
  gem install rubycritic packwerk >/dev/null 2>&1 || warn "gem install failed (may need sudo)"
else
  warn "gem not found; skipping Ruby tools"
fi

say "Done. Run: bin/analyse.sh /path/to/repo"
printf '\nInstalled:\n'
for t in scc lizard ast-grep semgrep detekt pmd depcruise madge rubycritic packwerk; do
  if have "$t"; then printf '  \033[1;32m✓\033[0m %s\n' "$t"; else printf '  \033[1;31m✗\033[0m %s\n' "$t"; fi
done
