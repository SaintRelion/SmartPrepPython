#!/bin/sh
set -e

echo "Running migrations..."
python manage.py migrate --noinput

echo "Starting Uvicorn..."
uvicorn main:app --host 0.0.0.0 --port 8000 &
