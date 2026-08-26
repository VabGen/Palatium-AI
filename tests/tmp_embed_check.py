import asyncio

from palatium_ai.core.config import get_settings
from palatium_ai.infrastructure.embeddings import create_embedding_client


async def main():
    """Проверка работы embedding."""
    client = create_embedding_client(get_settings())
    vectors = await client.embed(["hello embedding test"])
    print("vectors:", len(vectors))
    if not vectors:
        print("ERROR: empty embedding response")
        return
    print("dimension:", len(vectors[0]))


asyncio.run(main())


# poetry run python -m tests.tmp_embed_check
