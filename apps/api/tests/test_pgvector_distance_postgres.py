"""Verify real pgvector query semantics against disposable PostgreSQL.

Requires TEST_DATABASE_URL. No application data is written or migrated.
"""
import os

import pytest
from sqlalchemy import create_engine, text


def test_pgvector_distance_orders_candidates_and_preserves_exact_match():
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL is required")
    if not url.startswith(("postgresql://", "postgresql+psycopg://")):
        pytest.fail("TEST_DATABASE_URL must point to disposable PostgreSQL")

    engine = create_engine(url, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            installed = connection.scalar(text(
                "SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector')"
            ))
            assert installed, "pgvector extension is not installed"
            # Use a VALUES relation to exercise real nearest-neighbor ordering
            # without creating tables or relying on a seeded application database.
            rows = connection.execute(text("""
                SELECT candidate, embedding <-> CAST(:query AS vector(3)) AS distance
                FROM (VALUES
                    ('exact', '[1,0,0]'::vector(3)),
                    ('near', '[0.8,0.6,0]'::vector(3)),
                    ('far', '[0,1,0]'::vector(3))
                ) AS candidates(candidate, embedding)
                ORDER BY distance, candidate
            """), {"query": "[1,0,0]"}).all()
            assert [row.candidate for row in rows] == ["exact", "near", "far"]
            assert abs(rows[0].distance) < 1e-10
            assert abs(rows[1].distance - (0.4 ** 0.5)) < 1e-6
            assert abs(rows[2].distance - (2 ** 0.5)) < 1e-6
    finally:
        engine.dispose()
