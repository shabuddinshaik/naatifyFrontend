import os
import sqlite3
import asyncio
import json
import urllib.error
import urllib.request
from pypdf import PdfReader
from PIL import Image, UnidentifiedImageError
import uuid
from io import BytesIO
from datetime import datetime, timezone
from contextlib import asynccontextmanager
from pathlib import Path

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError
from fastapi import (
    FastAPI, HTTPException, Request, Response, Depends,
    UploadFile, File, Form,
)
from fastapi.responses import JSONResponse, FileResponse
from fastapi.security import HTTPBearer
from pydantic import BaseModel, Field
from app.transliteration import transliterate_urdu

DB_PATH = Path(os.getenv("DB_PATH", "/data/naatify.db"))
UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", "/var/lib/naatify/uploads"))
COVER_DIR = UPLOAD_DIR / "covers"
MAX_PDF_BYTES = 50 * 1024 * 1024
MAX_COVER_BYTES = 5 * 1024 * 1024
USERNAME = os.environ["ADMIN_USERNAME"]
ADMIN_PASSWORD = os.environ["ADMIN_PASSWORD"]
SECRET_KEY = os.environ["SECRET_KEY"]
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "false").lower() == "true"
TOKEN_TTL_SECONDS = 30 * 60

hasher = PasswordHasher()
bearer = HTTPBearer(auto_error=False)


