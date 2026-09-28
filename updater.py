# -*- coding: utf-8 -*-
"""
Проверка и загрузка обновлений LegalHelper с GitHub (без интерфейса).

Ветка main — всегда выпущенная версия (работа идёт в других ветках и попадает в main при выпуске).
Программа читает version.json из main и, если версия там новее установленной, скачивает архив
ветки main — в нём есть update.bat, который собирает и ставит программу.
"""
import json
import os
import urllib.request

REPO = "ezdk20000-code/LegalHelper"
VERSION_URL = f"https://raw.githubusercontent.com/{REPO}/main/version.json"
USER_AGENT = "LegalHelper-updater"


def parse_version(v):
    """'1.10' -> (1, 10): версии сравниваются по числам, а не как строки."""
    parts = []
    for p in str(v).strip().lstrip("vV").split("."):
        digits = "".join(ch for ch in p if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    while len(parts) > 1 and parts[-1] == 0:
        parts.pop()
    return tuple(parts)


def is_newer(remote, local):
    return parse_version(remote) > parse_version(local)


def _open(url, timeout):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Cache-Control": "no-cache"})
    return urllib.request.urlopen(req, timeout=timeout)


def fetch_info(timeout=10):
    """Сведения о последней версии: {'version', 'notes': [...], 'zip'}. Бросает исключение без интернета."""
    with _open(VERSION_URL, timeout) as r:
        info = json.loads(r.read().decode("utf-8-sig"))
    ver = str(info.get("version", "")).strip()
    if not ver:
        raise ValueError("В version.json на GitHub не указана версия.")
    info["version"] = ver
    notes = info.get("notes") or []
    info["notes"] = [notes] if isinstance(notes, str) else [str(n) for n in notes]
    info.setdefault("zip", f"https://github.com/{REPO}/archive/refs/heads/main.zip")
    return info


def download(url, dest, progress=None, cancelled=None, timeout=30):
    """Скачать файл в dest. progress(получено, всего или 0); cancelled() -> True прерывает загрузку."""
    tmp = dest + ".part"
    with _open(url, timeout) as r, open(tmp, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        got = 0
        while True:
            if cancelled and cancelled():
                raise InterruptedError("Загрузка отменена.")
            chunk = r.read(256 * 1024)
            if not chunk:
                break
            f.write(chunk)
            got += len(chunk)
            if progress:
                progress(got, total)
    os.replace(tmp, dest)
    return dest
