"""Concurrent content-addressed ingestion must preserve one durable identity.

Requires a disposable PostgreSQL database, configured via TEST_DATABASE_URL.
"""
import hashlib
import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.persistence import Base, DocumentRepository, DocumentRow


def test_parallel_duplicate_documents_share_identity():
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL is required")
    if not url.startswith(("postgresql://", "postgresql+psycopg://")):
        pytest.fail("TEST_DATABASE_URL must be a disposable PostgreSQL database")
    engine = create_engine(url, pool_pre_ping=True)
    try:
        Base.metadata.create_all(engine)
        factory = sessionmaker(bind=engine, expire_on_commit=False)
        payload = ("parallel-ingestion-" + str(uuid4())).encode()
        digest = hashlib.sha256(payload).hexdigest()
        barrier = Barrier(2)

        def ingest(index):
            document = SimpleNamespace(
                id=uuid4(), filename=f"source-{index}.txt",
                media_type="text/plain", sha256=digest, text=payload.decode()
            )
            barrier.wait(timeout=10)
            with factory.begin() as session:
                return DocumentRepository(session).add(document).id

        with ThreadPoolExecutor(max_workers=2) as pool:
            identities = list(pool.map(ingest, range(2)))
        assert identities[0] == identities[1]
        with factory.begin() as session:
            count = session.scalar(
                select(func.count()).select_from(DocumentRow).where(DocumentRow.sha256 == digest)
            )
            assert count == 1
    finally:
        engine.dispose()
