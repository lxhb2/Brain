"""Build portable Markdown bundles that keep text and images together."""
from __future__ import annotations

import datetime as _datetime
import json
import logging
import os
import re
import shutil
import uuid
import zipfile
from typing import Any, Dict, Optional

import database
import ocr_processor
from config import get_config

logger = logging.getLogger("brain.bundle")
_HTML_IMG_RE = re.compile(r"(<img[^>]+src\s*=\s*[\"'])([^\"']+)([\"'][^>]*>)")


def _bundle_base_name(note_id: int, title: Optional[str]) -> str:
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", title or "").strip()
    value = re.sub(r"\s+", "-", value)
    return (value or f"note-{note_id}")[:80].strip(".-")


def _replace_directory(source_dir: str, target_dir: str) -> None:
    backup_dir = target_dir + ".old"
    if os.path.exists(backup_dir):
        shutil.rmtree(backup_dir)
    if os.path.exists(target_dir):
        os.replace(target_dir, backup_dir)
    try:
        os.replace(source_dir, target_dir)
    finally:
        if os.path.exists(backup_dir):
            shutil.rmtree(backup_dir)


def build_markdown_bundle(note_id: int) -> Dict[str, Any]:
    """Create a persistent bundle directory and ZIP for one Markdown note.

    The directory keeps document.md and assets/ readable outside Brain. The ZIP
    is a stable single-file artifact intended for download and cloud backup.
    """
    note = database.get_note(note_id)
    if not note:
        raise ValueError(f"note {note_id} does not exist")

    source_path = os.path.realpath(str(note.get("file_path") or ""))
    if os.path.splitext(source_path)[1].lower() not in (".md", ".markdown"):
        raise ValueError("only Markdown notes can be bundled")
    if not os.path.isfile(source_path):
        raise FileNotFoundError(source_path)

    cfg = get_config()
    root = os.path.abspath(cfg.MARKDOWN_BUNDLE_DIR)
    os.makedirs(root, exist_ok=True)
    work_dir = os.path.join(root, f".note-{note_id}-{uuid.uuid4().hex}")
    temp_zip = os.path.join(root, f".note-{note_id}-{uuid.uuid4().hex}.zip")
    target_dir = os.path.join(root, str(note_id))
    os.makedirs(work_dir, exist_ok=True)
    assets_dir = os.path.join(work_dir, "assets")
    os.makedirs(assets_dir, exist_ok=True)

    try:
        markdown_text = ocr_processor._read_markdown_text(source_path)
        base_dir = os.path.dirname(source_path)
        used_names: set[str] = set()
        image_map: dict[str, str] = {}
        for resolved in ocr_processor.extract_markdown_image_paths(source_path):
            suffix = os.path.splitext(resolved)[1].lower()
            stem = os.path.splitext(os.path.basename(resolved))[0]
            candidate = f"{stem}{suffix}"
            seq = 1
            while candidate.lower() in used_names:
                candidate = f"{stem}-{seq}{suffix}"
                seq += 1
            used_names.add(candidate.lower())
            image_map[resolved] = f"assets/{candidate}"

        def map_markdown_image(match: re.Match[str]) -> str:
            alt, src = match.group(1), match.group(2)
            resolved = os.path.normpath(os.path.join(base_dir, src))
            bundled = image_map.get(resolved)
            return f"![{alt}]({bundled})" if bundled else match.group(0)

        def map_html_image(match: re.Match[str]) -> str:
            before, src, after = match.groups()
            resolved = os.path.normpath(os.path.join(base_dir, src))
            bundled = image_map.get(resolved)
            return f'{before}src="{bundled}"{after}' if bundled else match.group(0)

        portable_markdown = ocr_processor._MD_IMG_RE.sub(map_markdown_image, markdown_text)
        portable_markdown = _HTML_IMG_RE.sub(map_html_image, portable_markdown)
        if note.get("mermaid") and str(note.get("mermaid")).strip():
            portable_markdown += "\n\n## Mermaid 关系图\n\n```mermaid\n"
            portable_markdown += str(note["mermaid"]).strip() + "\n```\n"

        manifest = {
            "format": "brain-markdown-bundle",
            "version": 1,
            "note_id": note_id,
            "title": note.get("title"),
            "created_at": note.get("created_at"),
            "generated_at": _datetime.datetime.now(_datetime.timezone.utc).isoformat(),
            "entrypoint": "document.md",
            "assets": [
                {"bundle_path": bundled, "source_path": source}
                for source, bundled in image_map.items()
            ],
        }
        with open(os.path.join(work_dir, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)
        with open(os.path.join(work_dir, "document.md"), "w", encoding="utf-8") as f:
            f.write(portable_markdown)
        with open(os.path.join(work_dir, "README.txt"), "w", encoding="utf-8") as f:
            f.write(
                "This Brain Markdown bundle contains document.md and its referenced "
                "images.\nOpen document.md to keep the text and images together.\n"
            )
        for resolved, bundled in image_map.items():
            shutil.copy2(resolved, os.path.join(work_dir, *bundled.split("/")))

        base_name = _bundle_base_name(note_id, note.get("title"))
        archive_name = f"{base_name}-markdown-bundle.zip"
        with zipfile.ZipFile(temp_zip, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
            for filename in ("manifest.json", "document.md", "README.txt"):
                bundle.write(os.path.join(work_dir, filename), filename)
            for resolved, bundled in image_map.items():
                bundle.write(resolved, bundled)
        os.replace(temp_zip, os.path.join(work_dir, archive_name))

        _replace_directory(work_dir, target_dir)
        return {
            "note_id": note_id,
            "directory": target_dir,
            "archive": os.path.join(target_dir, archive_name),
            "document": os.path.join(target_dir, "document.md"),
            "image_count": len(image_map),
        }
    except Exception:
        shutil.rmtree(temp_zip, ignore_errors=True)
        shutil.rmtree(work_dir, ignore_errors=True)
        raise