def connect_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def initialize_db():
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    COVER_DIR.mkdir(parents=True, exist_ok=True)
    with connect_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS admins (
                username TEXT PRIMARY KEY,
                password_hash TEXT NOT NULL
            )
        """)
        existing = conn.execute(
            "SELECT username FROM admins WHERE username = ?", (USERNAME,)
        ).fetchone()

        if existing is None:
            conn.execute(
                "INSERT INTO admins (username, password_hash) VALUES (?, ?)",
                (USERNAME, hasher.hash(ADMIN_PASSWORD)),
            )

        conn.execute("""
            CREATE TABLE IF NOT EXISTS books (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                author TEXT NOT NULL DEFAULT '',
                original_filename TEXT NOT NULL,
                stored_filename TEXT NOT NULL UNIQUE,
                file_size INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'uploaded',
                uploaded_by TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS book_pages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                book_id TEXT NOT NULL,
                page_number INTEGER NOT NULL,
                extracted_text TEXT NOT NULL DEFAULT '',
                ocr_text TEXT NOT NULL DEFAULT '',
                page_type TEXT NOT NULL DEFAULT 'unknown',
                processing_status TEXT NOT NULL DEFAULT 'pending',
                review_status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (book_id, page_number),
                FOREIGN KEY (book_id) REFERENCES books(id) ON DELETE CASCADE
            )
        """)


        conn.execute("""
            CREATE TABLE IF NOT EXISTS page_transliterations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                book_id TEXT NOT NULL,
                page_number INTEGER NOT NULL,
                source_urdu TEXT NOT NULL DEFAULT '',
                roman_urdu TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'draft'
                    CHECK(status IN ('draft', 'reviewed', 'approved')),
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(book_id, page_number),
                FOREIGN KEY(book_id) REFERENCES books(id) ON DELETE CASCADE
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS naats (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                poet TEXT NOT NULL DEFAULT '',
                source_language TEXT NOT NULL DEFAULT 'Urdu',
                original_text TEXT NOT NULL DEFAULT '',
                source_format TEXT NOT NULL DEFAULT 'urdu_script',
                status TEXT NOT NULL DEFAULT 'draft'
                    CHECK(status IN ('draft', 'reviewed', 'approved', 'published')),
                created_by TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)

        # Source texts: one Naat can have multiple language/script forms.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS naat_sources (
                id TEXT PRIMARY KEY,
                naat_id TEXT NOT NULL,
                language TEXT NOT NULL,
                script_code TEXT NOT NULL,
                source_format TEXT NOT NULL,
                text TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'draft'
                    CHECK(status IN ('draft', 'reviewed', 'approved', 'published')),
                created_by TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(naat_id, language, script_code),
                FOREIGN KEY(naat_id) REFERENCES naats(id) ON DELETE CASCADE
            )
        """)

        # Backfill legacy original_text without overwriting existing sources.
        legacy_naats = conn.execute("SELECT * FROM naats").fetchall()

        for naat in legacy_naats:
            source_text = (naat["original_text"] or "").strip()
            if not source_text:
                continue

            source_format = naat["source_format"] or "urdu_script"
            script_code = {
                "urdu_script": "ur-Arab",
                "roman_urdu": "ur-Latn",
                "other": "und",
            }.get(source_format, "und")

            conn.execute("""
                INSERT OR IGNORE INTO naat_sources (
                    id, naat_id, language, script_code,
                    source_format, text, status, created_by,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, 'draft', ?, ?, ?)
            """, (
                str(uuid.uuid4()),
                naat["id"],
                naat["source_language"] or "Urdu",
                script_code,
                source_format,
                source_text,
                naat["created_by"],
                naat["created_at"],
                naat["updated_at"],
            ))

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_naat_sources_naat_id
            ON naat_sources(naat_id)
        """)

        # Safe, additive migration for book metadata.
        # Existing naats and versions are preserved.
        naat_columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(naats)").fetchall()
        }
        if "book_name" not in naat_columns:
            conn.execute(
                "ALTER TABLE naats ADD COLUMN book_name TEXT NOT NULL DEFAULT ''"
            )
        if "page_number" not in naat_columns:
            conn.execute(
                "ALTER TABLE naats ADD COLUMN page_number INTEGER"
            )

        # Naat poetry collections (separate from PDF books).
        conn.execute("""
            CREATE TABLE IF NOT EXISTS naat_collections (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                author TEXT NOT NULL DEFAULT '',
                description TEXT NOT NULL DEFAULT '',
                cover_image TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)

        # Optional collection relationship; preserve legacy book_name.
        naat_columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(naats)").fetchall()
        }

        if "collection_id" not in naat_columns:
            conn.execute("""
                ALTER TABLE naats
                ADD COLUMN collection_id TEXT
                REFERENCES naat_collections(id) ON DELETE SET NULL
            """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_naats_collection_id
            ON naats(collection_id)
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS naat_versions (
                id TEXT PRIMARY KEY,
                naat_id TEXT NOT NULL,
                language TEXT NOT NULL,
                format TEXT NOT NULL CHECK(format IN ('transliteration', 'translation')),
                text TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'draft'
                    CHECK(status IN ('draft', 'reviewed', 'approved', 'published')),
                updated_by TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(naat_id, language, format),
                FOREIGN KEY(naat_id) REFERENCES naats(id) ON DELETE CASCADE
            )
        """)

        # Additive migrations for version script and source tracking.
        version_columns = {
            row["name"]
            for row in conn.execute(
                "PRAGMA table_info(naat_versions)"
            ).fetchall()
        }

        if "script_code" not in version_columns:
            conn.execute("""
                ALTER TABLE naat_versions
                ADD COLUMN script_code TEXT NOT NULL DEFAULT ''
            """)

        if "source_id" not in version_columns:
            conn.execute("""
                ALTER TABLE naat_versions
                ADD COLUMN source_id TEXT
                REFERENCES naat_sources(id) ON DELETE SET NULL
            """)

        # Admin-triggered conversion job tracking.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS conversion_jobs (
                id TEXT PRIMARY KEY,
                naat_id TEXT NOT NULL,
                source_version_id TEXT,
                target_language TEXT NOT NULL,
                target_script_code TEXT NOT NULL,
                conversion_type TEXT NOT NULL
                    CHECK(conversion_type IN ('transliteration', 'translation')),
                status TEXT NOT NULL DEFAULT 'pending'
                    CHECK(status IN (
                        'pending',
                        'processing',
                        'completed',
                        'failed',
                        'cancelled'
                    )),
                generated_text TEXT NOT NULL DEFAULT '',
                error_message TEXT NOT NULL DEFAULT '',
                requested_by TEXT NOT NULL,
                created_at TEXT NOT NULL,
                completed_at TEXT,
                source_id TEXT REFERENCES naat_sources(id) ON DELETE SET NULL,
                FOREIGN KEY(naat_id) REFERENCES naats(id) ON DELETE CASCADE
            )
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_conversion_jobs_naat_id
            ON conversion_jobs(naat_id)
        """)

        # Recover unfinished Kannada jobs after a backend restart.
        conn.execute("""
            UPDATE conversion_jobs
            SET status = 'pending', error_message = ''
            WHERE status = 'processing'
              AND target_language = 'Kannada'
              AND conversion_type = 'transliteration'
        """)

        # Preserve the exact input text used when a conversion job is queued.
        job_columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(conversion_jobs)").fetchall()
        }
        if "source_text" not in job_columns:
            conn.execute("""
                ALTER TABLE conversion_jobs
                ADD COLUMN source_text TEXT NOT NULL DEFAULT ''
            """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS naat_revisions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                naat_id TEXT NOT NULL,
                version_id TEXT,
                content TEXT NOT NULL,
                editor TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(naat_id) REFERENCES naats(id) ON DELETE CASCADE
            )
        """)

        # Add source-level revision tracking without changing existing revisions.
        revision_columns = {
            row["name"]
            for row in conn.execute(
                "PRAGMA table_info(naat_revisions)"
            ).fetchall()
        }

        if "source_id" not in revision_columns:
            conn.execute("""
                ALTER TABLE naat_revisions
                ADD COLUMN source_id TEXT
                REFERENCES naat_sources(id) ON DELETE SET NULL
            """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_naat_revisions_source_id
            ON naat_revisions(source_id)
        """)



def call_kannada_service(source_text: str) -> str:
    service_url = os.getenv(
        "KANNADA_SERVICE_URL",
        "http://172.18.0.1:8001/transliterate",
    )
    payload = json.dumps({"text": source_text}).encode("utf-8")
    request = urllib.request.Request(
        service_url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Kannada service returned HTTP {exc.code}") from exc
    except Exception as exc:
        raise RuntimeError("Kannada transliteration service is unavailable") from exc

    generated = result.get("kannada_text", "")
    if not isinstance(generated, str) or not generated.strip():
        raise RuntimeError("Kannada service returned empty text.")
    return generated


def claim_kannada_job():
    with connect_db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            """SELECT * FROM conversion_jobs
               WHERE status = 'pending'
                 AND target_language = 'Kannada'
                 AND conversion_type = 'transliteration'
               ORDER BY created_at, id
               LIMIT 1"""
        ).fetchone()
        if row is None:
            conn.commit()
            return None

        changed = conn.execute(
            """UPDATE conversion_jobs
               SET status = 'processing'
               WHERE id = ? AND status = 'pending'""",
            (row["id"],),
        ).rowcount
        conn.commit()
        return dict(row) if changed == 1 else None


def process_kannada_job(job):
    try:
        generated = call_kannada_service(job["source_text"])
        now = datetime.now(timezone.utc).isoformat()

        with connect_db() as conn:
            current_job = conn.execute(
                "SELECT status FROM conversion_jobs WHERE id = ?",
                (job["id"],),
            ).fetchone()

            if not current_job or current_job["status"] != "processing":
                return

            existing = conn.execute(
                """SELECT * FROM naat_versions
                   WHERE naat_id = ? AND language = 'Kannada'
                     AND format = 'transliteration'""",
                (job["naat_id"],),
            ).fetchone()

            if existing and existing["status"] == "published":
                raise RuntimeError(
                    "Published Kannada version cannot be overwritten."
                )

            source_id = job["source_id"]

            if existing:
                source_id = source_id or existing["source_id"]

                conn.execute(
                    """INSERT INTO naat_revisions
                       (naat_id, version_id, content, editor, created_at)
                       VALUES (?, ?, ?, ?, ?)""",
                    (
                        job["naat_id"], existing["id"], existing["text"],
                        job["requested_by"], now,
                    ),
                )

                conn.execute(
                    """UPDATE naat_versions
                       SET text = ?, status = 'draft', updated_by = ?,
                           updated_at = ?, script_code = 'kn-Knda',
                           source_id = ?
                       WHERE id = ?""",
                    (
                        generated, job["requested_by"], now,
                        source_id, existing["id"],
                    ),
                )
            else:
                conn.execute(
                    """INSERT INTO naat_versions
                       (id, naat_id, language, format, text, status,
                        updated_by, created_at, updated_at, script_code, source_id)
                       VALUES (?, ?, 'Kannada', 'transliteration', ?, 'draft',
                               ?, ?, ?, 'kn-Knda', ?)""",
                    (
                        str(uuid.uuid4()), job["naat_id"], generated,
                        job["requested_by"], now, now, source_id,
                    ),
                )

            conn.execute(
                """UPDATE naats
                   SET status = CASE
                       WHEN EXISTS (
                           SELECT 1 FROM naat_versions
                           WHERE naat_id = ? AND status = 'published'
                       ) THEN 'published'
                       ELSE 'draft'
                   END,
                   updated_at = ?
                   WHERE id = ?""",
                (job["naat_id"], now, job["naat_id"]),
            )

            conn.execute(
                """UPDATE conversion_jobs
                   SET status = 'completed', generated_text = ?,
                       error_message = '', completed_at = ?
                   WHERE id = ? AND status = 'processing'""",
                (generated, now, job["id"]),
            )

    except Exception as exc:
        now = datetime.now(timezone.utc).isoformat()
        with connect_db() as conn:
            conn.execute(
                """UPDATE conversion_jobs
                   SET status = 'failed', error_message = ?, completed_at = ?
                   WHERE id = ? AND status = 'processing'""",
                (str(exc)[:2000], now, job["id"]),
            )


async def kannada_conversion_worker():
    while True:
        job = await asyncio.to_thread(claim_kannada_job)
        if job is None:
            await asyncio.sleep(2)
            continue
        await asyncio.to_thread(process_kannada_job, job)


@asynccontextmanager
async def lifespan(app: FastAPI):
    initialize_db()
    worker_task = asyncio.create_task(kannada_conversion_worker())
    app.state.kannada_worker_task = worker_task
    try:
        yield
    finally:
        worker_task.cancel()
        try:
            await worker_task
        except asyncio.CancelledError:
            pass


app = FastAPI(
    title="Naatify API",
    description="Backend API for the Naatify Islamic poetry platform",
    version="0.2.0",
    lifespan=lifespan,
)




class TransliterationRequest(BaseModel):
    text: str = Field(max_length=20000)


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=256)


def current_admin(request: Request):
    token = request.cookies.get("naatify_session")
    if not token:
        raise HTTPException(status_code=401, detail="Authentication required")

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        username = payload.get("sub")
        if not username:
            raise HTTPException(status_code=401, detail="Invalid session")
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired session")

    with connect_db() as conn:
        admin = conn.execute(
            "SELECT username FROM admins WHERE username = ?", (username,)
        ).fetchone()

    if not admin:
        raise HTTPException(status_code=401, detail="Admin account not found")

    return {"username": admin["username"]}


@app.get("/health")
def health():
    return {"status": "healthy", "service": "naatify-api"}


@app.get("/api/v1")
def api_info():
    return {"name": "Naatify API", "version": "0.2.0"}


class NaatCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    poet: str = Field(min_length=1, max_length=200)
    book_name: str = Field(min_length=1, max_length=200)
    page_number: int | None = Field(default=None, ge=1)
    source_language: str = Field(default="Urdu", min_length=1, max_length=50)
    original_text: str = Field(default="", max_length=100000)
    source_format: str = Field(default="urdu_script", pattern="^(urdu_script|roman_urdu|other)$")


class NaatUpdateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    poet: str = Field(min_length=1, max_length=200)
    book_name: str = Field(min_length=1, max_length=200)
    page_number: int | None = Field(default=None, ge=1)
    source_language: str = Field(default="Urdu", min_length=1, max_length=50)
    original_text: str = Field(default="", max_length=100000)
    source_format: str = Field(default="urdu_script", pattern="^(urdu_script|roman_urdu|other)$")


class CollectionRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    author: str = Field(default="", max_length=200)
    description: str = Field(default="", max_length=2000)


class CollectionAssignmentRequest(BaseModel):
    collection_id: str | None = None


class NaatVersionRequest(BaseModel):
    language: str = Field(min_length=1, max_length=50)
    format: str = Field(pattern="^(transliteration|translation)$")
    text: str = Field(default="", max_length=100000)
    status: str = Field(default="draft", pattern="^(draft|reviewed|approved)$")
    script_code: str = Field(default="", max_length=35)
    source_id: str | None = None


class NaatSourceRequest(BaseModel):
    language: str = Field(default="Urdu", min_length=1, max_length=50)
    script_code: str = Field(min_length=2, max_length=35)
    source_format: str = Field(
        default="urdu_script",
        pattern="^(urdu_script|roman_urdu|other)$"
    )
    text: str = Field(default="", max_length=100000)
    status: str = Field(default="draft", pattern="^(draft|reviewed|approved)$")


def naat_row(row):
    return dict(row) if row else None


@app.post("/api/v1/collections", status_code=201)
def create_collection(data: CollectionRequest, admin=Depends(current_admin)):
    title = data.title.strip()
    if not title:
        raise HTTPException(status_code=422, detail="Collection title is required.")

    now = datetime.now(timezone.utc).isoformat()
    collection_id = str(uuid.uuid4())

    with connect_db() as conn:
        conn.execute(
            """
            INSERT INTO naat_collections
                (id, title, author, description, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                collection_id,
                title,
                data.author.strip(),
                data.description.strip(),
                now,
                now,
            ),
        )
        row = conn.execute(
            "SELECT * FROM naat_collections WHERE id = ?",
            (collection_id,),
        ).fetchone()

    return dict(row)


