import hashlib
import mimetypes
import os
import re
import shutil
import sqlite3
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import Body, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from PIL import ExifTags, Image, ImageOps

from .auth import (
    clear_session,
    grant_project_access,
    hash_password,
    load_session,
    require_admin,
    require_project_level,
    revoke_project_access,
    save_session,
    verify_admin_password,
    verify_password,
)

DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
THUMBS_DIR = Path(os.environ.get("THUMBS_DIR", "/data/thumbs"))
PROJECTS_ROOT = Path(os.environ.get("PROJECTS_ROOT", "/projects"))
ROOT_PATH = os.environ.get("ROOT_PATH", "")

DATA_DIR.mkdir(parents=True, exist_ok=True)
THUMBS_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = DATA_DIR / "wedge.db"

IMG_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".tif", ".tiff", ".bmp"}
VIDEO_EXT = {".mp4", ".mov", ".webm", ".mkv", ".m4v", ".avi"}
MEDIA_EXT = IMG_EXT | VIDEO_EXT
PLAN_EXT = {".jpg", ".jpeg", ".png", ".webp", ".svg", ".gif"}

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slug TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    photos_path TEXT NOT NULL,
    plans_path TEXT NOT NULL,
    view_password_hash TEXT NOT NULL,
    edit_password_hash TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS media (
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'image',
    status TEXT NOT NULL DEFAULT 'unplaced',
    plan TEXT,
    x REAL,
    y REAL,
    angle REAL,
    fov REAL DEFAULT 60,
    note TEXT,
    taken_at TEXT,
    updated_at TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (project_id, name)
);
CREATE TABLE IF NOT EXISTS seen (
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    first_seen TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (project_id, name)
);
CREATE TABLE IF NOT EXISTS tag_types (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    color TEXT DEFAULT '#888',
    UNIQUE(project_id, name)
);
CREATE TABLE IF NOT EXISTS tags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    type_id INTEGER NOT NULL REFERENCES tag_types(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    UNIQUE(type_id, name)
);
CREATE TABLE IF NOT EXISTS media_tags (
    project_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    tag_id INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    PRIMARY KEY (project_id, name, tag_id),
    FOREIGN KEY (project_id, name) REFERENCES media(project_id, name) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS media_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    text TEXT NOT NULL,
    x REAL,
    y REAL,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (project_id, name) REFERENCES media(project_id, name) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_media_notes_media ON media_notes(project_id, name);
"""


def init_db():
    # Remove the pre-rename DB file if a fresh install left one behind.
    legacy_db = DATA_DIR / "fotoplan.db"
    if legacy_db.exists():
        try:
            legacy_db.unlink()
        except Exception:
            pass
    with db() as c:
        has_projects = c.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='projects'"
        ).fetchone()
        if not has_projects:
            # Wipe any legacy single-project tables so we start clean.
            for legacy in ("photos", "photo_tags", "seen", "tags", "tag_types"):
                c.execute(f"DROP TABLE IF EXISTS {legacy}")
            # also clean stale thumb files at the top level (from older builds)
            if THUMBS_DIR.exists():
                for f in THUMBS_DIR.iterdir():
                    if f.is_file():
                        try:
                            f.unlink()
                        except Exception:
                            pass
        c.executescript(SCHEMA)
        c.commit()


init_db()


# ---------------------------------------------------------------------------
# helpers


EXIF_DATE_TAGS = {"DateTimeOriginal", "DateTimeDigitized", "DateTime"}
_FILENAME_RE = re.compile(
    r"(20\d{2})[-_]?(\d{2})[-_]?(\d{2})[ _\-T]?(\d{2})[-_:]?(\d{2})[-_:]?(\d{2})?"
)


def extract_taken_at_image(path: Path) -> Optional[str]:
    try:
        with Image.open(path) as im:
            exif = im._getexif() or {}
            tagmap = {ExifTags.TAGS.get(k, k): v for k, v in exif.items()}
            for t in ("DateTimeOriginal", "DateTimeDigitized", "DateTime"):
                v = tagmap.get(t)
                if v:
                    try:
                        return datetime.strptime(v, "%Y:%m:%d %H:%M:%S").isoformat()
                    except Exception:
                        pass
    except Exception:
        pass
    return None


def extract_taken_at(path: Path) -> Optional[str]:
    if path.suffix.lower() in IMG_EXT:
        ts = extract_taken_at_image(path)
        if ts:
            return ts
    m = _FILENAME_RE.search(path.name)
    if m:
        y, mo, d, H, M, S = m.groups()
        try:
            return datetime(int(y), int(mo), int(d), int(H), int(M), int(S or 0)).isoformat()
        except Exception:
            pass
    try:
        return datetime.fromtimestamp(path.stat().st_mtime).isoformat()
    except Exception:
        return None


def list_dir(p: Path, exts: set[str]) -> list[str]:
    if not p.exists():
        return []
    out = []
    for f in sorted(p.iterdir()):
        if f.is_file() and f.suffix.lower() in exts:
            out.append(f.name)
    return out


def safe_path(base: Path, name: str) -> Path:
    p = (base / name).resolve()
    base_r = base.resolve()
    if base_r not in p.parents and p != base_r:
        raise HTTPException(400, "invalid path")
    if not p.exists():
        raise HTTPException(404, "not found")
    return p


def media_kind(name: str) -> str:
    ext = Path(name).suffix.lower()
    if ext in VIDEO_EXT:
        return "video"
    return "image"


def project_by_slug(slug: str) -> sqlite3.Row:
    with db() as c:
        r = c.execute("SELECT * FROM projects WHERE slug=?", (slug,)).fetchone()
    if not r:
        raise HTTPException(404, "project not found")
    return r


def project_thumbs_dir(project_id: int) -> Path:
    p = THUMBS_DIR / str(project_id)
    p.mkdir(parents=True, exist_ok=True)
    return p


def sync_media(project: sqlite3.Row) -> set[str]:
    photos_dir = Path(project["photos_path"])
    files = set(list_dir(photos_dir, MEDIA_EXT))
    with db() as c:
        existing = {
            r["name"]: r
            for r in c.execute(
                "SELECT name, taken_at FROM media WHERE project_id=?", (project["id"],)
            )
        }
        for f in files - set(existing):
            ts = extract_taken_at(photos_dir / f)
            c.execute(
                "INSERT INTO media(project_id, name, kind, status, taken_at) VALUES(?, ?, ?, 'unplaced', ?)",
                (project["id"], f, media_kind(f), ts),
            )
            c.execute(
                "INSERT OR IGNORE INTO seen(project_id, name) VALUES(?, ?)",
                (project["id"], f),
            )
        for f in files & set(existing):
            if not existing[f]["taken_at"]:
                ts = extract_taken_at(photos_dir / f)
                if ts:
                    c.execute(
                        "UPDATE media SET taken_at=? WHERE project_id=? AND name=?",
                        (ts, project["id"], f),
                    )
        c.commit()
    return files


def parse_range(range_header: str, file_size: int) -> tuple[int, int]:
    m = re.match(r"bytes=(\d*)-(\d*)", range_header)
    if not m:
        raise HTTPException(416, "invalid range")
    s, e = m.group(1), m.group(2)
    if s == "" and e == "":
        raise HTTPException(416, "invalid range")
    if s == "":
        length = int(e)
        start = max(0, file_size - length)
        end = file_size - 1
    else:
        start = int(s)
        end = int(e) if e else file_size - 1
    end = min(end, file_size - 1)
    if start > end or start < 0:
        raise HTTPException(416, "invalid range")
    return start, end


def serve_file_range(p: Path, request: Request) -> Response:
    file_size = p.stat().st_size
    mt, _ = mimetypes.guess_type(p.name)
    mt = mt or "application/octet-stream"
    range_header = request.headers.get("range")
    if not range_header:
        return FileResponse(
            p,
            media_type=mt,
            headers={"Accept-Ranges": "bytes"},
        )
    start, end = parse_range(range_header, file_size)
    length = end - start + 1

    def chunker(chunk_size: int = 64 * 1024):
        with open(p, "rb") as f:
            f.seek(start)
            remaining = length
            while remaining > 0:
                data = f.read(min(chunk_size, remaining))
                if not data:
                    break
                remaining -= len(data)
                yield data

    return StreamingResponse(
        chunker(),
        status_code=206,
        media_type=mt,
        headers={
            "Content-Range": f"bytes {start}-{end}/{file_size}",
            "Accept-Ranges": "bytes",
            "Content-Length": str(length),
        },
    )


def make_image_thumb(src: Path, dst: Path) -> bool:
    try:
        with Image.open(src) as im:
            im = ImageOps.exif_transpose(im)
            im.thumbnail((256, 256))
            im = im.convert("RGB")
            im.save(dst, "JPEG", quality=80)
        return True
    except Exception:
        return False


def make_video_thumb(src: Path, dst: Path) -> bool:
    try:
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-ss",
                "00:00:01",
                "-i",
                str(src),
                "-frames:v",
                "1",
                "-vf",
                "scale=256:-2",
                "-q:v",
                "5",
                str(dst),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=20,
        )
        return dst.exists() and dst.stat().st_size > 0
    except Exception:
        return False


def project_for_request(slug: str, need: str, request: Request) -> sqlite3.Row:
    project = project_by_slug(slug)
    require_project_level(request, slug, need)
    return project


# ---------------------------------------------------------------------------
# app

app = FastAPI(root_path=ROOT_PATH)

STATIC_DIR = Path(__file__).parent / "static"


# ----------------------- public / session -----------------------


@app.get("/api/session")
def get_session(request: Request):
    s = load_session(request)
    with db() as c:
        rows = c.execute("SELECT slug, name FROM projects ORDER BY name").fetchall()
    projects = [dict(r) for r in rows]
    return {
        "admin": bool(s.get("admin")),
        "projects": projects,
        "granted": s.get("projects") or {},
    }


# ----------------------- admin auth -----------------------


@app.post("/api/admin/login")
def admin_login(request: Request, response: Response, payload: dict = Body(...)):
    pw = (payload.get("password") or "").strip()
    if not verify_admin_password(pw):
        raise HTTPException(401, "wrong password")
    s = load_session(request)
    s["admin"] = True
    save_session(response, s)
    return {"ok": True}


@app.post("/api/admin/logout")
def admin_logout(request: Request, response: Response):
    s = load_session(request)
    s.pop("admin", None)
    save_session(response, s)
    return {"ok": True}


# ----------------------- admin project mgmt -----------------------


@app.get("/api/admin/projects")
def admin_list_projects(request: Request):
    require_admin(request)
    with db() as c:
        rows = c.execute(
            "SELECT id, slug, name, photos_path, plans_path, created_at FROM projects ORDER BY name"
        ).fetchall()
    return [dict(r) for r in rows]


@app.get("/api/admin/project_dirs")
def admin_list_project_dirs(request: Request):
    """List top-level dirs in PROJECTS_ROOT, flagging which ones have the
    required photos/ and plans/ subfolders."""
    require_admin(request)
    out = []
    if PROJECTS_ROOT.is_dir():
        for d in sorted(PROJECTS_ROOT.iterdir()):
            if not d.is_dir() or d.name.startswith("."):
                continue
            out.append({
                "name": d.name,
                "has_photos": (d / "photos").is_dir(),
                "has_plans": (d / "plans").is_dir(),
            })
    return {"projects_root": str(PROJECTS_ROOT), "dirs": out}


@app.post("/api/admin/projects")
def admin_create_project(request: Request, payload: dict = Body(...)):
    require_admin(request)
    slug = (payload.get("slug") or "").strip().lower()
    name = (payload.get("name") or "").strip()
    root_name = (payload.get("root") or "").strip()
    view_password = payload.get("view_password") or ""
    edit_password = payload.get("edit_password") or ""
    if not SLUG_RE.match(slug):
        raise HTTPException(400, "slug must match [a-z0-9][a-z0-9-]{0,62}")
    if not name:
        raise HTTPException(400, "name required")
    if not root_name:
        raise HTTPException(400, "root required")
    if "/" in root_name or "\\" in root_name or root_name in (".", "..") or root_name.startswith("."):
        raise HTTPException(400, "invalid root name")
    if not view_password or not edit_password:
        raise HTTPException(400, "both passwords required")
    if view_password == edit_password:
        raise HTTPException(400, "view and edit passwords must differ")
    root_p = PROJECTS_ROOT / root_name
    if not root_p.is_dir():
        raise HTTPException(400, f"folder not mounted: {root_p}")
    photos_path = str(root_p / "photos")
    plans_path = str(root_p / "plans")
    if not Path(photos_path).is_dir():
        raise HTTPException(400, f"missing required subfolder: {photos_path}")
    if not Path(plans_path).is_dir():
        raise HTTPException(400, f"missing required subfolder: {plans_path}")
    with db() as c:
        try:
            c.execute(
                """INSERT INTO projects(slug, name, photos_path, plans_path,
                   view_password_hash, edit_password_hash)
                   VALUES(?,?,?,?,?,?)""",
                (
                    slug,
                    name,
                    photos_path,
                    plans_path,
                    hash_password(view_password),
                    hash_password(edit_password),
                ),
            )
            c.commit()
        except sqlite3.IntegrityError:
            raise HTTPException(409, "slug already exists")
    return {"ok": True, "slug": slug}


@app.patch("/api/admin/projects/{slug}")
def admin_update_project(slug: str, request: Request, payload: dict = Body(...)):
    require_admin(request)
    project = project_by_slug(slug)
    fields = {}
    if "name" in payload and payload["name"]:
        fields["name"] = payload["name"].strip()
    if "photos_path" in payload and payload["photos_path"]:
        p = payload["photos_path"].strip()
        if not Path(p).is_dir():
            raise HTTPException(400, f"photos_path not a directory: {p}")
        fields["photos_path"] = p
    if "plans_path" in payload and payload["plans_path"]:
        p = payload["plans_path"].strip()
        if not Path(p).is_dir():
            raise HTTPException(400, f"plans_path not a directory: {p}")
        fields["plans_path"] = p
    if payload.get("view_password"):
        fields["view_password_hash"] = hash_password(payload["view_password"])
    if payload.get("edit_password"):
        fields["edit_password_hash"] = hash_password(payload["edit_password"])
    if not fields:
        return {"ok": True}
    sets = ", ".join(f"{k}=?" for k in fields)
    vals = list(fields.values()) + [project["id"]]
    with db() as c:
        c.execute(f"UPDATE projects SET {sets} WHERE id=?", vals)
        c.commit()
    return {"ok": True}


@app.delete("/api/admin/projects/{slug}")
def admin_delete_project(slug: str, request: Request):
    require_admin(request)
    project = project_by_slug(slug)
    with db() as c:
        c.execute("DELETE FROM projects WHERE id=?", (project["id"],))
        c.commit()
    # also drop the per-project thumb directory
    d = THUMBS_DIR / str(project["id"])
    if d.exists():
        shutil.rmtree(d, ignore_errors=True)
    return {"ok": True}


# ----------------------- per-project login -----------------------


@app.post("/api/projects/{slug}/login")
def project_login(slug: str, request: Request, response: Response, payload: dict = Body(...)):
    project = project_by_slug(slug)
    pw = payload.get("password") or ""
    level: Optional[str] = None
    if verify_password(pw, project["edit_password_hash"]):
        level = "edit"
    elif verify_password(pw, project["view_password_hash"]):
        level = "view"
    if not level:
        raise HTTPException(401, "wrong password")
    s = load_session(request)
    grant_project_access(s, slug, level)
    save_session(response, s)
    return {"level": level}


@app.post("/api/projects/{slug}/logout")
def project_logout(slug: str, request: Request, response: Response):
    s = load_session(request)
    revoke_project_access(s, slug)
    save_session(response, s)
    return {"ok": True}


# ----------------------- project state & media -----------------------


@app.get("/api/projects/{slug}/state")
def project_state(slug: str, request: Request):
    project = project_for_request(slug, "view", request)
    files = sync_media(project)
    plans = list_dir(Path(project["plans_path"]), PLAN_EXT)
    with db() as c:
        rows = [
            dict(r)
            for r in c.execute(
                "SELECT * FROM media WHERE project_id=? ORDER BY name",
                (project["id"],),
            )
        ]
        mt = c.execute(
            "SELECT name, tag_id FROM media_tags WHERE project_id=?",
            (project["id"],),
        ).fetchall()
        notes_rows = c.execute(
            "SELECT id, name, text, x, y FROM media_notes WHERE project_id=? ORDER BY id",
            (project["id"],),
        ).fetchall()
        types = [
            dict(r)
            for r in c.execute(
                "SELECT * FROM tag_types WHERE project_id=? ORDER BY name",
                (project["id"],),
            )
        ]
        type_ids = [t["id"] for t in types]
        tags = []
        if type_ids:
            qmarks = ",".join("?" * len(type_ids))
            tags = [
                dict(r)
                for r in c.execute(
                    f"SELECT * FROM tags WHERE type_id IN ({qmarks}) ORDER BY name",
                    type_ids,
                )
            ]
    tags_by_media: dict[str, list[int]] = {}
    for r in mt:
        tags_by_media.setdefault(r["name"], []).append(r["tag_id"])
    notes_by_media: dict[str, list[dict]] = {}
    for n in notes_rows:
        notes_by_media.setdefault(n["name"], []).append(dict(n))
    for r in rows:
        r["missing"] = r["name"] not in files
        r["tag_ids"] = tags_by_media.get(r["name"], [])
        r["notes"] = notes_by_media.get(r["name"], [])
    granted = require_project_level(request, slug, "view")
    new_unplaced = [r for r in rows if r["status"] == "unplaced" and not r["missing"]]
    return {
        "project": {"slug": project["slug"], "name": project["name"]},
        "level": granted,
        "plans": plans,
        "media": rows,
        "new_count": len(new_unplaced),
        "tag_types": types,
        "tags": tags,
    }


@app.get("/api/projects/{slug}/media/{name}")
def get_media_file(slug: str, name: str, request: Request):
    project = project_for_request(slug, "view", request)
    p = safe_path(Path(project["photos_path"]), name)
    return serve_file_range(p, request)


@app.get("/api/projects/{slug}/thumb/{name}")
def get_thumb(slug: str, name: str, request: Request):
    project = project_for_request(slug, "view", request)
    src = safe_path(Path(project["photos_path"]), name)
    key = hashlib.sha1(f"{name}-{src.stat().st_mtime_ns}".encode()).hexdigest()
    thumbs = project_thumbs_dir(project["id"])
    tp = thumbs / f"{key}.jpg"
    if not tp.exists():
        if media_kind(name) == "video":
            ok = make_video_thumb(src, tp)
        else:
            ok = make_image_thumb(src, tp)
        if not ok:
            return FileResponse(src) if media_kind(name) == "image" else JSONResponse(
                {"error": "no thumb"}, status_code=204
            )
    return FileResponse(tp)


@app.get("/api/projects/{slug}/plan/{name}")
def get_plan(slug: str, name: str, request: Request):
    project = project_for_request(slug, "view", request)
    p = safe_path(Path(project["plans_path"]), name)
    return FileResponse(p)


# ----------------------- per-project mutations -----------------------


@app.post("/api/projects/{slug}/place")
def place(slug: str, request: Request, payload: dict = Body(...)):
    project = project_for_request(slug, "edit", request)
    name = payload.get("name")
    plan = payload.get("plan")
    x = float(payload.get("x"))
    y = float(payload.get("y"))
    angle = float(payload.get("angle", 0))
    fov = float(payload.get("fov", 60))
    if not name or not plan:
        raise HTTPException(400, "name and plan required")
    with db() as c:
        cur = c.execute(
            "SELECT 1 FROM media WHERE project_id=? AND name=?",
            (project["id"], name),
        )
        if not cur.fetchone():
            raise HTTPException(404, "media unknown")
        c.execute(
            """UPDATE media SET status='placed', plan=?, x=?, y=?, angle=?, fov=?,
               updated_at=datetime('now')
               WHERE project_id=? AND name=?""",
            (plan, x, y, angle, fov, project["id"], name),
        )
        c.commit()
    return {"ok": True}


@app.post("/api/projects/{slug}/skip")
def skip(slug: str, request: Request, payload: dict = Body(...)):
    project = project_for_request(slug, "edit", request)
    name = payload.get("name")
    note = payload.get("note")
    with db() as c:
        c.execute(
            """UPDATE media SET status='skipped', plan=NULL, x=NULL, y=NULL, angle=NULL,
               note=?, updated_at=datetime('now')
               WHERE project_id=? AND name=?""",
            (note, project["id"], name),
        )
        c.commit()
    return {"ok": True}


@app.post("/api/projects/{slug}/reset")
def reset(slug: str, request: Request, payload: dict = Body(...)):
    project = project_for_request(slug, "edit", request)
    name = payload.get("name")
    with db() as c:
        c.execute(
            """UPDATE media SET status='unplaced', plan=NULL, x=NULL, y=NULL, angle=NULL,
               note=NULL, updated_at=datetime('now')
               WHERE project_id=? AND name=?""",
            (project["id"], name),
        )
        c.commit()
    return {"ok": True}


# ----------------------- tags -----------------------


@app.post("/api/projects/{slug}/tag_types")
def create_tag_type(slug: str, request: Request, payload: dict = Body(...)):
    project = project_for_request(slug, "edit", request)
    name = (payload.get("name") or "").strip()
    color = payload.get("color") or "#888"
    if not name:
        raise HTTPException(400, "name required")
    with db() as c:
        try:
            cur = c.execute(
                "INSERT INTO tag_types(project_id, name, color) VALUES(?, ?, ?)",
                (project["id"], name, color),
            )
            c.commit()
            return {"id": cur.lastrowid}
        except sqlite3.IntegrityError:
            raise HTTPException(409, "exists")


@app.delete("/api/projects/{slug}/tag_types/{tid}")
def delete_tag_type(slug: str, tid: int, request: Request):
    project = project_for_request(slug, "edit", request)
    with db() as c:
        c.execute(
            "DELETE FROM tag_types WHERE id=? AND project_id=?",
            (tid, project["id"]),
        )
        c.commit()
    return {"ok": True}


@app.post("/api/projects/{slug}/tags")
def create_tag(slug: str, request: Request, payload: dict = Body(...)):
    project = project_for_request(slug, "edit", request)
    type_id = payload.get("type_id")
    name = (payload.get("name") or "").strip()
    if not type_id or not name:
        raise HTTPException(400, "type_id and name required")
    with db() as c:
        # verify the type belongs to this project
        owns = c.execute(
            "SELECT 1 FROM tag_types WHERE id=? AND project_id=?",
            (type_id, project["id"]),
        ).fetchone()
        if not owns:
            raise HTTPException(404, "tag type not found")
        try:
            cur = c.execute(
                "INSERT INTO tags(type_id, name) VALUES(?, ?)", (type_id, name)
            )
            c.commit()
            return {"id": cur.lastrowid}
        except sqlite3.IntegrityError:
            raise HTTPException(409, "exists")


@app.delete("/api/projects/{slug}/tags/{tag_id}")
def delete_tag(slug: str, tag_id: int, request: Request):
    project = project_for_request(slug, "edit", request)
    with db() as c:
        # ensure the tag's type belongs to this project
        owns = c.execute(
            """SELECT 1 FROM tags t JOIN tag_types tt ON tt.id=t.type_id
               WHERE t.id=? AND tt.project_id=?""",
            (tag_id, project["id"]),
        ).fetchone()
        if not owns:
            raise HTTPException(404, "tag not found")
        c.execute("DELETE FROM tags WHERE id=?", (tag_id,))
        c.commit()
    return {"ok": True}


@app.post("/api/projects/{slug}/media_tags")
def set_media_tags(slug: str, request: Request, payload: dict = Body(...)):
    project = project_for_request(slug, "edit", request)
    name = payload.get("name")
    tag_ids = payload.get("tag_ids") or []
    if not name:
        raise HTTPException(400, "name required")
    with db() as c:
        owns = c.execute(
            "SELECT 1 FROM media WHERE project_id=? AND name=?",
            (project["id"], name),
        ).fetchone()
        if not owns:
            raise HTTPException(404, "media unknown")
        c.execute(
            "DELETE FROM media_tags WHERE project_id=? AND name=?",
            (project["id"], name),
        )
        for tid in tag_ids:
            # accept only tags of this project's tag_types
            ok = c.execute(
                """SELECT 1 FROM tags t JOIN tag_types tt ON tt.id=t.type_id
                   WHERE t.id=? AND tt.project_id=?""",
                (tid, project["id"]),
            ).fetchone()
            if ok:
                c.execute(
                    "INSERT OR IGNORE INTO media_tags(project_id, name, tag_id) VALUES(?, ?, ?)",
                    (project["id"], name, tid),
                )
        c.commit()
    return {"ok": True}


# ----------------------- notes -----------------------


def _validate_xy(payload: dict) -> tuple[Optional[float], Optional[float]]:
    """Return (x, y) as floats in [0, 1] or (None, None) if both absent/null."""
    x = payload.get("x")
    y = payload.get("y")
    if x is None and y is None:
        return None, None
    try:
        x = float(x)
        y = float(y)
    except (TypeError, ValueError):
        raise HTTPException(400, "x and y must be numbers")
    if not (0 <= x <= 1 and 0 <= y <= 1):
        raise HTTPException(400, "x and y must be in [0, 1]")
    return x, y


@app.post("/api/projects/{slug}/notes")
def create_note(slug: str, request: Request, payload: dict = Body(...)):
    project = project_for_request(slug, "edit", request)
    name = payload.get("name")
    text = (payload.get("text") or "").strip()
    if not name or not text:
        raise HTTPException(400, "name and text required")
    x, y = _validate_xy(payload)
    with db() as c:
        owns = c.execute(
            "SELECT 1 FROM media WHERE project_id=? AND name=?",
            (project["id"], name),
        ).fetchone()
        if not owns:
            raise HTTPException(404, "media unknown")
        cur = c.execute(
            "INSERT INTO media_notes(project_id, name, text, x, y) VALUES(?, ?, ?, ?, ?)",
            (project["id"], name, text, x, y),
        )
        c.commit()
        return {"id": cur.lastrowid}


@app.patch("/api/projects/{slug}/notes/{note_id}")
def update_note(slug: str, note_id: int, request: Request, payload: dict = Body(...)):
    project = project_for_request(slug, "edit", request)
    fields: dict = {}
    if "text" in payload:
        t = (payload.get("text") or "").strip()
        if not t:
            raise HTTPException(400, "text required")
        fields["text"] = t
    if "x" in payload or "y" in payload:
        x, y = _validate_xy(payload)
        fields["x"] = x
        fields["y"] = y
    if not fields:
        return {"ok": True}
    fields["updated_at"] = datetime.now().isoformat()
    sets = ", ".join(f"{k}=?" for k in fields)
    vals = list(fields.values()) + [note_id, project["id"]]
    with db() as c:
        cur = c.execute(
            f"UPDATE media_notes SET {sets} WHERE id=? AND project_id=?", vals
        )
        c.commit()
    if cur.rowcount == 0:
        raise HTTPException(404, "note not found")
    return {"ok": True}


@app.delete("/api/projects/{slug}/notes/{note_id}")
def delete_note(slug: str, note_id: int, request: Request):
    project = project_for_request(slug, "edit", request)
    with db() as c:
        c.execute(
            "DELETE FROM media_notes WHERE id=? AND project_id=?",
            (note_id, project["id"]),
        )
        c.commit()
    return {"ok": True}


# ----------------------- HTML pages -----------------------


def _serve_html(filename: str):
    return FileResponse(STATIC_DIR / filename, media_type="text/html")


@app.get("/")
def page_index():
    return _serve_html("index.html")


@app.get("/admin")
def page_admin():
    return _serve_html("admin.html")


@app.get("/p/{slug}")
def page_project(slug: str):
    # the JS will check session and either redirect to login or load the editor
    return _serve_html("app.html")


@app.get("/p/{slug}/login")
def page_project_login(slug: str):
    return _serve_html("login.html")


# Static assets last (won't shadow the routes above because mount is on /static)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
