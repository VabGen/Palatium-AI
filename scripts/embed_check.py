#!/usr/bin/env python
"""Manual embedding connectivity check (not part of pytest suite)."""

from __future__ import annotations

import asyncio

from palatium_ai.core.config import get_settings
from palatium_ai.infrastructure.embeddings import create_embedding_client


async def main() -> None:
    client = create_embedding_client(get_settings())
    vectors = await client.embed(["hello embedding test"])
    print("vectors:", len(vectors))
    if not vectors:
        print("ERROR: empty embedding response")
        return
    print("dimension:", len(vectors[0]))


if __name__ == "__main__":
    asyncio.run(main())