@app.get("/api/v1/collections")
def list_collections(admin=Depends(current_admin)):
    with connect_db() as conn:
        rows = conn.execute(
            """
            SELECT c.*,
                   (SELECT COUNT(*) FROM naats n
                    WHERE n.collection_id = c.id) AS naat_count
            FROM naat_collections c
            ORDER BY c.updated_at DESC, c.title COLLATE NOCASE
            """
        ).fetchall()

    return {"collections": [dict(row) for row in rows]}


@app.put("/api/v1/collections/{collection_id}")
def update_collection(
    collection_id: str,
    data: CollectionRequest,
    admin=Depends(current_admin),
):
    title = data.title.strip()
    if not title:
        raise HTTPException(status_code=422, detail="Collection title is required.")

    now = datetime.now(timezone.utc).isoformat()

    with connect_db() as conn:
        existing = conn.execute(
            "SELECT id FROM naat_collections WHERE id = ?",
            (collection_id,),
        ).fetchone()

        if not existing:
            raise HTTPException(status_code=404, detail="Collection not found.")

        conn.execute(
            """
            UPDATE naat_collections
            SET title = ?, author = ?, description = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                title,
                data.author.strip(),
                data.description.strip(),
                now,
                collection_id,
            ),
        )

        row = conn.execute(
            "SELECT * FROM naat_collections WHERE id = ?",
            (collection_id,),
        ).fetchone()

    return dict(row)


@app.post("/api/v1/collections/{collection_id}/cover")
async def upload_collection_cover(
    collection_id: str,
    file: UploadFile = File(...),
    admin=Depends(current_admin),
):
    with connect_db() as conn:
        collection = conn.execute(
            "SELECT id, cover_image FROM naat_collections WHERE id = ?",
            (collection_id,),
        ).fetchone()

    if not collection:
        raise HTTPException(status_code=404, detail="Collection not found.")

    content = await file.read(MAX_COVER_BYTES + 1)
    await file.close()

    if not content:
        raise HTTPException(status_code=400, detail="Empty image upload.")

    if len(content) > MAX_COVER_BYTES:
        raise HTTPException(status_code=413, detail="Cover image must be 5 MB or smaller.")

    allowed_formats = {
        "JPEG": ("jpg", "image/jpeg"),
        "PNG": ("png", "image/png"),
        "WEBP": ("webp", "image/webp"),
    }

    try:
        with Image.open(BytesIO(content)) as image:
            image_format = image.format
            width, height = image.size

            if image_format not in allowed_formats:
                raise HTTPException(
                    status_code=415,
                    detail="Only JPEG, PNG, and WebP images are supported.",
                )

            if width < 1 or height < 1 or width > 10000 or height > 10000:
                raise HTTPException(
                    status_code=422,
                    detail="Image dimensions are invalid or too large.",
                )

            if width * height > 40_000_000:
                raise HTTPException(
                    status_code=422,
                    detail="Image resolution is too large.",
                )

            image.verify()

    except HTTPException:
        raise
    except (UnidentifiedImageError, OSError, ValueError):
        raise HTTPException(status_code=415, detail="Uploaded file is not a valid image.")

    extension, media_type = allowed_formats[image_format]
    filename = f"{uuid.uuid4()}.{extension}"
    destination = COVER_DIR / filename

    COVER_DIR.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(content)

    now = datetime.now(timezone.utc).isoformat()

    try:
        with connect_db() as conn:
            conn.execute(
                """
                UPDATE naat_collections
                SET cover_image = ?, updated_at = ?
                WHERE id = ?
                """,
                (filename, now, collection_id),
            )
    except Exception:
        destination.unlink(missing_ok=True)
        raise

    old_cover = collection["cover_image"]
    if old_cover and Path(old_cover).name == old_cover and old_cover != filename:
        (COVER_DIR / old_cover).unlink(missing_ok=True)

    return {
        "message": "Cover image uploaded successfully.",
        "collection_id": collection_id,
        "cover_image": filename,
        "media_type": media_type,
    }



def _published_naat_filter():
    return """
        (
            EXISTS (
                SELECT 1 FROM naat_versions AS v
                WHERE v.naat_id = n.id
                  AND v.status = 'published'
                  AND length(trim(v.text)) > 0
            )
            OR EXISTS (
                SELECT 1 FROM naat_sources AS s
                WHERE s.naat_id = n.id
                  AND s.status = 'published'
                  AND length(trim(s.text)) > 0
            )
        )
    """


def _public_naat_payload(conn, row):
    item = dict(row)

    versions = conn.execute(
        """
        SELECT language, format, script_code, text
        FROM naat_versions
        WHERE naat_id = ?
          AND status = 'published'
          AND length(trim(text)) > 0
        ORDER BY language COLLATE NOCASE, format
        """,
        (row["id"],),
    ).fetchall()

    sources = conn.execute(
        """
        SELECT language, script_code, source_format, text
        FROM naat_sources
        WHERE naat_id = ?
          AND status = 'published'
          AND length(trim(text)) > 0
        ORDER BY language COLLATE NOCASE, script_code
        """,
        (row["id"],),
    ).fetchall()

    item["published_languages"] = sorted({
        version["language"] for version in versions
    } | {
        source["language"] for source in sources
    }, key=str.casefold)

    item["versions"] = [dict(version) for version in versions]
    item["sources"] = [dict(source) for source in sources]
    return item


@app.get("/api/v1/public/collections")
def public_list_collections():
    with connect_db() as conn:
        rows = conn.execute(
            f"""
            SELECT c.id, c.title, c.author, c.description,
                   c.cover_image, c.created_at, c.updated_at,
                   (
                       SELECT COUNT(*)
                       FROM naats AS n
                       WHERE n.collection_id = c.id
                         AND {_published_naat_filter()}
                   ) AS naat_count
            FROM naat_collections AS c
            WHERE EXISTS (
                SELECT 1
                FROM naats AS n
                WHERE n.collection_id = c.id
                  AND {_published_naat_filter()}
            )
            ORDER BY c.title COLLATE NOCASE
            """
        ).fetchall()

    collections = []
    for row in rows:
        item = dict(row)
        item["cover_url"] = (
            f"/api/v1/public/collections/{row['id']}/cover"
            if row["cover_image"] else None
        )
        item.pop("cover_image", None)
        collections.append(item)

    return {"collections": collections}


@app.get("/api/v1/public/collections/{collection_id}/cover")
def public_collection_cover(collection_id: str):
    with connect_db() as conn:
        row = conn.execute(
            """
            SELECT cover_image
            FROM naat_collections
            WHERE id = ?
            """,
            (collection_id,),
        ).fetchone()

    if not row or not row["cover_image"]:
        raise HTTPException(status_code=404, detail="Collection cover not found.")

    filename = row["cover_image"]

    # Only serve generated filenames from the covers directory.
    if Path(filename).name != filename:
        raise HTTPException(status_code=404, detail="Collection cover not found.")

    image_path = COVER_DIR / filename
    if not image_path.is_file():
        raise HTTPException(status_code=404, detail="Collection cover not found.")

    media_types = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
    }
    media_type = media_types.get(image_path.suffix.lower())

    if not media_type:
        raise HTTPException(status_code=404, detail="Collection cover not found.")

    return FileResponse(image_path, media_type=media_type)


@app.get("/api/v1/public/collections/{collection_id}")
def public_get_collection(collection_id: str):
    with connect_db() as conn:
        row = conn.execute(
            f"""
            SELECT c.id, c.title, c.author, c.description,
                   c.cover_image, c.created_at, c.updated_at,
                   (
                       SELECT COUNT(*)
                       FROM naats AS n
                       WHERE n.collection_id = c.id
                         AND {_published_naat_filter()}
                   ) AS naat_count
            FROM naat_collections AS c
            WHERE c.id = ?
              AND EXISTS (
                  SELECT 1
                  FROM naats AS n
                  WHERE n.collection_id = c.id
                    AND {_published_naat_filter()}
              )
            """,
            (collection_id,),
        ).fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Collection not found.")

    result = dict(row)
    result["cover_url"] = (
        f"/api/v1/public/collections/{collection_id}/cover"
        if row["cover_image"] else None
    )
    result.pop("cover_image", None)
    return result


@app.get("/api/v1/public/collections/{collection_id}/naats")
def public_list_collection_naats(collection_id: str):
    with connect_db() as conn:
        collection = conn.execute(
            "SELECT id FROM naat_collections WHERE id = ?",
            (collection_id,),
        ).fetchone()

        if not collection:
            raise HTTPException(status_code=404, detail="Collection not found.")

        rows = conn.execute(
            f"""
            SELECT n.id, n.title, n.poet, n.book_name, n.page_number,
                   n.collection_id, n.created_at, n.updated_at
            FROM naats AS n
            WHERE n.collection_id = ?
              AND {_published_naat_filter()}
            ORDER BY n.updated_at DESC, n.title COLLATE NOCASE
            """,
            (collection_id,),
        ).fetchall()

        naats = [_public_naat_payload(conn, row) for row in rows]

    return {"naats": naats}


@app.get("/api/v1/public/naats")
def public_list_naats():
    with connect_db() as conn:
        rows = conn.execute(
            """
            SELECT n.id, n.title, n.poet, n.book_name, n.page_number,
                   n.collection_id, n.created_at, n.updated_at
            FROM naats AS n
            WHERE (
                EXISTS (
                    SELECT 1
                    FROM naat_versions AS v
                    WHERE v.naat_id = n.id
                      AND v.status = 'published'
                      AND length(trim(v.text)) > 0
                )
                OR EXISTS (
                    SELECT 1
                    FROM naat_sources AS s
                    WHERE s.naat_id = n.id
                      AND s.status = 'published'
                      AND length(trim(s.text)) > 0
                )
            )
            ORDER BY n.updated_at DESC, n.title COLLATE NOCASE
            """
        ).fetchall()

        naats = []
        for row in rows:
            item = dict(row)
            versions = conn.execute(
                """
                SELECT language, format, script_code, text
                FROM naat_versions
                WHERE naat_id = ?
                  AND status = 'published'
                  AND length(trim(text)) > 0
                ORDER BY language COLLATE NOCASE, format
                """,
                (row["id"],),
            ).fetchall()
            sources = conn.execute(
                """
                SELECT language, script_code, source_format, text
                FROM naat_sources
                WHERE naat_id = ?
                  AND status = 'published'
                  AND length(trim(text)) > 0
                ORDER BY language COLLATE NOCASE, script_code
                """,
                (row["id"],),
            ).fetchall()

            item["published_languages"] = sorted({
                version["language"] for version in versions
            } | {
                source["language"] for source in sources
            }, key=str.casefold)
            item["versions"] = [dict(version) for version in versions]
            item["sources"] = [dict(source) for source in sources]
            naats.append(item)

    return {"naats": naats}


@app.get("/api/v1/public/naats/{naat_id}")
def public_get_naat(naat_id: str):
    with connect_db() as conn:
        naat = conn.execute(
            """
            SELECT id, title, poet, book_name, page_number,
                   collection_id, created_at, updated_at
            FROM naats
            WHERE id = ?
              AND (
                  EXISTS (
                      SELECT 1
                      FROM naat_versions
                      WHERE naat_id = naats.id
                        AND status = 'published'
                        AND length(trim(text)) > 0
                  )
                  OR EXISTS (
                      SELECT 1
                      FROM naat_sources
                      WHERE naat_id = naats.id
                        AND status = 'published'
                        AND length(trim(text)) > 0
                  )
              )
            """,
            (naat_id,),
        ).fetchone()

        if not naat:
            raise HTTPException(status_code=404, detail="Naat not found")

        versions = conn.execute(
            """
            SELECT language, format, script_code, text
            FROM naat_versions
            WHERE naat_id = ?
              AND status = 'published'
              AND length(trim(text)) > 0
            ORDER BY language COLLATE NOCASE, format
            """,
            (naat_id,),
        ).fetchall()

        sources = conn.execute(
            """
            SELECT language, script_code, source_format, text
            FROM naat_sources
            WHERE naat_id = ?
              AND status = 'published'
              AND length(trim(text)) > 0
            ORDER BY language COLLATE NOCASE, script_code
            """,
            (naat_id,),
        ).fetchall()

    result = dict(naat)
    result["published_languages"] = sorted({
        version["language"] for version in versions
    } | {
        source["language"] for source in sources
    }, key=str.casefold)
    result["versions"] = [dict(version) for version in versions]
    result["sources"] = [dict(source) for source in sources]
    return result


@app.get("/api/v1/naats")
def list_naats(admin=Depends(current_admin)):
    with connect_db() as conn:
        rows = conn.execute(
            "SELECT * FROM naats ORDER BY updated_at DESC"
        ).fetchall()
    return {"naats": [dict(row) for row in rows]}


@app.post("/api/v1/naats", status_code=201)
def create_naat(data: NaatCreateRequest, admin=Depends(current_admin)):
    now = datetime.now(timezone.utc).isoformat()
    naat_id = str(uuid.uuid4())
    with connect_db() as conn:
        book_name = data.book_name.strip()
        poet = data.poet.strip()
        if not poet or not book_name:
            raise HTTPException(status_code=422, detail="Author and book name are required. Use Anonymous or Unknown if not known.")
        page_number = data.page_number
        if book_name and page_number is None:
            page_number = conn.execute(
                """SELECT COALESCE(MAX(page_number), 0) + 1
                   FROM naats WHERE lower(trim(book_name)) = lower(?)
                   AND lower(trim(poet)) = lower(?)""",
                (book_name, poet),
            ).fetchone()[0]
        if book_name and page_number is not None:
            duplicate = conn.execute(
                """SELECT 1 FROM naats
                   WHERE lower(trim(book_name)) = lower(?)
                   AND lower(trim(poet)) = lower(?) AND page_number = ?""",
                (book_name, poet, page_number),
            ).fetchone()
            if duplicate:
                raise HTTPException(status_code=409, detail="That page number is already used in this book by this author")
        conn.execute(
            """INSERT INTO naats
               (id, title, poet, book_name, page_number, source_language,
                original_text, source_format, status, created_by, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'draft', ?, ?, ?)""",
            (naat_id, data.title.strip(), poet, book_name, page_number,
             data.source_language, data.original_text, data.source_format,
             admin["username"], now, now),
        )
        if data.original_text.strip():
            script_code = {
                "urdu_script": "ur-Arab",
                "roman_urdu": "ur-Latn",
            }.get(data.source_format, "und")

            conn.execute(
                """INSERT INTO naat_sources
                   (id, naat_id, language, script_code, source_format, text,
                    status, created_by, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, 'draft', ?, ?, ?)""",
                (
                    str(uuid.uuid4()), naat_id, data.source_language.strip(),
                    script_code, data.source_format, data.original_text,
                    admin["username"], now, now,
                ),
            )

        row = conn.execute("SELECT * FROM naats WHERE id = ?", (naat_id,)).fetchone()
    return dict(row)


@app.get("/api/v1/naats/{naat_id}")
def get_naat(naat_id: str, admin=Depends(current_admin)):
    with connect_db() as conn:
        naat = conn.execute("SELECT * FROM naats WHERE id = ?", (naat_id,)).fetchone()
        if not naat:
            raise HTTPException(status_code=404, detail="Naat not found")
        sources = conn.execute(
            """SELECT * FROM naat_sources
               WHERE naat_id = ? ORDER BY language, script_code""",
            (naat_id,),
        ).fetchall()
        versions = conn.execute(
            "SELECT * FROM naat_versions WHERE naat_id = ? ORDER BY language, format",
            (naat_id,),
        ).fetchall()
    result = dict(naat)
    result["sources"] = [dict(row) for row in sources]
    result["versions"] = [dict(row) for row in versions]
    return result


@app.post("/api/v1/naats/{naat_id}/conversion-jobs")
def create_kannada_conversion_job(
    naat_id: str,
    admin=Depends(current_admin),
):
    now = datetime.now(timezone.utc).isoformat()
    job_id = str(uuid.uuid4())

    with connect_db() as conn:
        naat = conn.execute(
            "SELECT id FROM naats WHERE id = ?", (naat_id,)
        ).fetchone()
        if not naat:
            raise HTTPException(status_code=404, detail="Naat not found")

        roman = conn.execute(
            """SELECT * FROM naat_versions
               WHERE naat_id = ? AND language = 'Roman Urdu'
                 AND format = 'transliteration'""",
            (naat_id,),
        ).fetchone()

        if not roman or not roman["text"].strip():
            raise HTTPException(
                status_code=422,
                detail="Save a non-empty Roman Urdu version before generating Kannada.",
            )

        published = conn.execute(
            """SELECT id FROM naat_versions
               WHERE naat_id = ? AND language = 'Kannada'
                 AND format = 'transliteration' AND status = 'published'""",
            (naat_id,),
        ).fetchone()
        if published:
            raise HTTPException(
                status_code=409,
                detail="Kannada version is already published and cannot be overwritten.",
            )

        active = conn.execute(
            """SELECT id FROM conversion_jobs
               WHERE naat_id = ? AND target_language = 'Kannada'
                 AND conversion_type = 'transliteration'
                 AND status IN ('pending', 'processing')
               LIMIT 1""",
            (naat_id,),
        ).fetchone()
        if active:
            raise HTTPException(
                status_code=409,
                detail="A Kannada conversion job is already pending or processing.",
            )

        conn.execute(
            """INSERT INTO conversion_jobs
               (id, naat_id, source_version_id, target_language,
                target_script_code, conversion_type, status, generated_text,
                error_message, requested_by, created_at, completed_at,
                source_id, source_text)
               VALUES (?, ?, ?, 'Kannada', 'kn-Knda', 'transliteration',
                       'pending', '', '', ?, ?, NULL, ?, ?)""",
            (
                job_id, naat_id, roman["id"], admin["username"], now,
                roman["source_id"], roman["text"],
            ),
        )

        row = conn.execute(
            "SELECT * FROM conversion_jobs WHERE id = ?", (job_id,)
        ).fetchone()

    return dict(row)


@app.get("/api/v1/conversion-jobs/{job_id}")
def get_conversion_job(
    job_id: str,
    admin=Depends(current_admin),
):
    with connect_db() as conn:
        row = conn.execute(
            "SELECT * FROM conversion_jobs WHERE id = ?", (job_id,)
        ).fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Conversion job not found")

    return dict(row)


@app.get("/api/v1/naats/{naat_id}/sources")
def list_naat_sources(naat_id: str, admin=Depends(current_admin)):
    with connect_db() as conn:
        naat = conn.execute(
            "SELECT id FROM naats WHERE id = ?", (naat_id,)
        ).fetchone()
        if not naat:
            raise HTTPException(status_code=404, detail="Naat not found")

        sources = conn.execute(
            """SELECT * FROM naat_sources
               WHERE naat_id = ? ORDER BY language, script_code""",
            (naat_id,),
        ).fetchall()

    return {"naat_id": naat_id, "sources": [dict(row) for row in sources]}


@app.post("/api/v1/naats/{naat_id}/sources", status_code=201)
def create_naat_source(
    naat_id: str,
    data: NaatSourceRequest,
    admin=Depends(current_admin),
):
    now = datetime.now(timezone.utc).isoformat()
    source_id = str(uuid.uuid4())

    with connect_db() as conn:
        naat = conn.execute(
            "SELECT id FROM naats WHERE id = ?", (naat_id,)
        ).fetchone()
        if not naat:
            raise HTTPException(status_code=404, detail="Naat not found")

        try:
            conn.execute(
                """INSERT INTO naat_sources (
                    id, naat_id, language, script_code, source_format,
                    text, status, created_by, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    source_id, naat_id, data.language.strip(),
                    data.script_code.strip(), data.source_format,
                    data.text, data.status, admin["username"], now, now,
                ),
            )
        except sqlite3.IntegrityError as exc:
            if "UNIQUE" in str(exc).upper():
                raise HTTPException(
                    status_code=409,
                    detail="A source with this language and script already exists for this Naat",
                )
            raise

        conn.execute(
            "UPDATE naats SET updated_at = ? WHERE id = ?",
            (now, naat_id),
        )
        row = conn.execute(
            "SELECT * FROM naat_sources WHERE id = ?", (source_id,)
        ).fetchone()

    return dict(row)


