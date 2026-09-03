#!/usr/bin/env bash

set -euo pipefail

PLUGIN_DIR="$(cd "${1:?plugin directory is required}" && pwd)"
shift
PLUGIN_ID="$(basename "${PLUGIN_DIR}")"

usage() {
  cat >&2 <<EOF
Usage: bash init.sh [project] [opencode|codex|claude|trae|dsh] [install_path]

Installs ${PLUGIN_ID} from this source checkout. The default tool is opencode
and the default install path is the source repository root.
EOF
}

LEVEL="project"
TOOL="opencode"
INSTALL_PATH=""
for argument in "$@"; do
  case "${argument}" in
    --help|-h) usage; exit 0 ;;
    project) LEVEL="project" ;;
    global) LEVEL="global" ;;
    opencode|codex|claude|trae|dsh) TOOL="${argument}" ;;
    cursor|copilot|codearts)
      echo "cannbot: ${argument} is not supported by the unified installer" >&2
      exit 1
      ;;
    *)
      if [[ -n "${INSTALL_PATH}" ]]; then usage; exit 1; fi
      INSTALL_PATH="${argument}"
      ;;
  esac
done

if [[ "${LEVEL}" != "project" ]]; then
  echo "cannbot: the unified installer currently supports project-level installation only" >&2
  exit 1
fi

if [[ -f "${PLUGIN_DIR}/../../script/bin/cannbot.js" ]]; then
  REPOSITORY_ROOT="$(cd "${PLUGIN_DIR}/../.." && pwd)"
  CLI="${REPOSITORY_ROOT}/script/bin/cannbot.js"
elif [[ -f "${PLUGIN_DIR}/../../../bin/cannbot.js" ]]; then
  REPOSITORY_ROOT="$(cd "${PLUGIN_DIR}/../../.." && pwd)"
  CLI="${REPOSITORY_ROOT}/bin/cannbot.js"
else
  echo "cannbot: cannot locate the unified installer from ${PLUGIN_DIR}" >&2
  exit 1
fi
INSTALL_PATH="${INSTALL_PATH:-${REPOSITORY_ROOT}}"

exec node "${CLI}" install "${PLUGIN_ID}" \
  --tool "${TOOL}" --target "${INSTALL_PATH}" --source "${REPOSITORY_ROOT}"
