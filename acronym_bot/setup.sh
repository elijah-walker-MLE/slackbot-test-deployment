#!/usr/bin/env bash
set -e

python3 -m venv .venv

source .venv/bin/activate

pip install --upgrade pip

pip install -r requirements.txt

echo "Environment setup complete. Activate it with:"
echo "source .venv/bin/activate"