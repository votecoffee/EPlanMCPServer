from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

SUPPORTED = {".dwg", ".dxf", ".dwt", ".dws", ".pdf"}


def inside(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


@dataclass(frozen=True)
class Config:
    roots: dict[str, Path]
    state: Path
    oda_executable: Path | None = None
    max_file_bytes: int = 268_435_456
    worker_timeout: int = 120
    max_entities: int = 500_000
    max_pages: int = 2000
    max_concurrent_requests: int = 4
    max_queued_requests: int = 32
    max_worker_processes: int = 4
    max_oda_processes: int = 1
    lock_timeout_seconds: int = 180

    @classmethod
    def load(cls, filename: str | Path) -> Config:
        filename = Path(filename).resolve(strict=True)
        raw = json.loads(filename.read_text(encoding="utf-8-sig"))
        roots = {name: Path(value).resolve(strict=True) for name, value in raw["roots"].items()}
        if not roots or any(
            not name or "/" in name or "\\" in name or not p.is_dir() for name, p in roots.items()
        ):
            raise ValueError("Configure named existing source directories")
        state = Path(raw.get("state_dir", filename.parent / "state")).resolve()
        if any(inside(state, root) or inside(root, state) for root in roots.values()):
            raise ValueError("State and source roots must not overlap")
        oda = raw.get("oda_executable")
        if not oda and os.name == "nt":
            candidates = sorted(Path("C:/Program Files/ODA").glob("ODAFileConverter*/ODAFileConverter.exe"))
            oda = str(candidates[-1]) if candidates else None
        executable = Path(oda).resolve(strict=True) if oda else None
        if executable and (not executable.is_file() or not Path(oda).is_absolute()):
            raise ValueError("ODA executable must be an absolute installed file path")
        concurrency = {}
        for key, default, low, high in (
            ("max_concurrent_requests", 4, 1, 32),
            ("max_queued_requests", 32, 0, 1024),
            ("max_worker_processes", 4, 1, 16),
            ("max_oda_processes", 1, 1, 4),
            ("lock_timeout_seconds", 180, 1, 600),
        ):
            value = raw.get(key, default)
            if type(value) is not int or not low <= value <= high:
                raise ValueError(f"{key} must be an integer in {low}..{high}")
            concurrency[key] = value
        return cls(roots, state, executable, **concurrency)

    def resolve(self, root_id: str, relative_path: str) -> Path:
        if root_id not in self.roots:
            raise ValueError("Unknown root_id; call eplan_status")
        relative = Path(relative_path)
        if relative.is_absolute() or relative.drive or ":" in relative_path:
            raise ValueError("Supply a path relative to the named root")
        candidate = Path(os.path.abspath(self.roots[root_id] / relative))
        if not inside(candidate, self.roots[root_id]):
            raise ValueError("Source is outside the named root")
        result = candidate.resolve(strict=True)
        if not inside(result, self.roots[root_id]) or not result.is_file():
            raise ValueError("Source is outside the named root or is not a file")
        if result.stat().st_size > self.max_file_bytes:
            raise ValueError("File exceeds configured byte limit")
        return result

    def files(self, root_id: str) -> list[dict]:
        if root_id not in self.roots:
            raise ValueError("Unknown root_id")
        root = self.roots[root_id]
        result = []
        for folder, dirs, files in os.walk(root, followlinks=False):
            dirs[:] = sorted(
                d
                for d in dirs
                if not Path(folder, d).is_symlink()
                and not getattr(Path(folder, d), "is_junction", lambda: False)()
            )
            for name in sorted(files):
                path = Path(folder, name)
                if not inside(path.resolve(), root) or path.is_symlink():
                    continue
                stat = path.stat()
                result.append(
                    {
                        "root_id": root_id,
                        "relative_path": path.relative_to(root).as_posix(),
                        "extension": path.suffix.lower(),
                        "size_bytes": stat.st_size,
                        "mtime_ns": stat.st_mtime_ns,
                        "supported": path.suffix.lower() in SUPPORTED,
                    }
                )
                if len(result) > 100_000:
                    raise ValueError("Inventory exceeds 100000 files; configure smaller roots")
        return sorted(result, key=lambda row: row["relative_path"].casefold())
