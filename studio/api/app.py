"""FastAPI application: projects, imports, images, tags and splits.

Local-only by design (Development Rule 1): the Host header is checked against an allowlist to
block DNS-rebinding, and there is no CORS. The server reads folders the user names, which is why
it must stay bound to ``127.0.0.1``.
"""

import asyncio
import logging
import shutil
import sqlite3
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from studio import db, importer, paths, repo
from studio.config import load_config
from studio.jobs import JobManager

logger = logging.getLogger(__name__)
WEB_DIR = Path(__file__).resolve().parent.parent / "web"
IMMUTABLE = "public, max-age=31536000, immutable"  # URLs carry the content hash (?v=)


class ProjectCreate(BaseModel):
    name: str


class ImportRequest(BaseModel):
    path: str = Field(min_length=1)


class TagsRequest(BaseModel):
    tags: list[str]


class SetSplitRequest(BaseModel):
    image_ids: list[int]
    split: str | None


class AutoSplitRequest(BaseModel):
    ratios: dict[str, float] | None = None
    seed: int | None = None
    only_unassigned: bool = True


def create_app(
    config: dict[str, Any] | None = None, allowed_hosts: list[str] | None = None
) -> FastAPI:
    """Build the application. ``config`` defaults to ``config.yaml``."""
    config = config if config is not None else load_config()
    database_file = paths.db_path(config)
    with db.connect(database_file) as setup_conn:
        db.migrate(setup_conn)
    jobs = JobManager(keep_finished=config["jobs"]["keep_finished"])

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        yield
        jobs.shutdown()

    app = FastAPI(title="Local Vision Studio", version="0.1.0", lifespan=lifespan)
    app.state.config = config
    app.state.db_path = database_file
    app.state.jobs = jobs
    app.add_middleware(
        TrustedHostMiddleware, allowed_hosts=allowed_hosts or config["app"]["allowed_hosts"]
    )

    def get_conn(request: Request) -> Iterator[sqlite3.Connection]:
        conn = db.connect(request.app.state.db_path)
        try:
            yield conn
        finally:
            conn.close()

    Conn = Depends(get_conn)

    def need_project(conn: sqlite3.Connection, project_id: int) -> dict[str, Any]:
        project = repo.get_project(conn, project_id)
        if project is None:
            raise HTTPException(404, f"Project {project_id} not found.")
        return project

    def image_urls(image: dict[str, Any]) -> dict[str, Any]:
        version = image["sha256"][:12]
        image["thumb_url"] = f"/api/images/{image['id']}/thumb?v={version}"
        image["file_url"] = f"/api/images/{image['id']}/file?v={version}"
        image.pop("stored_name", None)
        return image

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {"status": "ok", "version": app.version}

    @app.get("/api/limits")
    def limits() -> dict[str, Any]:
        """Limits the UI mirrors, so there is one source of truth (config.yaml)."""
        return {
            "project_name_max": config["projects"]["max_name_length"],
            "tag_max_length": config["tags"]["max_length"],
            "tags_per_image": config["tags"]["max_per_image"],
            "page_size": config["gallery"]["default_page_size"],
        }

    # ---- projects ---------------------------------------------------------------------------
    @app.get("/api/projects")
    def list_projects(conn: sqlite3.Connection = Conn) -> list[dict[str, Any]]:
        return repo.list_projects(conn)

    @app.post("/api/projects", status_code=201)
    def create_project(body: ProjectCreate, conn: sqlite3.Connection = Conn) -> dict[str, Any]:
        try:
            name = repo.clean_name(body.name, config["projects"]["max_name_length"])
            project = repo.create_project(conn, name)
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
        except repo.ProjectExists as error:
            raise HTTPException(409, str(error)) from error
        # Row ids can be reused after a delete; never inherit files left over from an old project.
        shutil.rmtree(paths.project_dir(config, project["id"]), ignore_errors=True)
        return project

    @app.get("/api/projects/{project_id}")
    def get_project(project_id: int, conn: sqlite3.Connection = Conn) -> dict[str, Any]:
        return need_project(conn, project_id)

    @app.delete("/api/projects/{project_id}", status_code=204)
    def delete_project(project_id: int, conn: sqlite3.Connection = Conn) -> Response:
        if jobs.has_active(project_id):
            raise HTTPException(
                409, "An import is still running for this project. Cancel it first."
            )
        if not repo.delete_project(conn, config, project_id):
            raise HTTPException(404, f"Project {project_id} not found.")
        if paths.project_dir(config, project_id).exists():
            # The rows are gone but some files could not be removed (for example, still open).
            return JSONResponse(
                {"warning": "The project was deleted, but some of its files could not be removed. "
                 f"You can delete the folder by hand: {paths.project_dir(config, project_id)}"}
            )
        return Response(status_code=204)

    # ---- imports ----------------------------------------------------------------------------
    @app.post("/api/projects/{project_id}/imports", status_code=202)
    def start_import(
        project_id: int, body: ImportRequest, conn: sqlite3.Connection = Conn
    ) -> dict[str, str]:
        need_project(conn, project_id)
        source = Path(body.path).expanduser()
        if not source.exists():
            raise HTTPException(400, f"Source not found: {source}")
        if not (source.is_dir() or source.suffix.lower() == ".zip"):
            raise HTTPException(400, "Choose a folder or a .zip file.")

        def run(progress, cancelled) -> dict[str, Any]:
            job_conn = db.connect(database_file)
            try:
                report = importer.import_source(
                    job_conn,
                    config,
                    project_id,
                    source,
                    progress=lambda done, total, partial: progress(done, total, partial.to_dict()),
                    cancelled=cancelled,
                )
                return report.to_dict()
            finally:
                job_conn.close()

        return {"job_id": jobs.submit(run, kind="import", project_id=project_id)}

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str) -> dict[str, Any]:
        job = jobs.get(job_id)
        if job is None:
            raise HTTPException(404, "Job not found.")
        return job

    @app.post("/api/jobs/{job_id}/cancel", status_code=202)
    def cancel_job(job_id: str) -> dict[str, bool]:
        if jobs.get(job_id) is None:
            raise HTTPException(404, "Job not found.")
        # False means it had already finished, which is fine from the caller's point of view.
        return {"cancel_requested": jobs.cancel(job_id)}

    @app.websocket("/api/jobs/{job_id}/ws")
    async def job_progress(websocket: WebSocket, job_id: str) -> None:
        await websocket.accept()
        poll = config["app"]["job_poll_interval_s"]
        last: dict[str, Any] | None = None
        try:
            while True:
                job = jobs.get(job_id)
                if job is None:
                    await websocket.close(code=4404, reason="Job not found")
                    return
                if job != last:
                    await websocket.send_json(job)
                    last = job
                if job["state"] in ("done", "failed"):
                    await websocket.close()
                    return
                await asyncio.sleep(poll)
        except WebSocketDisconnect:
            return  # the browser went away (tab closed or hidden); nothing to clean up

    @app.get("/api/projects/{project_id}/batches")
    def list_batches(project_id: int, conn: sqlite3.Connection = Conn) -> list[dict[str, Any]]:
        need_project(conn, project_id)
        return repo.list_batches(conn, project_id)

    # ---- images -----------------------------------------------------------------------------
    @app.get("/api/projects/{project_id}/images")
    def list_images(
        project_id: int,
        offset: int = Query(0, ge=0),
        limit: int | None = Query(None, ge=1),
        split: str | None = None,
        tag: str | None = None,
        batch_id: int | None = None,
        q: str | None = None,
        conn: sqlite3.Connection = Conn,
    ) -> dict[str, Any]:
        need_project(conn, project_id)
        gallery = config["gallery"]
        page = min(limit or gallery["default_page_size"], gallery["max_page_size"])
        try:
            items, total = repo.list_images(
                conn,
                project_id,
                offset=offset,
                limit=page,
                split=split,
                tag=tag,
                batch_id=batch_id,
                query=q,
            )
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
        return {
            "items": [image_urls(item) for item in items],
            "total": total,
            "offset": offset,
            "limit": page,
        }

    @app.get("/api/projects/{project_id}/tags")
    def list_tags(project_id: int, conn: sqlite3.Connection = Conn) -> list[dict[str, Any]]:
        need_project(conn, project_id)
        return repo.project_tags(conn, project_id)

    def image_file(conn: sqlite3.Connection, image_id: int, thumb: bool) -> FileResponse:
        image = repo.get_image(conn, image_id)
        if image is None:
            raise HTTPException(404, f"Image {image_id} not found.")
        if thumb:
            path = paths.thumbs_dir(config, image["project_id"]) / f"{image['sha256']}.jpg"
        else:
            path = paths.images_dir(config, image["project_id"]) / image["stored_name"]
        if not path.is_file():
            raise HTTPException(404, "Image file is missing on disk.")
        return FileResponse(path, headers={"Cache-Control": IMMUTABLE})

    @app.get("/api/images/{image_id}")
    def get_image(image_id: int, conn: sqlite3.Connection = Conn) -> dict[str, Any]:
        image = repo.get_image(conn, image_id)
        if image is None:
            raise HTTPException(404, f"Image {image_id} not found.")
        return image_urls(image)

    @app.get("/api/images/{image_id}/thumb")
    def get_thumb(image_id: int, conn: sqlite3.Connection = Conn) -> FileResponse:
        return image_file(conn, image_id, thumb=True)

    @app.get("/api/images/{image_id}/file")
    def get_file(image_id: int, conn: sqlite3.Connection = Conn) -> FileResponse:
        return image_file(conn, image_id, thumb=False)

    @app.put("/api/images/{image_id}/tags")
    def put_tags(
        image_id: int, body: TagsRequest, conn: sqlite3.Connection = Conn
    ) -> dict[str, Any]:
        if repo.get_image(conn, image_id) is None:
            raise HTTPException(404, f"Image {image_id} not found.")
        try:
            tags = repo.clean_tags(
                body.tags, config["tags"]["max_length"], config["tags"]["max_per_image"]
            )
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
        repo.set_tags(conn, image_id, tags)
        return {"tags": tags}

    # ---- splits -----------------------------------------------------------------------------
    @app.put("/api/projects/{project_id}/split")
    def put_split(
        project_id: int, body: SetSplitRequest, conn: sqlite3.Connection = Conn
    ) -> dict[str, Any]:
        need_project(conn, project_id)
        try:
            changed = repo.set_split(conn, project_id, body.image_ids, body.split)
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
        return {"changed": changed}

    @app.post("/api/projects/{project_id}/split/auto")
    def auto_split(
        project_id: int, body: AutoSplitRequest, conn: sqlite3.Connection = Conn
    ) -> dict[str, Any]:
        need_project(conn, project_id)
        defaults = config["splits"]
        ratios = body.ratios if body.ratios is not None else defaults["default_ratios"]
        seed = body.seed if body.seed is not None else defaults["default_seed"]
        try:
            assigned, previous = repo.apply_splits(
                conn, project_id, ratios, seed, body.only_unassigned
            )
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
        counts = need_project(conn, project_id)["split_counts"]
        return {"assigned": assigned, "split_counts": counts, "previous": previous}

    if WEB_DIR.is_dir():
        app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
    return app
