# -*- coding: utf-8 -*-
"""
Переносимая папка дела (без интерфейса).

У каждого дела своя папка (по умолчанию «Документы/LegalHelper/Дела/<название>»). В ней:
    LegalHelper-дело.json — все сведения о деле: карточка, сроки и напоминания, заметки, список документов,
                            учёт времени и оплат, выписки, комплекты для подачи, нормы права, карта дела;
    Документы/            — файлы, собранные в папку дела (кнопкой «Собрать файлы в папку дела»).
Пути к файлам внутри папки хранятся относительными, поэтому папку можно скопировать на флешку и открыть
на другом компьютере: «Файл → Открыть дело из папки…».
"""
import datetime as dt
import json
import os
import re
import shutil
import uuid
from pathlib import Path

CASE_FILE = "LegalHelper-дело.json"
DOCS_SUBDIR = "Документы"
FORMAT = 1
_SKIP = {"id", "case_id"}


def cases_root():
    return str(Path.home() / "Documents" / "LegalHelper" / "Дела")


def clean_name(s):
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]', " ", s or "").strip(" .")
    return re.sub(r"\s+", " ", s)[:80] or "Дело"


def _rel(path, folder):
    """Путь внутри папки дела — относительный (с /), иначе абсолютный."""
    if not path:
        return {"abs": ""}
    try:
        rp = os.path.relpath(os.path.abspath(path), os.path.abspath(folder))
        if not rp.startswith(".."):
            return {"rel": rp.replace("\\", "/")}
    except ValueError:                                  # другой диск в Windows
        pass
    return {"abs": path}


def _unrel(ref, folder):
    if not ref:
        return ""
    if ref.get("rel"):
        return os.path.normpath(os.path.join(folder, ref["rel"]))
    return ref.get("abs", "")


def ensure_uid(db, cid):
    c = db.case(cid)
    if c and not c.get("uid"):
        db.con.execute("UPDATE cases SET uid=? WHERE id=?", (uuid.uuid4().hex, cid))
        db.con.commit()
    return db.case(cid)["uid"]


def ensure_folder(db, cid):
    """Папка дела: указанная в карточке или новая «Документы/LegalHelper/Дела/<название>» (запоминается)."""
    c = db.case(cid)
    if c.get("folder") and os.path.isdir(c["folder"]):
        return c["folder"]
    base = os.path.join(cases_root(), clean_name(c["title"]))
    folder, n = base, 2
    while os.path.exists(folder) and not _is_folder_of(folder, c):
        folder, n = f"{base} ({n})", n + 1
    os.makedirs(folder, exist_ok=True)
    db.update_case(cid, folder=folder)
    return folder


def _is_folder_of(folder, case):
    p = os.path.join(folder, CASE_FILE)
    if not os.path.exists(p):
        return not os.listdir(folder)                    # пустая папка — можно занять
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f).get("case", {}).get("uid") == case.get("uid")
    except Exception:
        return False


def _rows(db, sql, args):
    return [dict(r) for r in db.con.execute(sql, args).fetchall()]


def case_data(db, cid, folder):
    ensure_uid(db, cid)
    c = {k: v for k, v in db.case(cid).items() if k not in ("id", "folder")}
    docs = []
    for d in _rows(db, "SELECT * FROM docs WHERE case_id=? ORDER BY pos, id", (cid,)):
        docs.append({**{k: v for k, v in d.items() if k not in _SKIP | {"path"}}, "file": _rel(d["path"], folder)})
    packs = []
    for p in _rows(db, "SELECT * FROM packs WHERE case_id=? ORDER BY id", (cid,)):
        items = [{**{k: v for k, v in it.items() if k not in {"id", "pack_id", "path"}}, "file": _rel(it["path"], folder)}
                 for it in _rows(db, "SELECT * FROM pack_items WHERE pack_id=? ORDER BY pos, id", (p["id"],))]
        packs.append({**{k: v for k, v in p.items() if k not in _SKIP}, "items": items})
    board = db.con.execute("SELECT scene FROM boards WHERE case_id=?", (cid,)).fetchone()
    tables = {t: [{k: v for k, v in r.items() if k not in _SKIP} for r in
                  _rows(db, f"SELECT * FROM {t} WHERE case_id=? ORDER BY id", (cid,))]
              for t in ("events", "time_entries", "payments", "quotes")}
    laws = [{k: v for k, v in r.items() if k != "case_id"} for r in
            _rows(db, "SELECT * FROM laws WHERE case_id=? ORDER BY id", (cid,))]
    return {"format": FORMAT, "app": "LegalHelper", "saved": dt.datetime.now().isoformat(timespec="seconds"),
            "case": c, "docs": docs, "packs": packs, "laws": laws, "board": board[0] if board else "", **tables}


