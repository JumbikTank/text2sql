"""Generate embeddings for table metadata using sentence-transformers."""

import asyncio
import os

import asyncpg
from pgvector.asyncpg import register_vector
from sentence_transformers import SentenceTransformer

# Load the embedding model
print("Loading embedding model...")
model = SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')
print("Model loaded successfully!")

async def generate_embeddings():
    """Generate and update embeddings for all metadata records."""
    # Connect to PostgreSQL
    conn = await asyncpg.connect(
        host=os.environ.get('PGHOST', 'localhost'),
        port=int(os.environ.get('PGPORT', '5432')),
        user=os.environ.get('PGUSER', 'postgres'),
        password=os.environ.get('PGPASSWORD', ''),
        database=os.environ.get('PGDATABASE', 'ecommerce'),
    )

    # Register pgvector type
    await register_vector(conn)

    try:
        # Fetch all metadata records
        records = await conn.fetch("""
            SELECT id, table_name, table_comments, full_description, description
            FROM notes
        """)

        print(f"Found {len(records)} metadata records")

        # Generate embeddings for each record
        for record in records:
            # Combine all text fields for embedding
            text = f"{record['table_name']} {record['table_comments']} {record['full_description']} {record['description']}"

            print(f"Generating embedding for table: {record['table_name']}")

            # Generate embedding
            embedding = model.encode(text)

            # Update the database - pass numpy array directly after register_vector
            await conn.execute("""
                UPDATE notes
                SET embedding = $1
                WHERE id = $2
            """, embedding, record['id'])

            print(f"✓ Updated embedding for {record['table_name']}")

        print("\n✅ All embeddings generated successfully!")

    finally:
        await conn.close()

if __name__ == "__main__":
    asyncio.run(generate_embeddings())
