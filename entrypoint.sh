#!/bin/sh
set -e

echo "Starting Uvicorn..."
uvicorn main:app --host 0.0.0.0 --port 8000
