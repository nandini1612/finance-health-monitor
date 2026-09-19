"""
Shared DB connection helper for the cloud tier.

Reads a single DATABASE_URL env var, e.g.:
    postgresql://cashpulse:password@localhost:5432/cashpulse            (local test Postgres)
    postgresql://cashpulse:password@cashpulse-db.xxxx.us-east-1.rds.amazonaws.com:5432/cashpulse  (AWS RDS)

Same code path for local development and the real cloud database -- this
is the standard "12-factor app" pattern (config via environment, not
hardcoded) and is worth naming as such in an interview.
"""

import os

import sqlalchemy


def get_engine():
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "DATABASE_URL is not set. Copy cloud/.env.example to cloud/.env, fill in your "
            "RDS (or local Postgres) credentials, and `export $(cat cloud/.env | xargs)` "
            "before running anything in cloud/."
        )
    return sqlalchemy.create_engine(url, pool_pre_ping=True)
