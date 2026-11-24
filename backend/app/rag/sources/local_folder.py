"""DocumentSource over a local folder. File id = path relative to the folder (posix style); checksum = SHA-256 of the bytes."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

from app.rag.base import SourceFile
from app.rag.parsers import mime_for_name


class LocalFolderSource:
    name = "local"
    SYNTHETIC_PREFIX = "SYNTHETIC_"  # placeholder documents shipped with the repo; their facts are invented

    def __init__(self, root: Path, *, include_synthetic: bool = False) -> None:
        """include_synthetic=False (the default) keeps SYNTHETIC_* placeholders out of the index, so a real deployment can
        never answer from invented dates or rules. The synthetic evaluation set opts in (and uses its own collection)."""
        self._root = root
        self._include_synthetic = include_synthetic

    def list_files(self) -> list[SourceFile]:
        if not self._root.is_dir():
            raise FileNotFoundError(f"documents folder not found: {self._root.name}")
        files: list[SourceFile] = []
        for path in sorted(self._root.rglob("*")):
            relative = path.relative_to(self._root)
            hidden = any(part.startswith((".", "~$")) for part in relative.parts)
            if not path.is_file() or hidden:
                continue
            if not self._include_synthetic and path.name.startswith(self.SYNTHETIC_PREFIX):
                continue
            stat = path.stat()
            files.append(SourceFile(
                source_file_id=relative.as_posix(),
                name=path.name,
                mime_type=mime_for_name(path.name),
                modified_time=datetime.fromtimestamp(stat.st_mtime, tz=UTC),
                remote_checksum=self._sha256(path),
            ))
        return files

    def fetch(self, file: SourceFile) -> tuple[bytes, str]:
        target = (self._root / file.source_file_id).resolve()
        if self._root.resolve() not in target.parents:  # never read outside the folder, whatever the id says
            raise ValueError("file id points outside the documents folder")
        return target.read_bytes(), file.mime_type

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1 << 20), b""):
                digest.update(block)
        return digest.hexdigest()
