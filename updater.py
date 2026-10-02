# -*- coding: utf-8 -*-
"""
Проверка и загрузка обновлений LegalHelper с GitHub (без интерфейса).

Ветка main — всегда выпущенная версия (работа идёт в других ветках и попадает в main при выпуске).
Программа читает version.json из main и, если версия там новее установленной, скачивает готовый
установщик этой версии (LegalHelper-Setup.exe, его собирает GitHub при выпуске — .github/workflows/release.yml)
и ставит его тихо, с обычной полоской установки. Запасной путь (запуск из исходников, установщик ещё
не собран) — архив ветки main с update.bat, который собирает программу на месте.
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
# Открытое место только для готовых установщиков (без исходного кода): репозиторий сайта и сам сайт.
# Старые адреса (репозиторий с кодом) — запасные, пока код не закрыт.
PUBLIC_REPO = "LegalHelper/legalhelper.github.io"
SITE = "https://legalhelper.github.io/"
VERSION_URL = f"https://raw.githubusercontent.com/{REPO}/main/version.json"
VERSION_URLS = [SITE + "version.json", VERSION_URL]
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
    last, found = None, []
    for attempt in range(ATTEMPTS):
        for url in VERSION_URLS:               # из всех мест берём самую новую версию
            try:
                with _open(url, timeout) as r:
                    found.append(json.loads(r.read().decode("utf-8-sig")))
            except Exception as e:             # сеть моргнула или файла там нет — ещё раз / другое место
                last = e
        if found:
            break
        time.sleep(1 + attempt)
    else:
        raise last
    info = found[0]
    for other in found[1:]:
        if is_newer(str(other.get("version", "")), str(info.get("version", ""))):
            info = other
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


SETUP_URLS = ["https://github.com/" + PUBLIC_REPO + "/releases/download/v{ver}/LegalHelper-Setup.exe",
              "https://github.com/" + REPO + "/releases/download/v{ver}/LegalHelper-Setup.exe"]
SETUP_URL = SETUP_URLS[-1]
SETUP_MIN_SIZE = 20 * 1048576               # меньше — это не установщик (страница ошибки и т. п.)


def setup_url(ver):
    """Адрес установщика: первое место, где он уже выложен (иначе — основное)."""
    for u in SETUP_URLS:
        if _setup_ok(u.format(ver=ver)):
            return u.format(ver=ver)
    return SETUP_URLS[0].format(ver=ver)


def _setup_ok(url, timeout=15):
    try:
        # HEAD к GitHub нельзя: ссылка на файл подписана для GET. Берём первые 2 байта и смотрим полный размер
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Range": "bytes=0-1"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            head = r.read(2)
            size = (r.headers.get("Content-Range") or "").rpartition("/")[2]
            size = int(size) if size.isdigit() else int(r.headers.get("Content-Length") or 0)
            return r.status in (200, 206) and head == b"MZ" and size >= SETUP_MIN_SIZE
    except Exception:
        return False


def setup_available(ver, timeout=15):
    """Готов ли установщик этой версии (в любом из мест). GitHub собирает его 10–15 минут после выпуска."""
    return any(_setup_ok(u.format(ver=ver), timeout) for u in SETUP_URLS)


def download_setup(ver, dest, progress=None, cancelled=None, timeout=60):
    """Скачать установщик версии ver в dest (с повторами). Проверяет, что это действительно программа Windows."""
    errors = []
    url = setup_url(ver)
    for attempt in range(ATTEMPTS):
        try:
            _fetch(url, dest, progress, cancelled, timeout)
            with open(dest, "rb") as f:
                head = f.read(2)
            if head == b"MZ" and os.path.getsize(dest) >= SETUP_MIN_SIZE:
                return dest
            errors.append("получен не установщик")
        except InterruptedError:
            raise
        except Exception as e:
            errors.append(str(e))
        time.sleep(2 * (attempt + 1))
    raise ConnectionError("Не удалось скачать установщик:\n" + "\n".join(errors[-3:]))


CHANGELOG_URL = f"https://raw.githubusercontent.com/{REPO}/main/CHANGELOG.md"
CHANGELOG_URLS = [SITE + "CHANGELOG.md", CHANGELOG_URL]


def parse_changelog(text, since=None):
    """CHANGELOG.md -> [(версия, заголовок, [пункты])], только версии новее since (если указана).
    Пункт — строка «- …»; строки с отступом продолжают предыдущий пункт."""
    out, cur = [], None
    for line in text.splitlines():
        if line.startswith("## "):
            head = line[3:].strip()
            ver, _, title = head.partition("—")
            ver = ver.strip()
            cur = (ver, title.strip(), [])
            if since is None or is_newer(ver, since):
                out.append(cur)
            else:
                cur = None
        elif cur is not None:
            st = line.strip()
            if line.lstrip().startswith("- ") and not line.startswith("  "):
                cur[2].append(st[2:])
            elif st and cur[2]:
                cur[2][-1] += (" " + st[2:]) if st.startswith("- ") else (" " + st)
    return out


def fetch_changelog(since, timeout=15):
    """Подробные описания всех версий новее установленной (пусто, если не удалось скачать)."""
    best = []
    for url in CHANGELOG_URLS:                 # берём самый полный список из доступных мест
        try:
            with _open(url, timeout) as r:
                got = parse_changelog(r.read().decode("utf-8-sig"), since)
            if len(got) > len(best):
                best = got
        except Exception:
            pass
    return best
