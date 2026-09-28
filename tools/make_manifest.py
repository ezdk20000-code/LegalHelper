# -*- coding: utf-8 -*-
"""Список файлов версии для запасного способа обновления (updater._download_by_files).
Запускать перед выпуском: python tools/make_manifest.py  → manifest.json в корне репозитория."""
import json
import os
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
files = subprocess.run(["git", "-c", "core.quotepath=off", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.splitlines()
skip = ("manifest.json", ".gitignore", ".gitattributes", "CLAUDE.md")
out = [{"path": f, "size": os.path.getsize(os.path.join(ROOT, f))} for f in files
       if f not in skip and not f.startswith("tools/") and os.path.isfile(os.path.join(ROOT, f))]
with open(os.path.join(ROOT, "manifest.json"), "w", encoding="utf-8") as fh:
    json.dump({"files": out}, fh, ensure_ascii=False, indent=0)
print(len(out), "files,", sum(f["size"] for f in out) // 1024, "KB")
