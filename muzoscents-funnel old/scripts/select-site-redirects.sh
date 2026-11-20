#!/usr/bin/env bash
set -euo pipefail
MODE="${1:-backroom}"
DIR="muzoscents-funnel old"
if [ "$MODE" = "storefront" ]; then
  cp "$DIR/_redirects.storefront" "$DIR/_redirects"
  echo "Activated storefront-only _redirects"
else
  git checkout -- "$DIR/_redirects"
  echo "Restored backroom _redirects"
fi