@app.put("/api/v1/naats/{naat_id}/sources/{source_id}")
def update_naat_source(
    naat_id: str,
    source_id: str,
    data: NaatSourceRequest,
    admin=Depends(current_admin),
):
    now = datetime.now(timezone.utc).isoformat()

    with connect_db() as conn:
        source = conn.execute(
            """SELECT * FROM naat_sources
               WHERE id = ? AND naat_id = ?""",
            (source_id, naat_id),
        ).fetchone()

        if not source:
            raise HTTPException(status_code=404, detail="Source not found")

        if source["status"] == "published":
            raise HTTPException(
                status_code=409,
                detail="Published source cannot be edited",
            )

        # Preserve the previous source text when its content changes.
        if source["text"] != data.text:
            conn.execute(
                """INSERT INTO naat_revisions (
                    naat_id, version_id, source_id, content, editor, created_at
                ) VALUES (?, NULL, ?, ?, ?, ?)""",
                (
                    naat_id, source_id, source["text"],
                    admin["username"], now,
                ),
            )

        try:
            conn.execute(
                """UPDATE naat_sources
                   SET language = ?, script_code = ?, source_format = ?,
                       text = ?, status = ?, updated_at = ?
                   WHERE id = ? AND naat_id = ?""",
                (
                    data.language.strip(),
                    data.script_code.strip(),
                    data.source_format,
                    data.text,
                    "draft" if source["text"] != data.text else data.status,
                    now,
                    source_id,
                    naat_id,
                ),
            )
        except sqlite3.IntegrityError as exc:
            if "UNIQUE" in str(exc).upper():
                raise HTTPException(
                    status_code=409,
                    detail="A source with this language and script already exists for this Naat",
                )
            raise

        conn.execute(
            "UPDATE naats SET updated_at = ? WHERE id = ?",
            (now, naat_id),
        )

        row = conn.execute(
            "SELECT * FROM naat_sources WHERE id = ?", (source_id,)
        ).fetchone()

    return dict(row)


