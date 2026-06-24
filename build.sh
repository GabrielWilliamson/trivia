#!/bin/bash
set -e

echo "===================="
echo "STARTING BUILD PROCESS"
echo "===================="

echo "Step 1: Installing Python dependencies"
uv sync

# echo "Step 2: Installing Node.js dependencies"
# npm install

# echo "Step 3: Building static files (npm run build)"
# npm run build

echo "Step 4: Collecting static files"
uv run manage.py collectstatic --noinput --clear

echo "Step 5: Applying database migrations"
uv run manage.py migrate

echo "===================="
echo "✅ BUILD PROCESS COMPLETED SUCCESSFULLY"
echo "===================="
