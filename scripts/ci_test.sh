#!/usr/bin/env sh
set -e
pip install -e ".[dev]"
pytest -q