@app.post("/api/v1/naats/{naat_id}/sources/{source_id}/publish")
def publish_naat_source(
    naat_id: str,
    source_id: str,
    admin=Depends(current_admin),
):
    now = datetime.now(timezone.utc).isoformat()

    with connect_db() as conn:
        naat = conn.execute(
            "SELECT id FROM naats WHERE id = ?", (naat_id,)
        ).fetchone()
        if not naat:
            raise HTTPException(status_code=404, detail="Naat not found")

        source = conn.execute(
            """SELECT * FROM naat_sources
               WHERE id = ? AND naat_id = ?""",
            (source_id, naat_id),
        ).fetchone()
        if not source:
            raise HTTPException(status_code=404, detail="Source not found")

        if not source["text"].strip():
            raise HTTPException(
                status_code=422,
                detail="Cannot publish an empty source",
            )

        if source["status"] != "approved":
            raise HTTPException(
                status_code=422,
                detail="Source must be approved before publishing",
            )

        conn.execute(
            """UPDATE naat_sources
               SET status = 'published', updated_at = ?
               WHERE id = ? AND naat_id = ?""",
            (now, source_id, naat_id),
        )

        conn.execute(
            """UPDATE naats SET status = 'published', updated_at = ?
               WHERE id = ?""",
            (now, naat_id),
        )

        published = conn.execute(
            "SELECT * FROM naat_sources WHERE id = ?",
            (source_id,),
        ).fetchone()

    return {
        "naat_id": naat_id,
        "source": dict(published),
        "status": "published",
    }


@app.put("/api/v1/naats/{naat_id}/collection")
def assign_naat_collection(
    naat_id: str,
    data: CollectionAssignmentRequest,
    admin=Depends(current_admin),
):
    now = datetime.now(timezone.utc).isoformat()

    with connect_db() as conn:
        naat = conn.execute(
            "SELECT id FROM naats WHERE id = ?",
            (naat_id,),
        ).fetchone()

        if not naat:
            raise HTTPException(status_code=404, detail="Naat not found")

        if data.collection_id is not None:
            collection = conn.execute(
                "SELECT id FROM naat_collections WHERE id = ?",
                (data.collection_id,),
            ).fetchone()

            if not collection:
                raise HTTPException(status_code=404, detail="Collection not found")

        conn.execute(
            """
            UPDATE naats
            SET collection_id = ?, updated_at = ?
            WHERE id = ?
            """,
            (data.collection_id, now, naat_id),
        )

    return {
        "naat_id": naat_id,
        "collection_id": data.collection_id,
        "updated_at": now,
    }


