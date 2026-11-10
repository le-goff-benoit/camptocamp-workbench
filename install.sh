#!/usr/bin/env bash
set -euo pipefail

cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
mode="${1:---check}"
case "$mode" in
  --check) python3 scripts/check_requirements.py ;;
  --install)
    python3 scripts/check_requirements.py
    python3 scripts/manage.py install
    python3 scripts/manage.py start
    printf '%s\n' 'Installation terminée. Lancez : python3 scripts/manage.py open'
    ;;
  *) printf '%s\n' 'Usage : bash install.sh [--check|--install]' >&2; exit 2 ;;
esac
