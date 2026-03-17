#!/bin/bash
# start.sh
# --------
# Entrypoint for production deployment (Railway, Azure Container Apps).
#
# What this does:
#   1. Runs alembic upgrade head — applies any pending migrations
#   2. Starts uvicorn — the actual API server
#
# Why run migrations here and not in the Dockerfile?
#   Migrations need a live database connection — they can't run at build time
#   because the DB isn't available during docker build. Running them at startup
#   guarantees the DB is ready (Railway/Azure waits for DB health before
#   starting dependent services).
#
# Why not a separate migration job?
#   For a single-instance deployment this is fine. For horizontal scaling
#   (multiple API instances) you'd want a one-off migration job to avoid
#   race conditions. We'll address that in Azure Container Apps deployment.
#
# Idempotent:
#   alembic upgrade head is safe to run multiple times — if already at head
#   it does nothing. No risk of re-running migrations on every restart.

set -e  # exit immediately if any command fails

echo "==> Running database migrations..."
alembic upgrade head
echo "==> Migrations complete."

echo "==> Starting API server..."
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