@app.put("/api/v1/naats/{naat_id}")
def update_naat(naat_id: str, data: NaatUpdateRequest, admin=Depends(current_admin)):
    now = datetime.now(timezone.utc).isoformat()
    with connect_db() as conn:
        old = conn.execute("SELECT * FROM naats WHERE id = ?", (naat_id,)).fetchone()
        if not old:
            raise HTTPException(status_code=404, detail="Naat not found")
        if old["status"] == "published":
            raise HTTPException(status_code=409, detail="Unpublish the Naat before editing")
        book_name = data.book_name.strip()
        poet = data.poet.strip()
        if not poet or not book_name:
            raise HTTPException(status_code=422, detail="Author and book name are required. Use Anonymous or Unknown if not known.")
        page_number = data.page_number
        same_book = (
            (old["book_name"] or "").strip().casefold() == book_name.casefold()
            and (old["poet"] or "").strip().casefold() == poet.casefold()
        )
        if page_number is None and book_name:
            if same_book and old["page_number"] is not None:
                page_number = old["page_number"]
            else:
                page_number = conn.execute(
                    """SELECT COALESCE(MAX(page_number), 0) + 1
                       FROM naats WHERE lower(trim(book_name)) = lower(?)
                       AND lower(trim(poet)) = lower(?) AND id != ?""",
                    (book_name, poet, naat_id),
                ).fetchone()[0]
        if book_name and page_number is not None:
            duplicate = conn.execute(
                """SELECT 1 FROM naats
                   WHERE lower(trim(book_name)) = lower(?)
                   AND lower(trim(poet)) = lower(?) AND page_number = ? AND id != ?""",
                (book_name, poet, page_number, naat_id),
            ).fetchone()
            if duplicate:
                raise HTTPException(status_code=409, detail="That page number is already used in this book by this author")
        source_language = (data.source_language or "Urdu").strip()
        script_code = {
            "urdu_script": "ur-Arab",
            "roman_urdu": "ur-Latn",
        }.get(data.source_format, "und")

        source = conn.execute(
            """SELECT * FROM naat_sources
               WHERE naat_id = ? AND language = ? AND script_code = ?""",
            (naat_id, (old["source_language"] or "Urdu").strip(),
             {"urdu_script": "ur-Arab", "roman_urdu": "ur-Latn"}.get(
                 old["source_format"], "und"
             )),
        ).fetchone()

        if source:
            if source["text"] != data.original_text:
                conn.execute(
                    """INSERT INTO naat_revisions
                       (naat_id, version_id, source_id, content, editor, created_at)
                       VALUES (?, NULL, ?, ?, ?, ?)""",
                    (naat_id, source["id"], source["text"],
                     admin["username"], now),
                )
            conn.execute(
                """UPDATE naat_sources
                   SET language=?, script_code=?, source_format=?, text=?,
                       status=?, updated_at=?
                   WHERE id=?""",
                (source_language, script_code, data.source_format,
                 data.original_text,
                 "draft" if source["text"] != data.original_text else source["status"],
                 now, source["id"]),
            )
        elif data.original_text.strip():
            conn.execute(
                """INSERT INTO naat_sources
                   (id, naat_id, language, script_code, source_format, text,
                    status, created_by, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, 'draft', ?, ?, ?)""",
                (str(uuid.uuid4()), naat_id, source_language, script_code,
                 data.source_format, data.original_text,
                 admin["username"], now, now),
            )

        conn.execute(
            """UPDATE naats SET title=?, poet=?, book_name=?, page_number=?,
               source_language=?, original_text=?, source_format=?,
               status='draft', updated_at=? WHERE id=?""",
            (data.title.strip(), poet, book_name, page_number,
             data.source_language, data.original_text, data.source_format,
             now, naat_id),
        )
        row = conn.execute("SELECT * FROM naats WHERE id = ?", (naat_id,)).fetchone()
    return dict(row)


@app.delete("/api/v1/naats/{naat_id}")
def delete_naat(naat_id: str, admin=Depends(current_admin)):
    with connect_db() as conn:
        naat = conn.execute(
            "SELECT id, title FROM naats WHERE id = ?", (naat_id,)
        ).fetchone()
        if not naat:
            raise HTTPException(status_code=404, detail="Naat not found")

        # Explicitly remove only this naat and its dependent lyric history.
        conn.execute("DELETE FROM naat_revisions WHERE naat_id = ?", (naat_id,))
        conn.execute("DELETE FROM conversion_jobs WHERE naat_id = ?", (naat_id,))
        conn.execute("DELETE FROM naat_versions WHERE naat_id = ?", (naat_id,))
        conn.execute("DELETE FROM naat_sources WHERE naat_id = ?", (naat_id,))
        conn.execute("DELETE FROM naats WHERE id = ?", (naat_id,))

    return {"deleted": True, "id": naat_id, "title": naat["title"]}


@app.put("/api/v1/naats/{naat_id}/versions")
def save_naat_version(naat_id: str, data: NaatVersionRequest, admin=Depends(current_admin)):
    now = datetime.now(timezone.utc).isoformat()
    version_id = str(uuid.uuid4())
    with connect_db() as conn:
        naat = conn.execute("SELECT status FROM naats WHERE id = ?", (naat_id,)).fetchone()
        if not naat:
            raise HTTPException(status_code=404, detail="Naat not found")
        if data.source_id:
            source = conn.execute(
                "SELECT id FROM naat_sources WHERE id=? AND naat_id=?",
                (data.source_id, naat_id),
            ).fetchone()
            if not source:
                raise HTTPException(status_code=404, detail="Source not found for this Naat")

        existing = conn.execute(
            "SELECT * FROM naat_versions WHERE naat_id=? AND language=? AND format=?",
            (naat_id, data.language, data.format),
        ).fetchone()
        if existing:
            if existing["status"] == "published":
                raise HTTPException(status_code=409, detail="Published version cannot be edited")
            conn.execute(
                """INSERT INTO naat_revisions (naat_id, version_id, content, editor, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (naat_id, existing["id"], existing["text"], admin["username"], now),
            )
            conn.execute(
                """UPDATE naat_versions
                   SET text=?, status=?, updated_by=?, updated_at=?,
                       script_code=?, source_id=?
                   WHERE id=?""",
                (
                    data.text, data.status, admin["username"], now,
                    data.script_code or existing["script_code"],
                    data.source_id or existing["source_id"],
                    existing["id"],
                ),
            )
            version_id = existing["id"]
        else:
            conn.execute(
                """INSERT INTO naat_versions
                   (id, naat_id, language, format, text, status, updated_by,
                    created_at, updated_at, script_code, source_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    version_id, naat_id, data.language, data.format, data.text,
                    data.status, admin["username"], now, now,
                    data.script_code, data.source_id,
                ),
            )
        conn.execute(
            """UPDATE naats
               SET status = CASE
                   WHEN EXISTS (
                       SELECT 1 FROM naat_versions
                       WHERE naat_id = ? AND status = 'published'
                   ) THEN 'published'
                   ELSE 'draft'
               END,
               updated_at = ?
               WHERE id = ?""",
            (naat_id, now, naat_id),
        )
        row = conn.execute("SELECT * FROM naat_versions WHERE id=?", (version_id,)).fetchone()
    return dict(row)


@app.post("/api/v1/naats/{naat_id}/validate")
def validate_naat(naat_id: str, admin=Depends(current_admin)):
    with connect_db() as conn:
        naat = conn.execute("SELECT * FROM naats WHERE id=?", (naat_id,)).fetchone()
        if not naat:
            raise HTTPException(status_code=404, detail="Naat not found")
        versions = conn.execute(
            "SELECT * FROM naat_versions WHERE naat_id=?", (naat_id,)
        ).fetchall()

    issues = []
    if not naat["title"].strip():
        issues.append("Naat title is required.")
    if not naat["original_text"].strip():
        issues.append("Original lyrics are empty.")
    for version in versions:
        if not version["text"].strip():
            issues.append(f'{version["language"]} ({version["format"]}) is empty.')
        if version["text"].strip() and len(version["text"].strip()) < 3:
            issues.append(f'{version["language"]} may be incomplete.')
    return {
        "naat_id": naat_id,
        "valid": len(issues) == 0,
        "issues": issues,
        "version_count": len(versions),
    }


@app.post("/api/v1/naats/{naat_id}/versions/{version_id}/publish")
def publish_naat_version(
    naat_id: str,
    version_id: str,
    admin=Depends(current_admin),
):
    now = datetime.now(timezone.utc).isoformat()

    with connect_db() as conn:
        naat = conn.execute(
            "SELECT id FROM naats WHERE id = ?", (naat_id,)
        ).fetchone()
        if not naat:
            raise HTTPException(status_code=404, detail="Naat not found")

        version = conn.execute(
            """SELECT * FROM naat_versions
               WHERE id = ? AND naat_id = ?""",
            (version_id, naat_id),
        ).fetchone()
        if not version:
            raise HTTPException(status_code=404, detail="Version not found")

        if not version["text"].strip():
            raise HTTPException(
                status_code=422,
                detail="Cannot publish an empty version",
            )

        if version["status"] != "approved":
            raise HTTPException(
                status_code=422,
                detail="Version must be approved before publishing",
            )

        conn.execute(
            """UPDATE naat_versions
               SET status = 'published', updated_at = ?
               WHERE id = ? AND naat_id = ?""",
            (now, version_id, naat_id),
        )

        conn.execute(
            """UPDATE naats SET status = 'published', updated_at = ?
               WHERE id = ?""",
            (now, naat_id),
        )

        published = conn.execute(
            "SELECT * FROM naat_versions WHERE id = ?",
            (version_id,),
        ).fetchone()

    return {
        "naat_id": naat_id,
        "version": dict(published),
        "status": "published",
    }


@app.post("/api/v1/naats/{naat_id}/publish")
def publish_naat(naat_id: str, admin=Depends(current_admin)):
    now = datetime.now(timezone.utc).isoformat()
    with connect_db() as conn:
        naat = conn.execute("SELECT * FROM naats WHERE id=?", (naat_id,)).fetchone()
        if not naat:
            raise HTTPException(status_code=404, detail="Naat not found")
        versions = conn.execute(
            "SELECT * FROM naat_versions WHERE naat_id=?", (naat_id,)
        ).fetchall()
        if not naat["original_text"].strip():
            raise HTTPException(status_code=422, detail="Original lyrics are required")
        if not versions or any(not v["text"].strip() or v["status"] != "approved" for v in versions):
            raise HTTPException(
                status_code=422,
                detail="Every saved language version must contain text and be approved before publishing",
            )
        conn.execute("UPDATE naats SET status='published', updated_at=? WHERE id=?", (now, naat_id))
        conn.execute(
            "UPDATE naat_versions SET status='published', updated_at=? WHERE naat_id=?",
            (now, naat_id),
        )
    return {"naat_id": naat_id, "status": "published"}


