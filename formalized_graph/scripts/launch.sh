#!/bin/bash

# Configuration
PORT=5002

echo "==========================================="
echo "   Math-AI Research: Mathlib Graph Explorer"
echo "==========================================="

# 1. Environment check
# Try to find a venv in the current directory or parent
if [ -d "venv" ]; then
    PYTHON="venv/bin/python3"
elif [ -d "../venv" ]; then
    PYTHON="../venv/bin/python3"
else
    PYTHON="python3"
    echo "Warning: venv not found, using system python3"
fi

# 2. Kill any existing server on the port
echo "Cleaning up existing processes on port $PORT..."
lsof -t -i :$PORT | xargs kill -9 2>/dev/null || true

# 3. Launch
echo "Starting explorer at http://localhost:$PORT"
echo "Data Source: Mathlib4 + FLT Formalization Project"
echo "Press Ctrl+C to stop."
echo ""

# Run from the project root to ensure relative paths work correctly
# formalized_graph/data/generated/global_corpus.db is expected by app.py
$PYTHON formalized_graph/explorer/app.py
