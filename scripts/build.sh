#!/bin/sh
set -eu
SCRIPT_DIR=$(CDPATH='' cd -- "$(dirname "$0")" && pwd)
PROJECT_ROOT=$(CDPATH='' cd -- "$SCRIPT_DIR/.." && pwd)
unset PYTHONHOME
PYTHONNOUSERSITE=1
PYTHONPATH=$PROJECT_ROOT/src
export PYTHONNOUSERSITE PYTHONPATH
exec /usr/bin/python3 -P -m coremark_project.cli build "$@"