@app.post("/api/v1/auth/login")
def login(data: LoginRequest, response: Response):
    with connect_db() as conn:
        admin = conn.execute(
            "SELECT username, password_hash FROM admins WHERE username = ?",
            (data.username,),
        ).fetchone()

    valid = False
    if admin:
        try:
            valid = hasher.verify(admin["password_hash"], data.password)
        except (VerifyMismatchError, VerificationError):
            valid = False

    if not valid:
        raise HTTPException(status_code=401, detail="Invalid username or password")

    token = jwt.encode(
        {"sub": admin["username"], "exp": __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc
        ) + __import__("datetime").timedelta(seconds=TOKEN_TTL_SECONDS)},
        SECRET_KEY,
        algorithm="HS256",
    )

    response.set_cookie(
        key="naatify_session",
        value=token,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite="strict",
        max_age=TOKEN_TTL_SECONDS,
        path="/",
    )
    return {"message": "Login successful", "username": admin["username"]}




@app.post("/api/v1/transliterate")
def transliterate_text(
    data: TransliterationRequest,
    admin=Depends(current_admin),
):
    result = transliterate_urdu(data.text)
    return result


@app.post("/api/v1/transliterate/kannada")
def transliterate_kannada(
    data: TransliterationRequest,
    admin=Depends(current_admin),
):
    try:
        generated = call_kannada_service(data.text)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    return {
        "original_text": data.text,
        "kannada_text": generated,
        "review_status": "needs_review",
    }


@app.get("/api/v1/auth/me")
def me(admin=Depends(current_admin)):
    return admin


@app.post("/api/v1/auth/logout")
def logout(response: Response):
    response.delete_cookie(
        "naatify_session",
        path="/",
        httponly=True,
        secure=COOKIE_SECURE,
        samesite="strict",
    )
    return {"message": "Logged out"}


@app.post("/api/v1/books", status_code=201)
async def upload_book(
    title: str = Form(..., min_length=1, max_length=200),
    author: str = Form(..., min_length=1, max_length=200),
    file: UploadFile = File(...),
    admin=Depends(current_admin),
):
    title = title.strip()
    author = author.strip()

    if not title:
        raise HTTPException(status_code=422, detail="Book title is required")
    if not author:
        raise HTTPException(status_code=422, detail="Book author is required. Use Anonymous if not known.")

    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Select a PDF file")

    book_id = str(uuid.uuid4())
    stored_filename = f"{book_id}.pdf"
    destination = UPLOAD_DIR / stored_filename
    total = 0
    header = b""

    try:
        with destination.open("xb") as output:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break

                if len(header) < 5:
                    header += chunk[:5 - len(header)]

                total += len(chunk)
                if total > MAX_PDF_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail="PDF must be 50 MB or smaller",
                    )
                output.write(chunk)

        if total < 5 or header != b"%PDF-":
            raise HTTPException(
                status_code=400,
                detail="The uploaded file is not a valid PDF",
            )

        created_at = datetime.now(timezone.utc).isoformat()
        original_filename = Path(file.filename).name[:255]

        with connect_db() as conn:
            conn.execute(
                """
                INSERT INTO books
                (id, title, author, original_filename, stored_filename,
                 file_size, status, uploaded_by, created_at)
                VALUES (?, ?, ?, ?, ?, ?, 'uploaded', ?, ?)
                """,
                (
                    book_id, title, author, original_filename,
                    stored_filename, total, admin["username"], created_at,
                ),
            )

        return {
            "id": book_id,
            "title": title,
            "author": author,
            "original_filename": original_filename,
            "file_size": total,
            "status": "uploaded",
            "created_at": created_at,
        }
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    finally:
        await file.close()


@app.get("/api/v1/books")
def list_books(admin=Depends(current_admin)):
    with connect_db() as conn:
        rows = conn.execute(
            """
            SELECT id, title, author, original_filename, file_size,
                   status, uploaded_by, created_at
            FROM books
            ORDER BY created_at DESC
            """
        ).fetchall()
    return {"books": [dict(row) for row in rows]}


@app.get("/api/v1/books/{book_id}/inspect")
def inspect_book(book_id: str, admin=Depends(current_admin)):
    with connect_db() as conn:
        book = conn.execute(
            """
            SELECT id, title, author, original_filename, stored_filename,
                   file_size, status, created_at
            FROM books WHERE id = ?
            """,
            (book_id,),
        ).fetchone()

    if not book:
        raise HTTPException(status_code=404, detail="Book not found")

    # Resolve only the generated filename stored by the upload endpoint.
    stored_filename = book["stored_filename"]
    if (
        not stored_filename
        or Path(stored_filename).name != stored_filename
        or not stored_filename.endswith(".pdf")
    ):
        raise HTTPException(status_code=500, detail="Invalid stored PDF reference")

    pdf_path = UPLOAD_DIR / stored_filename
    if not pdf_path.is_file():
        raise HTTPException(status_code=404, detail="Stored PDF file not found")

    try:
        reader = PdfReader(str(pdf_path), strict=False)

        if reader.is_encrypted:
            decrypt_result = reader.decrypt("")
            if not decrypt_result:
                raise HTTPException(
                    status_code=422,
                    detail="This PDF requires a password for inspection",
                )

        page_count = len(reader.pages)
        pages = []
        pages_with_text = 0

        # Inspect all pages, but retain only a short text sample per page.
        # No page images are rendered and the PDF is never modified.
        for index, page in enumerate(reader.pages):
            text = (page.extract_text() or "").strip()
            if text:
                pages_with_text += 1

            box = page.mediabox
            pages.append({
                "page_number": index + 1,
                "width_pt": round(float(box.width), 2),
                "height_pt": round(float(box.height), 2),
                "text_characters": len(text),
                "has_selectable_text": bool(text),
                "text_sample": text[:160],
            })

        return {
            "book": {
                "id": book["id"],
                "title": book["title"],
                "author": book["author"],
                "original_filename": book["original_filename"],
                "file_size": book["file_size"],
                "status": book["status"],
                "created_at": book["created_at"],
            },
            "inspection": {
                "page_count": page_count,
                "pages_with_selectable_text": pages_with_text,
                "pages_likely_scanned": page_count - pages_with_text,
                "text_extraction_available": pages_with_text > 0,
                "pages": pages,
            },
        }
    except HTTPException:
        raise
    except Exception as exc:
        # Avoid exposing internal file paths or parser details to the client.
        raise HTTPException(
            status_code=422,
            detail="Unable to inspect this PDF. It may be damaged or unsupported.",
        ) from exc


@app.post("/api/v1/books/{book_id}/extract")
def extract_book_pages(
    book_id: str,
    start_page: int = 1,
    limit: int = 10,
    admin=Depends(current_admin),
):
    if start_page < 1:
        raise HTTPException(status_code=422, detail="start_page must be at least 1")
    if limit < 1 or limit > 20:
        raise HTTPException(status_code=422, detail="limit must be between 1 and 20")

    with connect_db() as conn:
        book = conn.execute(
            "SELECT id, stored_filename FROM books WHERE id = ?",
            (book_id,),
        ).fetchone()

    if not book:
        raise HTTPException(status_code=404, detail="Book not found")

    stored_filename = book["stored_filename"]
    if (
        not stored_filename
        or Path(stored_filename).name != stored_filename
        or not stored_filename.endswith(".pdf")
    ):
        raise HTTPException(status_code=500, detail="Invalid stored PDF reference")

    pdf_path = UPLOAD_DIR / stored_filename
    if not pdf_path.is_file():
        raise HTTPException(status_code=404, detail="Stored PDF file not found")

    from app.page_extraction import extract_pdf_pages

    try:
        result = extract_pdf_pages(
            str(pdf_path),
            start_page=start_page,
            limit=limit,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=422,
            detail="Unable to extract pages from this PDF.",
        ) from exc

    saved_pages = []
    with connect_db() as conn:
        for page in result["pages"]:
            existing = conn.execute(
                """
                SELECT review_status, extracted_text, ocr_text, page_type,
                       processing_status
                FROM book_pages
                WHERE book_id = ? AND page_number = ?
                """,
                (book_id, page["page_number"]),
            ).fetchone()

            # Do not overwrite human-reviewed or approved content.
            if existing and existing["review_status"] in ("reviewed", "approved"):
                saved_pages.append({
                    "page_number": page["page_number"],
                    "processing_status": existing["processing_status"],
                    "review_status": existing["review_status"],
                    "saved": False,
                    "preserved_reviewed_content": True,
                })
                continue

            if existing:
                conn.execute(
                    """
                    UPDATE book_pages
                    SET extracted_text = ?,
                        ocr_text = ?,
                        page_type = CASE
                            WHEN page_type = 'unknown' THEN ?
                            ELSE page_type
                        END,
                        processing_status = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE book_id = ? AND page_number = ?
                    """,
                    (
                        page["extracted_text"],
                        page.get("ocr_text", ""),
                        page["page_type"],
                        page["processing_status"],
                        book_id,
                        page["page_number"],
                    ),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO book_pages (
                        book_id, page_number, extracted_text, ocr_text, page_type,
                        processing_status, review_status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        book_id,
                        page["page_number"],
                        page["extracted_text"],
                        page.get("ocr_text", ""),
                        page["page_type"],
                        page["processing_status"],
                        page["review_status"],
                    ),
                )

            saved_pages.append({
                "page_number": page["page_number"],
                "text_characters": page["text_characters"],
                "processing_status": page["processing_status"],
                "review_status": "pending",
                "saved": True,
                "preserved_reviewed_content": False,
            })

    return {
        "book_id": book_id,
        "page_count": result["page_count"],
        "start_page": result["start_page"],
        "end_page": result["end_page"],
        "pages": saved_pages,
    }


