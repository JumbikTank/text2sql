"""BIRD Mini-Dev V2 loader.

What it does, in order:

1. Downloads the question file (`mini_dev_postgresql.json`) from
   Hugging Face (`birdsql/bird_mini_dev`).
2. Creates a single Postgres database called `bird_dev` in the local
   `text2sql-test-db` instance and loads BIRD's combined PG dump (75 tables
   from all 11 BIRD logical DBs into one `public` schema — that's how
   BIRD ships it).
3. Registers ONE Text2SQL connection (`bird-dev`) pointing at that DB.
4. Bootstraps the metadata DB and runs a single
   `ScannerService.scan_connection` so embeddings are pre-warmed.

Manual prerequisite: download the BIRD Mini-Dev package
(`minidev_0703.zip`) from
https://drive.google.com/file/d/13VLWIwpw5E3d5DUkMvzw7hvHE67a4XkG/view
and place it at `bench/bird_data/minidev_0703.zip`. The zip contains
`minidev/MINIDEV_postgresql/BIRD_dev.sql` (~1 GB).

Usage::

    uv run python -m bench.bird_loader            # full setup
    uv run python -m bench.bird_loader --skip-restore   # reuse existing DB
    uv run python -m bench.bird_loader --skip-scan      # leave embeddings alone

Note: the BIRD `db_id` field in each question is informational — the
official BIRD evaluator runs every question against the same combined
database. Our pipeline does likewise: vector search picks the relevant
subset of the 75 tables for whatever the user asks.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

# Override so .env beats macOS USERNAME et al. Same trick run_bench uses.
load_dotenv(REPO_ROOT / ".env", override=True)

from huggingface_hub import hf_hub_download  # noqa: E402

from src.common.credentials import CredentialStorage  # noqa: E402
from src.common.dto import DatabaseConnectionConfig  # noqa: E402
from src.common.metadata_db import MetadataDB  # noqa: E402
from src.common.settings import Settings  # noqa: E402
from src.services.embedding_service import EmbeddingService  # noqa: E402
from src.services.scanner_service import ScannerService  # noqa: E402

BIRD_DATA_DIR = REPO_ROOT / "bench" / "bird_data"
BIRD_ZIP = BIRD_DATA_DIR / "minidev_0703.zip"
BIRD_QUESTIONS_JSON = BIRD_DATA_DIR / "mini_dev_postgresql.json"
BIRD_UNZIPPED_DIR = BIRD_DATA_DIR / "minidev"
BIRD_PG_DUMP = BIRD_UNZIPPED_DIR / "MINIDEV_postgresql" / "BIRD_dev.sql"

# We host BIRD DBs in the existing text2sql-test-db container — testuser has
# CREATEDB privileges and the container is already running.
HOST_CONTAINER = "text2sql-test-db"
HOST_USER = "testuser"
HOST_PASSWORD = "testpass"
HOST_PORT = 5433
HOST_BIND_ADDRESS = "localhost"

CONNECTION_ID_PREFIX = "bird-"
BIRD_PG_DATABASE = "bird_dev"
# Legacy single-connection name kept for cleanup of old runs only.
LEGACY_SINGLE_CONNECTION_NAME = f"{CONNECTION_ID_PREFIX}dev"


def bird_connection_name(db_id: str) -> str:
    """Text2SQL connection name for a given BIRD logical DB."""
    return f"{CONNECTION_ID_PREFIX}{db_id}"


BIRD_DEV_TABLES_JSON = BIRD_UNZIPPED_DIR / "MINIDEV" / "dev_tables.json"


def _info(msg: str) -> None:
    print(f"[bird-loader] {msg}")


def _fatal(msg: str) -> None:
    print(f"[bird-loader] FATAL: {msg}", file=sys.stderr)
    sys.exit(1)


def fetch_questions_json() -> Path:
    """Download mini_dev_postgresql.json from HF if absent."""
    if BIRD_QUESTIONS_JSON.exists():
        _info(f"questions already at {BIRD_QUESTIONS_JSON}")
        return BIRD_QUESTIONS_JSON

    BIRD_DATA_DIR.mkdir(parents=True, exist_ok=True)
    _info("downloading mini_dev_postgresql.json from HF…")
    # The HF repo stores the questions as parquet-style splits under data/.
    # The JSON variant is named like data/mini_dev_pg-00000-of-00001.json.
    cached = hf_hub_download(
        repo_id="birdsql/bird_mini_dev",
        repo_type="dataset",
        filename="data/mini_dev_pg-00000-of-00001.json",
    )
    shutil.copyfile(cached, BIRD_QUESTIONS_JSON)
    _info(f"saved {BIRD_QUESTIONS_JSON} ({BIRD_QUESTIONS_JSON.stat().st_size} bytes)")
    return BIRD_QUESTIONS_JSON


def ensure_postgres_dump() -> Path:
    """Make sure the BIRD postgres dump file is unpacked and accessible."""
    if BIRD_PG_DUMP.exists():
        _info(f"pg dump already at {BIRD_PG_DUMP}")
        return BIRD_PG_DUMP

    if not BIRD_ZIP.exists():
        _fatal(
            "BIRD package not downloaded. Manual step:\n"
            f"  1. Open https://drive.google.com/file/d/13VLWIwpw5E3d5DUkMvzw7hvHE67a4XkG/view\n"
            f"  2. Click Download → save as {BIRD_ZIP}\n"
            f"  3. Re-run this loader."
        )

    _info(f"unzipping {BIRD_ZIP}…")
    with zipfile.ZipFile(BIRD_ZIP) as zf:
        zf.extractall(BIRD_DATA_DIR)

    if not BIRD_PG_DUMP.exists():
        # The actual zip layout may have a leading directory we don't know
        # ahead of time. Walk the tree and locate the PG dump (skip MySQL).
        candidates = [
            p for p in BIRD_DATA_DIR.rglob("BIRD_dev.sql")
            if "postgresql" in p.parts[-2].lower()
        ]
        if not candidates:
            _fatal(
                f"could not find postgresql BIRD_dev.sql under {BIRD_DATA_DIR}. "
                f"Inspect the unzipped layout and update BIRD_PG_DUMP."
            )
        return candidates[0]
    return BIRD_PG_DUMP


def _ensure_bird_database() -> bool:
    """Create the `bird_dev` database if it doesn't exist. Returns True
    when newly created (caller should restore the dump), False when it
    already existed."""
    out = subprocess.run(
        [
            "docker", "exec",
            HOST_CONTAINER,
            "psql", "-U", HOST_USER, "-d", "postgres",
            "-At", "-c",
            f"SELECT 1 FROM pg_database WHERE datname = '{BIRD_PG_DATABASE}';",
        ],
        check=True, capture_output=True, text=True,
    )
    if out.stdout.strip() == "1":
        _info(f"database {BIRD_PG_DATABASE!r} already exists")
        return False
    _info(f"creating database {BIRD_PG_DATABASE!r}…")
    subprocess.run(
        [
            "docker", "exec",
            HOST_CONTAINER,
            "createdb", "-U", HOST_USER, BIRD_PG_DATABASE,
        ],
        check=True,
    )
    return True


def restore_postgres_dump(dump_path: Path) -> None:
    """Pipe the BIRD dump through psql into the bird_dev database in
    text2sql-test-db. Idempotent: if `bird_dev` already exists with tables,
    the dump is skipped."""
    newly_created = _ensure_bird_database()

    if not newly_created:
        # Already populated — verify and exit.
        out = subprocess.run(
            [
                "docker", "exec", HOST_CONTAINER,
                "psql", "-U", HOST_USER, "-d", BIRD_PG_DATABASE,
                "-At", "-c",
                "SELECT count(*) FROM information_schema.tables "
                "WHERE table_schema = 'public';",
            ],
            check=True, capture_output=True, text=True,
        )
        existing = int(out.stdout.strip() or "0")
        if existing > 0:
            _info(f"  bird_dev already has {existing} tables — skipping restore")
            return
        _info("  bird_dev exists but is empty — proceeding with restore")

    _info(f"loading dump ({dump_path.stat().st_size / 1e9:.1f} GB) into "
          f"{HOST_CONTAINER}/{BIRD_PG_DATABASE} (~5 min)…")

    with dump_path.open("rb") as f:
        proc = subprocess.run(
            [
                "docker", "exec", "-i",
                HOST_CONTAINER,
                "psql",
                "-U", HOST_USER,
                "-d", BIRD_PG_DATABASE,
                "-v", "ON_ERROR_STOP=0",
                "-q",  # quiet: suppress per-statement output (huge dump)
            ],
            stdin=f,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )

    if proc.returncode != 0:
        tail = (proc.stderr.decode(errors="replace"))[-2000:]
        _fatal(f"psql restore failed (exit {proc.returncode}). stderr tail:\n{tail}")

    out = subprocess.run(
        [
            "docker", "exec", HOST_CONTAINER,
            "psql", "-U", HOST_USER, "-d", BIRD_PG_DATABASE,
            "-At", "-c",
            "SELECT count(*) FROM information_schema.tables "
            "WHERE table_schema = 'public';",
        ],
        check=True, capture_output=True, text=True,
    )
    _info(f"restore complete — {out.stdout.strip()} tables in {BIRD_PG_DATABASE}.public")


def load_dev_tables() -> dict[str, set[str]]:
    """Return `{db_id: {table_name, …}}` from BIRD's dev_tables.json.

    Names are lower-cased because Postgres folds unquoted identifiers to
    lower-case (BIRD's source uses mixed case like 'Player_Attributes').
    """
    if not BIRD_DEV_TABLES_JSON.exists():
        _fatal(f"missing {BIRD_DEV_TABLES_JSON} — re-run unzip step")
    raw = json.loads(BIRD_DEV_TABLES_JSON.read_text())
    return {
        e["db_id"]: {n.lower() for n in e["table_names_original"]}
        for e in raw
    }


def register_connections(
    settings: Settings, db_id_to_tables: dict[str, set[str]]
) -> dict[str, str]:
    """Ensure one Text2SQL connection per BIRD db_id. Returns
    `{db_id: connection_id}`."""
    if not settings.credential_encryption_key:
        _fatal("CREDENTIAL_ENCRYPTION_KEY not set in .env")
        return {}

    storage = CredentialStorage(
        settings.credential_storage_path,
        settings.credential_encryption_key,
    )

    name_to_existing = {c.name: c.id for c in storage.list_connections()}

    db_to_conn: dict[str, str] = {}
    for db_id in db_id_to_tables:
        name = bird_connection_name(db_id)
        if name in name_to_existing:
            db_to_conn[db_id] = name_to_existing[name]
            _info(f"  connection exists: {name} ({db_to_conn[db_id]})")
            continue
        config = DatabaseConnectionConfig(
            name=name,
            host=HOST_BIND_ADDRESS,
            port=HOST_PORT,
            database=BIRD_PG_DATABASE,
            username=HOST_USER,
            password=HOST_PASSWORD,
            ssl_mode="disable",
        )
        saved = storage.save_connection(config)
        db_to_conn[db_id] = saved.id
        _info(f"  registered: {name} ({saved.id})")

    return db_to_conn


def cleanup_legacy_single_connection(settings: Settings) -> None:
    """Drop the old `bird-dev` aggregated connection + its embeddings if
    they linger from earlier runs — they pulled the entire 75-table pool
    and skew vector search."""
    if not settings.credential_encryption_key:
        return
    storage = CredentialStorage(
        settings.credential_storage_path,
        settings.credential_encryption_key,
    )
    for c in storage.list_connections():
        if c.name == LEGACY_SINGLE_CONNECTION_NAME:
            storage.delete_connection(c.id)
            _info(f"deleted legacy aggregated connection {c.name} ({c.id})")
            return


async def scan_connections(
    settings: Settings,
    db_to_conn: dict[str, str],
    db_id_to_tables: dict[str, set[str]],
) -> None:
    """Populate per-db_id embeddings, each scoped to its allowed tables."""
    md = MetadataDB(settings)
    await md.bootstrap()

    es = EmbeddingService(metadata_engine=md.engine)
    # Drop any stale embeddings under the legacy aggregated bird-dev id —
    # they have wrong scope.
    storage = CredentialStorage(
        settings.credential_storage_path,
        settings.credential_encryption_key,
    )
    # Use list_connections() *after* cleanup to know which ids exist.
    legacy_ids = [
        c.id for c in storage.list_connections()
        if c.name == LEGACY_SINGLE_CONNECTION_NAME
    ]
    for cid in legacy_ids:
        await es.remove_connection(cid)

    scanner = ScannerService(settings=settings, embedding_service=es)
    try:
        for db_id, conn_id in db_to_conn.items():
            allowlist = db_id_to_tables[db_id]
            count_before = await es.count_embeddings(conn_id)
            if count_before > 0:
                _info(
                    f"  {db_id}: {count_before} embeddings already present — skipping"
                )
                continue
            _info(f"  scanning {db_id} ({len(allowlist)} tables)…")
            result = await scanner.scan_connection(
                conn_id, table_allowlist=allowlist
            )
            if not result.if_success:
                _info(f"    [warn] scan failed: {result.error_message}")
                continue
            _info(
                f"    +{len(result.tables_added)} tables; total {result.total_tables}"
            )
    finally:
        await scanner.close()
        await md.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="BIRD Mini-Dev loader")
    parser.add_argument(
        "--skip-restore", action="store_true",
        help="Skip pg_dump restore (assume DBs already loaded)",
    )
    parser.add_argument(
        "--skip-scan", action="store_true",
        help="Skip metadata-DB scanning",
    )
    args = parser.parse_args()

    settings = Settings()
    BIRD_DATA_DIR.mkdir(parents=True, exist_ok=True)

    fetch_questions_json()

    if not args.skip_restore:
        dump = ensure_postgres_dump()
        restore_postgres_dump(dump)

    cleanup_legacy_single_connection(settings)

    db_id_to_tables = load_dev_tables()
    db_to_conn = register_connections(settings, db_id_to_tables)

    if not args.skip_scan:
        asyncio.run(scan_connections(settings, db_to_conn, db_id_to_tables))

    _info(f"done. {len(db_to_conn)} BIRD connections ready.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
