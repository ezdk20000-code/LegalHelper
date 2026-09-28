# -*- coding: utf-8 -*-
"""
Резервные копии данных LegalHelper (без интерфейса).

В копию входит всё, что программа хранит сама: база дел (сроки, заметки, документы, расчёты, карты,
нормы), настройки и реквизиты, свои шаблоны. Сами файлы документов лежат в папках дел — их копирует
пользователь вместе с папкой (см. casefile.py).

Копии — zip-архивы в «Документы/LegalHelper/Резервные копии»: вне папки программы, чтобы их не задело
ни обновление, ни переустановка. Внутри — manifest.json с датой, причиной и числом дел.
"""
import datetime as dt
import json
import os
import shutil
import sqlite3
import tempfile
import zipfile
from pathlib import Path

KEEP = 30                      # сколько последних копий хранить
DAILY_HOURS = 20               # автокопия при запуске, если последней больше стольких часов
DB_NAME = "cases.sqlite"
SETTINGS_NAME = "settings.ini"
TEMPLATES_DIR = "Шаблоны"
MANIFEST = "manifest.json"

REASONS = {"auto": "ежедневная", "manual": "вручную", "update": "перед обновлением",
           "restore": "перед восстановлением", "delete": "перед удалением дела", "import": "перед загрузкой дела"}


def backups_dir():
    d = Path.home() / "Documents" / "LegalHelper" / "Резервные копии"
    d.mkdir(parents=True, exist_ok=True)
    return str(d)


def check_db(path):
    """True — база цела (или её ещё нет). Быстрая проверка SQLite (PRAGMA quick_check)."""
    if not os.path.exists(path):
        return True
    for attempt in range(3):
        try:
            con = sqlite3.connect(path, timeout=5)
            try:
                ok = con.execute("PRAGMA quick_check").fetchone()[0] == "ok"
                con.execute("SELECT count(*) FROM cases").fetchone()
                return ok
            finally:
                con.close()
        except sqlite3.OperationalError as e:
            if "locked" in str(e) or "busy" in str(e):       # занята другой операцией — это не порча
                import time
                time.sleep(0.5)
                continue
            return False
        except sqlite3.Error:
            return False
    return True


def _count_cases(db_path):
    try:
        con = sqlite3.connect(db_path)
        try:
            return con.execute("SELECT count(*) FROM cases").fetchone()[0]
        finally:
            con.close()
    except sqlite3.Error:
        return None


def make_backup(data_dir, reason="auto", version=""):
    """Сделать копию. Базу копируем средствами SQLite — копия целая, даже если программа с ней работает."""
    db_path = os.path.join(data_dir, DB_NAME)
    stamp = dt.datetime.now()
    name = f"LegalHelper {stamp:%Y-%m-%d %H-%M-%S} ({REASONS.get(reason, reason)}).zip"
    out = os.path.join(backups_dir(), name)
    tmp = tempfile.mkdtemp(prefix="lh_backup_")
    try:
        cases = None
        with zipfile.ZipFile(out + ".part", "w", zipfile.ZIP_DEFLATED) as z:
            if os.path.exists(db_path):
                snap = os.path.join(tmp, DB_NAME)
                src = sqlite3.connect(db_path)
                dst = sqlite3.connect(snap)
                try:
                    src.backup(dst)
                finally:
                    dst.close()
                    src.close()
                cases = _count_cases(snap)
                z.write(snap, DB_NAME)
            st = os.path.join(data_dir, SETTINGS_NAME)
            if os.path.exists(st):
                z.write(st, SETTINGS_NAME)
            tdir = os.path.join(data_dir, TEMPLATES_DIR)
            for root, _dirs, files in os.walk(tdir):
                for fn in files:
                    full = os.path.join(root, fn)
                    z.write(full, os.path.relpath(full, data_dir))
            z.writestr(MANIFEST, json.dumps({"created": stamp.isoformat(timespec="seconds"), "reason": reason,
                                             "version": version, "cases": cases}, ensure_ascii=False, indent=1))
        os.replace(out + ".part", out)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    prune()
    return out


def list_backups():
    """Копии от новых к старым: [{path, created (datetime), reason, reason_text, version, cases, size}]."""
    out = []
    for fn in os.listdir(backups_dir()):
        if not fn.lower().endswith(".zip"):
            continue
        p = os.path.join(backups_dir(), fn)
        try:
            with zipfile.ZipFile(p) as z:
                m = json.loads(z.read(MANIFEST).decode("utf-8"))
            created = dt.datetime.fromisoformat(m["created"])
        except Exception:
            continue                                   # не наша или повреждённая — не показываем
        reason = m.get("reason", "")
        out.append({"path": p, "created": created, "reason": reason, "reason_text": REASONS.get(reason, reason),
                    "version": m.get("version", ""), "cases": m.get("cases"), "size": os.path.getsize(p)})
    out.sort(key=lambda b: b["created"], reverse=True)
    return out


def prune(keep=KEEP):
    for b in list_backups()[keep:]:
        try:
            os.remove(b["path"])
        except OSError:
            pass


def needs_daily():
    last = next((b for b in list_backups()), None)
    return last is None or dt.datetime.now() - last["created"] > dt.timedelta(hours=DAILY_HOURS)


def backup_is_valid(path):
    """В архиве есть целая база."""
    tmp = tempfile.mkdtemp(prefix="lh_check_")
    try:
        with zipfile.ZipFile(path) as z:
            if DB_NAME not in z.namelist():
                return False
            z.extract(DB_NAME, tmp)
        return check_db(os.path.join(tmp, DB_NAME))
    except Exception:
        return False
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def restore(path, data_dir, version=""):
    """Вернуть данные из копии. Сначала сохраняет текущее состояние (его тоже можно будет вернуть).
    База должна быть закрыта. Возвращает путь к копии «перед восстановлением» (или None)."""
    if not backup_is_valid(path):
        raise ValueError("Эта резервная копия повреждена — выберите другую.")
    safety = None
    try:
        safety = make_backup(data_dir, "restore", version)
    except Exception:
        pass                                           # текущая база может быть повреждена — это не повод не восстанавливать
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        tmp = tempfile.mkdtemp(prefix="lh_restore_")
        try:
            z.extractall(tmp)
            os.replace(os.path.join(tmp, DB_NAME), os.path.join(data_dir, DB_NAME))
            for extra in ("-wal", "-shm", "-journal"):
                try:
                    os.remove(os.path.join(data_dir, DB_NAME + extra))
                except OSError:
                    pass
            if SETTINGS_NAME in names:
                shutil.copy2(os.path.join(tmp, SETTINGS_NAME), os.path.join(data_dir, SETTINGS_NAME))
            src_t = os.path.join(tmp, TEMPLATES_DIR)
            if os.path.isdir(src_t):
                shutil.copytree(src_t, os.path.join(data_dir, TEMPLATES_DIR), dirs_exist_ok=True)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    return safety
