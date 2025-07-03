#!/usr/bin/env bash
set -ex

ruff format --check .
ruff check .
mypy --install-types --non-interactive dataall_core
pylint -j 0 --disable=all --enable=R0911,R0912,R0913,R0915 --fail-under=9 dataall_core
poetry check --lock
