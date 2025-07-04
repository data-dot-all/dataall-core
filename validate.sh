#!/usr/bin/env bash
set -ex

ruff format --check .
ruff check .
mypy --install-types --non-interactive dataall_core
pylint dataall_core
poetry check --lock
