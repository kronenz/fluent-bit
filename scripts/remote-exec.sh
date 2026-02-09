#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ ! -f "${SCRIPT_DIR}/.env" ]; then
  echo "ERROR: ${SCRIPT_DIR}/.env 파일이 없습니다. .env.example을 복사하여 .env를 생성하세요."
  exit 1
fi

source "${SCRIPT_DIR}/.env"
export SSH_HOST SSH_USER SSH_PASSWORD

"${SCRIPT_DIR}/ssh-helper.py" "$@"
