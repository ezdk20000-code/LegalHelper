# -*- coding: utf-8 -*-
"""
Проверка и загрузка обновлений LegalHelper с GitHub (без интерфейса).

Ветка main — всегда выпущенная версия (работа идёт в других ветках и попадает в main при выпуске).
Программа читает version.json из main и, если версия там новее установленной, скачивает архив
ветки main — в нём есть update.bat, который собирает и ставит программу.
"""
import json
import os
import shutil
import tempfile
import time
import urllib.parse
import urllib.request
import zipfile

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


# Откуда брать архив новой версии — по очереди, пока не получится. У части провайдеров github.com
# отвечает медленно, поэтому первым идёт прямой адрес codeload, последним — сборка архива по файлам
# с raw.githubusercontent.com (тот же сервер, с которого читается version.json).
ZIP_URLS = [f"https://codeload.github.com/{REPO}/zip/refs/heads/main",
            f"https://github.com/{REPO}/archive/refs/heads/main.zip"]
RAW_BASE = f"https://raw.githubusercontent.com/{REPO}/main/"
MANIFEST = "manifest.json"
ATTEMPTS = 3


def fetch_info(timeout=15):
    """Сведения о последней версии: {'version', 'notes': [...], 'zip'}. Бросает исключение без интернета."""
    last = None
    for attempt in range(ATTEMPTS):
        try:
            with _open(VERSION_URL, timeout) as r:
                info = json.loads(r.read().decode("utf-8-sig"))
            break
        except Exception as e:                 # сеть моргнула — ещё раз
            last = e
            time.sleep(1 + attempt)
    else:
        raise last
    ver = str(info.get("version", "")).strip()
    if not ver:
        raise ValueError("В version.json на GitHub не указана версия.")
    info["version"] = ver
    notes = info.get("notes") or []
    info["notes"] = [notes] if isinstance(notes, str) else [str(n) for n in notes]
    info.setdefault("zip", ZIP_URLS[0])
    return info


def _fetch(url, dest, progress=None, cancelled=None, timeout=60, base=0, total_hint=0):
    tmp = dest + ".part"
    with _open(url, timeout) as r, open(tmp, "wb") as f:
        total = total_hint or int(r.headers.get("Content-Length") or 0)   # по файлам — общий размер
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
                progress(base + got, total)
    os.replace(tmp, dest)
    return got


def _download_by_files(dest, progress=None, cancelled=None):
    """Запасной путь: скачать файлы новой версии по одному (по manifest.json) и сложить в zip,
    как будто это архив ветки main — дальше обновление идёт обычным путём (update.bat)."""
    with _open(RAW_BASE + MANIFEST, 30) as r:
        files = json.loads(r.read().decode("utf-8-sig"))["files"]
    total = sum(int(f.get("size") or 0) for f in files)
    work = tempfile.mkdtemp(prefix="lh_upd_")
    try:
        got = 0
        with zipfile.ZipFile(dest + ".part", "w", zipfile.ZIP_DEFLATED) as z:
            for f in files:
                path = f["path"]
                local = os.path.join(work, "f")
                url = RAW_BASE + urllib.parse.quote(path)
                for attempt in range(ATTEMPTS):
                    try:
                        n = _fetch(url, local, progress, cancelled, 60, got, total)
                        break
                    except InterruptedError:
                        raise
                    except Exception:
                        if attempt == ATTEMPTS - 1:
                            raise
                        time.sleep(2 * (attempt + 1))
                got += n
                z.write(local, "LegalHelper-main/" + path)
        os.replace(dest + ".part", dest)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return dest


def download(url, dest, progress=None, cancelled=None, timeout=60):
    """Скачать архив новой версии в dest: несколько адресов, по несколько попыток, в конце — по файлам.
    progress(получено, всего или 0); cancelled() -> True прерывает загрузку."""
    urls = [url] + [u for u in ZIP_URLS if u != url]
    errors = []
    for u in urls:
        for attempt in range(2):
            try:
                _fetch(u, dest, progress, cancelled, timeout)
                if zipfile.is_zipfile(dest):
                    return dest
                errors.append(f"{u}: получен не архив")
                break
            except InterruptedError:
                raise
            except Exception as e:
                errors.append(f"{u.split('/')[2]}: {e}")
                time.sleep(2 * (attempt + 1))
    try:
        return _download_by_files(dest, progress, cancelled)
    except InterruptedError:
        raise
    except Exception as e:
        errors.append(f"по файлам: {e}")
    raise ConnectionError("Не удалось скачать обновление ни одним способом:\n" + "\n".join(errors[-4:]))