class PageTransliterationRequest(BaseModel):
    book_id: str = Field(min_length=1, max_length=100)
    page_number: int = Field(ge=1, le=10000)
    source_urdu: str = Field(max_length=20000)
    roman_urdu: str = Field(default="", max_length=40000)
    status: str = Field(default="draft", pattern="^(draft|reviewed|approved)$")


@app.get("/api/v1/transliterations")
def list_transliterations(
    book_id: str,
    start_page: int = 1,
    end_page: int = 20,
    admin=Depends(current_admin),
):
    print(f"[transliteration] LIST request book_id={book_id} range={start_page}-{end_page}", flush=True)
    if start_page < 1 or end_page < start_page or end_page - start_page > 99:
        print(f"[transliteration] LIST invalid range={start_page}-{end_page}", flush=True)
        raise HTTPException(status_code=422, detail="Choose a valid range of up to 100 pages")

    with connect_db() as conn:
        book = conn.execute(
            "SELECT id, title, original_filename FROM books WHERE id = ?", (book_id,)
        ).fetchone()
        if not book:
            raise HTTPException(status_code=404, detail="Book not found")

        pages = conn.execute("""
            SELECT bp.page_number,
                   COALESCE(NULLIF(pt.source_urdu, ''), NULLIF(bp.extracted_text, ''),
                            NULLIF(bp.ocr_text, ''), '') AS source_urdu,
                   COALESCE(pt.roman_urdu, '') AS roman_urdu,
                   COALESCE(pt.status, 'draft') AS status,
                   bp.processing_status
            FROM book_pages bp
            LEFT JOIN page_transliterations pt
              ON pt.book_id = bp.book_id AND pt.page_number = bp.page_number
            WHERE bp.book_id = ? AND bp.page_number BETWEEN ? AND ?
            ORDER BY bp.page_number
        """, (book_id, start_page, end_page)).fetchall()

        saved = conn.execute("""
            SELECT page_number, source_urdu, roman_urdu, status
            FROM page_transliterations
            WHERE book_id = ? AND page_number BETWEEN ? AND ?
            ORDER BY page_number
        """, (book_id, start_page, end_page)).fetchall()

    by_number = {row["page_number"]: dict(row) for row in pages}
    for row in saved:
        by_number[row["page_number"]] = {
            **by_number.get(row["page_number"], {}),
            **dict(row),
        }

    # Include pages without extraction records so scanned pages can be entered manually.
    result_pages = []
    for number in range(start_page, end_page + 1):
        result_pages.append({
            "page_number": number,
            "source_urdu": "",
            "roman_urdu": "",
            "status": "draft",
            "processing_status": "not_extracted",
            **by_number.get(number, {}),
        })

    print(
        f"[transliteration] LIST result book_id={book_id} count={len(result_pages)} "
        f"pages_with_urdu={sum(bool(x.get('source_urdu')) for x in result_pages)} "
        f"pages_with_roman={sum(bool(x.get('roman_urdu')) for x in result_pages)}",
        flush=True,
    )
    return {
        "book": dict(book),
        "start_page": start_page,
        "end_page": end_page,
        "pages": result_pages,
    }


@app.post("/api/v1/transliterations/generate")
def generate_page_transliteration(
    data: PageTransliterationRequest,
    admin=Depends(current_admin),
):
    print(
        f"[transliteration] GENERATE request book_id={data.book_id} "
        f"page={data.page_number} urdu_chars={len(data.source_urdu)}",
        flush=True,
    )
    if not data.source_urdu.strip():
        print(f"[transliteration] GENERATE rejected empty text page={data.page_number}", flush=True)
        raise HTTPException(status_code=422, detail="Enter Urdu text before transliterating")

    with connect_db() as conn:
        exists = conn.execute(
            "SELECT 1 FROM books WHERE id = ?", (data.book_id,)
        ).fetchone()
        if not exists:
            raise HTTPException(status_code=404, detail="Book not found")
        existing = conn.execute("""
            SELECT status FROM page_transliterations
            WHERE book_id = ? AND page_number = ?
        """, (data.book_id, data.page_number)).fetchone()

    if existing and existing["status"] == "approved":
        raise HTTPException(status_code=409, detail="Approved content cannot be regenerated; edit through an explicit review workflow")

    result = transliterate_urdu(data.source_urdu)
    print(
        f"[transliteration] GENERATE success page={data.page_number} "
        f"roman_chars={len(result.get('roman_urdu', ''))} "
        f"review_status={result.get('review_status')}",
        flush=True,
    )
    return {
        "book_id": data.book_id,
        "page_number": data.page_number,
        **result,
    }


@app.put("/api/v1/transliterations")
def save_page_transliteration(
    data: PageTransliterationRequest,
    admin=Depends(current_admin),
):
    print(
        f"[transliteration] SAVE request book_id={data.book_id} "
        f"page={data.page_number} status={data.status} "
        f"urdu_chars={len(data.source_urdu)} roman_chars={len(data.roman_urdu)}",
        flush=True,
    )
    if not data.source_urdu.strip():
        print(f"[transliteration] SAVE rejected empty Urdu page={data.page_number}", flush=True)
        raise HTTPException(status_code=422, detail="Urdu source text cannot be empty")
    if not data.roman_urdu.strip():
        print(f"[transliteration] SAVE rejected empty Roman Urdu page={data.page_number}", flush=True)
        raise HTTPException(status_code=422, detail="Roman Urdu text cannot be empty")

    with connect_db() as conn:
        if not conn.execute("SELECT 1 FROM books WHERE id = ?", (data.book_id,)).fetchone():
            raise HTTPException(status_code=404, detail="Book not found")

        existing = conn.execute("""
            SELECT status FROM page_transliterations
            WHERE book_id = ? AND page_number = ?
        """, (data.book_id, data.page_number)).fetchone()

        if existing and existing["status"] == "approved" and data.status != "approved":
            raise HTTPException(status_code=409, detail="Approved content cannot be downgraded")

        conn.execute("""
            INSERT INTO page_transliterations
                (book_id, page_number, source_urdu, roman_urdu, status, updated_at)
            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(book_id, page_number) DO UPDATE SET
                source_urdu = excluded.source_urdu,
                roman_urdu = excluded.roman_urdu,
                status = excluded.status,
                updated_at = CURRENT_TIMESTAMP
        """, (
            data.book_id, data.page_number, data.source_urdu.strip(),
            data.roman_urdu.strip(), data.status
        ))

    print(
        f"[transliteration] SAVE success book_id={data.book_id} "
        f"page={data.page_number} status={data.status}",
        flush=True,
    )
    return {
        "saved": True,
        "book_id": data.book_id,
        "page_number": data.page_number,
        "status": data.status,
    }


@app.get("/api/v1/transliterations/export")
def export_approved_transliterations(
    book_id: str,
    admin=Depends(current_admin),
):
    from fastapi.responses import JSONResponse

    with connect_db() as conn:
        book = conn.execute(
            "SELECT id, title, author, original_filename FROM books WHERE id = ?",
            (book_id,),
        ).fetchone()
        if not book:
            raise HTTPException(status_code=404, detail="Book not found")

        pages = conn.execute("""
            SELECT page_number, source_urdu, roman_urdu
            FROM page_transliterations
            WHERE book_id = ? AND status = 'approved'
            ORDER BY page_number
        """, (book_id,)).fetchall()

    payload = {
        "schema_version": 1,
        "book": dict(book),
        "language": "ur",
        "transliteration_language": "Roman Urdu",
        "pages": [dict(row) for row in pages],
    }
    filename = f"naatify-{book_id}-approved.json"
    return JSONResponse(
        content=payload,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
