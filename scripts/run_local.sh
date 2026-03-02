#!/usr/bin/env bash
set -euo pipefail

if [[ -f .env ]]; then
  export $(grep -v '^#' .env | xargs)
fi

python -m neuqa_pr_agent.main --pr "${1:?PR number required}" "${@:2}"
