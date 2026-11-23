"""Project folders: create / open / copy / delete / export as ZIP / import from ZIP."""
from __future__ import annotations

import json
import shutil
import uuid
import zipfile
from datetime import datetime
from pathlib import Path

import numpy as np
from PIL import Image

from config import settings
from models.data_models import ProjectState
from .database import Database


def _save_png(arr: np.ndarray, path: Path) -> None:
    Image.fromarray(arr).save(path)


def _load_png(path: Path) -> np.ndarray | None:
    return np.asarray(Image.open(path).convert("RGB")) if path.exists() else None


class ProjectManager:
    def __init__(self, db: Database | None = None, root: Path | None = None):
        settings.ensure_dirs()
        self.db = db or Database()
        self.root = Path(root or settings.PROJECT_DIR)
        self.root.mkdir(parents=True, exist_ok=True)

    def folder(self, pid: str) -> Path:
        return self.root / pid

    # ----------------------------------------------------------------- create / save
    def create(self, state: ProjectState, original: np.ndarray, processed: np.ndarray, source_name: str | None = None,
               source_bytes: bytes | None = None) -> ProjectState:
        f = self.folder(state.project_id)
        (f / "outputs").mkdir(parents=True, exist_ok=True)
        _save_png(original, f / "original.png")
        _save_png(processed, f / "processed.png")
        if source_bytes and source_name:
            (f / ("source_" + Path(source_name).name)).write_bytes(source_bytes)
        self.save(state, "created")
        return state

    def save(self, state: ProjectState, event: str | None = None) -> None:
        state.touch()
        f = self.folder(state.project_id)
        f.mkdir(parents=True, exist_ok=True)
        (f / "project.json").write_text(state.to_json(indent=1), encoding="utf-8")
        (f / "settings.json").write_text(json.dumps(state.settings, indent=1, ensure_ascii=False), encoding="utf-8")
        ch = state.chart
        self.db.upsert_project(dict(
            id=state.project_id, name=state.name, created=state.created, updated=state.updated, image_name=state.image_meta.get("name"),
            chart_type=ch.chart_type if ch else None, n_series=sum(len(c.series) for c in state.charts),
            n_points=sum(len(s.points) for c in state.charts for s in c.series),
            quality=(ch.quality.get("overall") if ch and ch.quality else None), folder=str(f), is_sample=int(state.is_sample), notes=None,
            n_charts=len(state.charts),
            n_fits=sum(len(((a.get('fits') or {}).get('models')) or []) for c in state.charts for a in (c.analysis.get('series', {}) or {}).values())))
        if event:
            self.db.add_event(state.project_id, event)

    def update_images(self, pid: str, original: np.ndarray | None, processed: np.ndarray | None) -> None:
        f = self.folder(pid)
        if original is not None:
            _save_png(original, f / "original.png")
        if processed is not None:
            _save_png(processed, f / "processed.png")

    # ------------------------------------------------------------------------ open
    def open(self, pid: str):
        f = self.folder(pid)
        pj = f / "project.json"
        if not pj.exists():
            raise FileNotFoundError(f"Project {pid} not found")
        state = ProjectState.from_json(pj.read_text(encoding="utf-8"))
        return state, _load_png(f / "original.png"), _load_png(f / "processed.png")

    def outputs_dir(self, pid: str) -> Path:
        d = self.folder(pid) / "outputs"
        d.mkdir(parents=True, exist_ok=True)
        return d

    # --------------------------------------------------------------- copy / delete
    def copy(self, pid: str, new_name: str | None = None) -> str:
        state, orig, proc = self.open(pid)
        new_id = uuid.uuid4().hex[:12]
        src, dst = self.folder(pid), self.folder(new_id)
        shutil.copytree(src, dst, ignore=shutil.ignore_patterns("outputs"))
        (dst / "outputs").mkdir(exist_ok=True)
        state.project_id = new_id
        state.name = new_name or f"{state.name} (copy)"
        state.created = datetime.now().isoformat(timespec="seconds")
        self.save(state, f"copied from {pid}")
        return new_id

    def delete(self, pid: str) -> None:
        shutil.rmtree(self.folder(pid), ignore_errors=True)
        self.db.delete_project(pid)

    # ---------------------------------------------------------------- zip export / import
    def export_zip(self, pid: str, zip_path: Path) -> str:
        f = self.folder(pid)
        zip_path = Path(zip_path)
        zip_path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
            for p in f.rglob("*"):
                if p.is_file():
                    z.write(p, arcname=str(p.relative_to(f)))
        return str(zip_path)

    def import_zip(self, zip_path: Path) -> str:
        """Restore a project exported with export_zip (safe against path traversal)."""
        with zipfile.ZipFile(zip_path) as z:
            names = z.namelist()
            if "project.json" not in names:
                raise ValueError("The ZIP file does not contain a GraphInsight project (project.json missing).")
            data = json.loads(z.read("project.json").decode("utf-8"))
            if data.get("format") != "graphinsight-project":
                raise ValueError("Unsupported project file.")
            new_id = uuid.uuid4().hex[:12]
            dst = self.folder(new_id)
            dst.mkdir(parents=True, exist_ok=True)
            base = dst.resolve()
            for n in names:
                target = (dst / n).resolve()
                if base not in target.parents and target != base:
                    raise ValueError(f"Unsafe path in ZIP: {n}")
                if n.endswith("/"):
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(z.read(n))
        state = ProjectState.from_json((dst / "project.json").read_text(encoding="utf-8"))
        state.project_id = new_id
        (dst / "outputs").mkdir(exist_ok=True)
        self.save(state, "imported from ZIP")
        return new_id

    def list(self, search: str | None = None) -> list[dict]:
        return self.db.list_projects(search)