def save_case_file(db, cid):
    """Записать LegalHelper-дело.json в папку дела (только если что-то изменилось). Возвращает путь."""
    folder = ensure_folder(db, cid)
    data = case_data(db, cid, folder)
    path = os.path.join(folder, CASE_FILE)
    body = dict(data, saved="")
    try:
        with open(path, encoding="utf-8") as f:
            old = json.load(f)
        if dict(old, saved="") == body:
            return path
    except Exception:
        pass
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)
    return path


def collect_files(db, cid):
    """Скопировать файлы дела, лежащие вне его папки, в «<папка дела>/Документы» и переключить пути на копии.
    Возвращает (скопировано, не найдено)."""
    folder = ensure_folder(db, cid)
    dest_dir = os.path.join(folder, DOCS_SUBDIR)
    copied, missing = 0, []
    moved = {}

    def bring(path):
        if not path or "rel" in _rel(path, folder):
            return path
        if path in moved:
            return moved[path]
        if not os.path.exists(path):
            missing.append(path)
            return path
        os.makedirs(dest_dir, exist_ok=True)
        stem, ext = os.path.splitext(os.path.basename(path))
        new, n = os.path.join(dest_dir, stem + ext), 2
        while os.path.exists(new):
            new, n = os.path.join(dest_dir, f"{stem} ({n}){ext}"), n + 1
        shutil.copy2(path, new)
        moved[path] = new
        return new
    for d in _rows(db, "SELECT id, path FROM docs WHERE case_id=?", (cid,)):
        new = bring(d["path"])
        if new != d["path"]:
            db.con.execute("UPDATE docs SET path=? WHERE id=?", (new, d["id"]))
            copied += 1
    for it in _rows(db, "SELECT i.id, i.path FROM pack_items i JOIN packs p ON p.id=i.pack_id WHERE p.case_id=?", (cid,)):
        new = bring(it["path"])
        if new != it["path"]:
            db.con.execute("UPDATE pack_items SET path=? WHERE id=?", (new, it["id"]))
    db.con.commit()
    save_case_file(db, cid)
    return copied, missing


def read_case_file(folder):
    path = os.path.join(folder, CASE_FILE)
    if not os.path.exists(path):
        raise FileNotFoundError(f"В папке нет файла «{CASE_FILE}» — это не папка дела LegalHelper.")
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if data.get("app") != "LegalHelper" or "case" not in data:
        raise ValueError("Файл дела повреждён или создан другой программой.")
    return data


def find_by_uid(db, uid):
    r = db.con.execute("SELECT id FROM cases WHERE uid=?", (uid,)).fetchone() if uid else None
    return r[0] if r else None


def _insert(db, table, row):
    cols = [k for k in row if k in _columns(db, table)]
    cur = db.con.execute(f"INSERT INTO {table}({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                         [row[k] for k in cols])
    return cur.lastrowid


def _columns(db, table, _cache={}):
    key = (id(db.con), table)
    if key not in _cache:
        _cache[key] = {r[1] for r in db.con.execute(f"PRAGMA table_info({table})")}
    return _cache[key]


def import_case(db, folder, replace_cid=None):
    """Загрузить дело из папки. replace_cid — заменить данные уже существующего дела (то же дело)."""
    data = read_case_file(folder)
    folder = os.path.abspath(folder)
    c = dict(data["case"])
    c["folder"] = folder
    c.setdefault("uid", uuid.uuid4().hex)
    con = db.con
    try:
        if replace_cid:
            db.delete_case(replace_cid)
        cid = _insert(db, "cases", {k: v for k, v in c.items() if k != "id"})
        for t in ("events", "time_entries", "payments", "quotes"):
            for r in data.get(t, []):
                _insert(db, t, dict(r, case_id=cid))
        for d in data.get("docs", []):
            _insert(db, "docs", dict({k: v for k, v in d.items() if k != "file"}, case_id=cid,
                                     path=_unrel(d.get("file"), folder)))
        for p in data.get("packs", []):
            pid = _insert(db, "packs", dict({k: v for k, v in p.items() if k != "items"}, case_id=cid))
            for it in p.get("items", []):
                _insert(db, "pack_items", dict({k: v for k, v in it.items() if k != "file"}, pack_id=pid,
                                               path=_unrel(it.get("file"), folder)))
        ids = {}
        for law in sorted(data.get("laws", []), key=lambda r: r.get("id", 0)):
            old = law.get("id")
            ids[old] = _insert(db, "laws", dict({k: v for k, v in law.items() if k != "id"}, case_id=cid,
                                                parent_id=0))
        for law in data.get("laws", []):
            if law.get("parent_id"):
                con.execute("UPDATE laws SET parent_id=? WHERE id=?", (ids.get(law["parent_id"], 0), ids[law.get("id")]))
        if data.get("board"):
            con.execute("INSERT OR REPLACE INTO boards(case_id, scene, updated) VALUES (?,?,?)",
                        (cid, data["board"], dt.datetime.now().isoformat(timespec="seconds")))
        con.commit()
    except Exception:
        con.rollback()
        raise
    return cid
