# -*- coding: utf-8 -*-
"""Карточки дел, события и сроки, документы, учёт времени и оплат, выписки — локально в SQLite."""
import os
import sqlite3
import datetime as dt

SCHEMA = """
CREATE TABLE IF NOT EXISTS cases(
    id INTEGER PRIMARY KEY, title TEXT NOT NULL, number TEXT DEFAULT '', court TEXT DEFAULT '',
    judge TEXT DEFAULT '', client TEXT DEFAULT '', opponent TEXT DEFAULT '', third TEXT DEFAULT '',
    stage TEXT DEFAULT '', claim TEXT DEFAULT '', rate REAL DEFAULT 0, notes TEXT DEFAULT '',
    folder TEXT DEFAULT '', archived INTEGER DEFAULT 0, created TEXT, updated TEXT);
CREATE TABLE IF NOT EXISTS events(
    id INTEGER PRIMARY KEY, case_id INTEGER, date TEXT, time TEXT DEFAULT '', kind TEXT DEFAULT 'Срок',
    title TEXT DEFAULT '', place TEXT DEFAULT '', done INTEGER DEFAULT 0, notified INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS docs(
    id INTEGER PRIMARY KEY, case_id INTEGER, path TEXT, title TEXT DEFAULT '', added TEXT);
CREATE TABLE IF NOT EXISTS time_entries(
    id INTEGER PRIMARY KEY, case_id INTEGER, date TEXT, hours REAL DEFAULT 0, rate REAL DEFAULT 0,
    amount REAL DEFAULT 0, description TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS payments(
    id INTEGER PRIMARY KEY, case_id INTEGER, date TEXT, amount REAL DEFAULT 0, note TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS quotes(
    id INTEGER PRIMARY KEY, case_id INTEGER, text TEXT, source TEXT DEFAULT '', page INTEGER DEFAULT 0,
    created TEXT);
CREATE TABLE IF NOT EXISTS packs(
    id INTEGER PRIMARY KEY, case_id INTEGER, title TEXT DEFAULT 'Исковое заявление',
    portal TEXT DEFAULT '', created TEXT, updated TEXT);
CREATE TABLE IF NOT EXISTS pack_items(
    id INTEGER PRIMARY KEY, pack_id INTEGER, pos INTEGER DEFAULT 0, title TEXT DEFAULT '',
    path TEXT DEFAULT '', copies INTEGER DEFAULT 1, done INTEGER DEFAULT 0, note TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS laws(
    id INTEGER PRIMARY KEY, case_id INTEGER, parent_id INTEGER DEFAULT 0, pos INTEGER DEFAULT 0,
    kind TEXT DEFAULT 'norm', title TEXT DEFAULT '', body TEXT DEFAULT '', note TEXT DEFAULT '',
    url TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS boards(
    case_id INTEGER PRIMARY KEY, scene TEXT DEFAULT '', updated TEXT);
CREATE TABLE IF NOT EXISTS instances(
    id INTEGER PRIMARY KEY, case_id INTEGER, pos INTEGER DEFAULT 0, level TEXT DEFAULT '', court TEXT DEFAULT '',
    number TEXT DEFAULT '', judge TEXT DEFAULT '', url TEXT DEFAULT '', result TEXT DEFAULT '');
"""

# Уровни судов: (уровень, стадия дела, следующий уровень)
COURT_LEVELS = [
    ("Мировой судья", "Первая инстанция", "Районный (городской) суд"),
    ("Районный (городской) суд", "Первая инстанция", "Областной (краевой) суд — апелляция"),
    ("Областной (краевой) суд — апелляция", "Апелляция", "Кассационный суд общей юрисдикции"),
    ("Кассационный суд общей юрисдикции", "Кассация", "Верховный Суд РФ"),
    ("Арбитражный суд субъекта РФ", "Первая инстанция", "Арбитражный апелляционный суд"),
    ("Арбитражный апелляционный суд", "Апелляция", "Арбитражный суд округа — кассация"),
    ("Арбитражный суд округа — кассация", "Кассация", "Верховный Суд РФ"),
    ("Суд по интеллектуальным правам", "Первая инстанция", "Верховный Суд РФ"),
    ("Верховный Суд РФ", "ВС РФ", "Конституционный Суд РФ"),
    ("Конституционный Суд РФ", "ВС РФ", ""),
    ("Иное (третейский суд, госорган…)", "", ""),
]
LEVEL_NAMES = [x[0] for x in COURT_LEVELS]


def guess_level(court, number=""):
    c = (court or "").lower()
    if "мировой" in c or "судебный участок" in c:
        return "Мировой судья"
    if "интеллектуальн" in c:
        return "Суд по интеллектуальным правам"
    if "верховный" in c:
        return "Верховный Суд РФ"
    if "апелляционный" in c and "арбитраж" in c:
        return "Арбитражный апелляционный суд"
    if "арбитражный суд" in c and "округа" in c:
        return "Арбитражный суд округа — кассация"
    if "арбитраж" in c or (number or "").strip()[:1] in ("А", "A"):
        return "Арбитражный суд субъекта РФ"
    if "кассационный" in c:
        return "Кассационный суд общей юрисдикции"
    if "областной" in c or "краевой" in c or "городской суд" in c and ("москов" in c or "санкт" in c):
        return "Областной (краевой) суд — апелляция"
    return "Районный (городской) суд"


def next_level(level, prev_levels=()):
    return next((n for l, _s, n in COURT_LEVELS if l == level), "") or ""


def stage_for(level, prev_levels=()):
    if level == "Районный (городской) суд" and "Мировой судья" in prev_levels:
        return "Апелляция"                    # районный суд — апелляция на решение мирового судьи
    return next((st for l, st, _n in COURT_LEVELS if l == level), "")

CASE_FIELDS = [("title", "Название"), ("number", "Номер дела"), ("court", "Суд"),
               ("court_url", "Ссылка на дело на сайте суда"), ("judge", "Судья"),
               ("client", "Доверитель"), ("opponent", "Процессуальный оппонент"), ("third", "Третьи лица"),
               ("stage", "Стадия"), ("claim", "Предмет / цена иска"), ("rate", "Ставка, ₽/час"),
               ("folder", "Папка с документами"), ("notes", "Заметки")]


def iso(d):
    return d.isoformat() if isinstance(d, (dt.date, dt.datetime)) else str(d)


def ru(d):
    """'2026-09-25' -> '25.09.2026'."""
    try:
        return dt.date.fromisoformat(str(d)[:10]).strftime("%d.%m.%Y")
    except ValueError:
        return str(d)


class CaseDB:
    def __init__(self, path):
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self.path = path
        self.con = sqlite3.connect(path)
        self.con.row_factory = sqlite3.Row
        self.con.execute("PRAGMA synchronous=FULL")      # запись на диск до конца — меньше риск порчи при сбое
        self.con.executescript(SCHEMA)
        self._migrate()
        self.con.commit()

    def _migrate(self):
        """Добавить новые поля в базы, созданные старыми версиями (данные не теряются)."""
        cols = {r[1] for r in self.con.execute("PRAGMA table_info(docs)")}
        for name, ddl in (("icon", "TEXT DEFAULT ''"), ("sent", "TEXT DEFAULT ''"), ("pos", "INTEGER DEFAULT 0")):
            if name not in cols:
                self.con.execute(f"ALTER TABLE docs ADD COLUMN {name} {ddl}")
        cols = {r[1] for r in self.con.execute("PRAGMA table_info(cases)")}
        if "court_url" not in cols:
            self.con.execute("ALTER TABLE cases ADD COLUMN court_url TEXT DEFAULT ''")
        if "uid" not in cols:                   # постоянный номер дела — чтобы узнать его в перенесённой папке
            self.con.execute("ALTER TABLE cases ADD COLUMN uid TEXT DEFAULT ''")
        import uuid
        for (cid,) in self.con.execute("SELECT id FROM cases WHERE uid IS NULL OR uid=''").fetchall():
            self.con.execute("UPDATE cases SET uid=? WHERE id=?", (uuid.uuid4().hex, cid))

    # ---------------------------------------------------------------- инстанции
    def instances(self, cid):
        return self._all("SELECT * FROM instances WHERE case_id=? ORDER BY pos, id", (cid,))

    def add_instance(self, cid, level="", court="", number="", judge="", url=""):
        r = self._one("SELECT COALESCE(MAX(pos), -1) + 1 AS n FROM instances WHERE case_id=?", (cid,))
        iid = self._exec("INSERT INTO instances(case_id,pos,level,court,number,judge,url) VALUES (?,?,?,?,?,?,?)",
                         (cid, r["n"], level, court, number, judge, url))
        self.sync_instance(cid)
        return iid

    def update_instance(self, iid, **kw):
        keys = [k for k in kw if k in ("level", "court", "number", "judge", "url", "result")]
        if keys:
            self._exec(f"UPDATE instances SET {','.join(k + '=?' for k in keys)} WHERE id=?",
                       [kw[k] for k in keys] + [iid])
            r = self._one("SELECT case_id FROM instances WHERE id=?", (iid,))
            if r:
                self.sync_instance(r["case_id"])

    def delete_instance(self, iid):
        r = self._one("SELECT case_id FROM instances WHERE id=?", (iid,))
        self._exec("DELETE FROM instances WHERE id=?", (iid,))
        if r:
            self.sync_instance(r["case_id"])

    def sync_instance(self, cid):
        """Текущая инстанция (последняя) — это «Суд», «Номер дела», «Судья», ссылка и стадия дела."""
        inst = self.instances(cid)
        if not inst:
            return
        cur = inst[-1]
        prev = [i["level"] for i in inst[:-1]]
        stage = stage_for(cur["level"], prev)
        kw = dict(court=cur["court"], number=cur["number"], judge=cur["judge"], court_url=cur["url"])
        if stage:
            kw["stage"] = stage
        self.update_case(cid, **kw)

    def ensure_instances(self, cid):
        """Дело из старой версии: первая инстанция — из того, что записано в карточке."""
        if self.instances(cid):
            return
        c = self.case(cid) or {}
        if not (c.get("court") or c.get("number")):
            return
        self._exec("INSERT INTO instances(case_id,pos,level,court,number,judge,url) VALUES (?,?,?,?,?,?,?)",
                   (cid, 0, guess_level(c.get("court"), c.get("number")), c.get("court", ""), c.get("number", ""),
                    c.get("judge", ""), c.get("court_url", "")))

    def close(self):
        try:
            self.con.commit()
            self.con.close()
        except Exception:
            pass

    # ---------------------------------------------------------------- общее
    def _all(self, sql, args=()):
        return [dict(r) for r in self.con.execute(sql, args).fetchall()]

    def _one(self, sql, args=()):
        r = self.con.execute(sql, args).fetchone()
        return dict(r) if r else None

    def _exec(self, sql, args=()):
        cur = self.con.execute(sql, args)
        self.con.commit()
        return cur.lastrowid

    # ---------------------------------------------------------------- дела
    def cases(self, archived=False, query=""):
        q = f"%{query.strip()}%"
        return self._all("SELECT * FROM cases WHERE archived=? AND (title LIKE ? OR number LIKE ? OR client "
                         "LIKE ? OR opponent LIKE ? OR court LIKE ?) ORDER BY updated DESC",
                         (1 if archived else 0, q, q, q, q, q))

    def case(self, cid):
        return self._one("SELECT * FROM cases WHERE id=?", (cid,))

    def add_case(self, **kw):
        import uuid
        now = dt.datetime.now().isoformat(timespec="seconds")
        kw.setdefault("title", "Новое дело")
        keys = [k for k, _ in CASE_FIELDS if k in kw]
        return self._exec(f"INSERT INTO cases({','.join(keys)},uid,created,updated) VALUES "
                          f"({','.join('?' * len(keys))},?,?,?)", [kw[k] for k in keys] + [uuid.uuid4().hex, now, now])

    def update_case(self, cid, **kw):
        keys = [k for k in kw if k in dict(CASE_FIELDS) or k == "archived"]
        if not keys:
            return
        now = dt.datetime.now().isoformat(timespec="seconds")
        self._exec(f"UPDATE cases SET {','.join(k + '=?' for k in keys)}, updated=? WHERE id=?",
                   [kw[k] for k in keys] + [now, cid])

    def delete_case(self, cid):
        for t in ("events", "docs", "time_entries", "payments", "quotes", "laws", "boards", "instances"):
            self.con.execute(f"DELETE FROM {t} WHERE case_id=?", (cid,))
        for p in self.packs(cid):
            self.delete_pack(p["id"])
        self._exec("DELETE FROM cases WHERE id=?", (cid,))

    # ---------------------------------------------------------------- события
    def events(self, cid=None, upcoming_days=None, include_done=True):
        sql, args = "SELECT e.*, c.title AS case_title, c.number AS case_number FROM events e " \
                    "LEFT JOIN cases c ON c.id=e.case_id WHERE 1=1", []
        if cid is not None:
            sql += " AND e.case_id=?"
            args.append(cid)
        if not include_done:
            sql += " AND e.done=0"
        if upcoming_days is not None:
            sql += " AND e.date<=? AND (c.archived IS NULL OR c.archived=0)"
            args.append(iso(dt.date.today() + dt.timedelta(days=upcoming_days)))
        return self._all(sql + " ORDER BY e.date, e.time", args)

    def add_event(self, cid, date, kind="Срок", title="", time="", place=""):
        return self._exec("INSERT INTO events(case_id,date,time,kind,title,place) VALUES (?,?,?,?,?,?)",
                          (cid, iso(date), time, kind, title, place))

    def update_event(self, eid, **kw):
        keys = [k for k in kw if k in ("date", "time", "kind", "title", "place", "done", "notified")]
        self._exec(f"UPDATE events SET {','.join(k + '=?' for k in keys)} WHERE id=?",
                   [iso(kw[k]) if k == "date" else kw[k] for k in keys] + [eid])

    REMINDER = "Напоминание"

    def reminders(self, cid=None, include_done=False):
        """Напоминания (события вида «Напоминание») — срабатывают в точное время."""
        return [e for e in self.events(cid, include_done=include_done) if e["kind"] == self.REMINDER]

    def delete_event(self, eid):
        self._exec("DELETE FROM events WHERE id=?", (eid,))

    # ---------------------------------------------------------------- документы
    def docs(self, cid):
        return self._all("SELECT * FROM docs WHERE case_id=? ORDER BY pos, added", (cid,))

    def update_doc(self, did, **kw):
        keys = [k for k in kw if k in ("title", "icon", "sent", "pos", "path")]
        if keys:
            self._exec(f"UPDATE docs SET {','.join(k + '=?' for k in keys)} WHERE id=?",
                       tuple(kw[k] for k in keys) + (did,))

    def add_doc(self, cid, path, title=""):
        if self._one("SELECT id FROM docs WHERE case_id=? AND path=?", (cid, path)):
            return None
        return self._exec("INSERT INTO docs(case_id,path,title,added) VALUES (?,?,?,?)",
                          (cid, path, title or os.path.splitext(os.path.basename(path))[0],
                           dt.datetime.now().isoformat(timespec="seconds")))

    def case_of_path(self, path):
        r = self._one("SELECT d.case_id AS cid FROM docs d JOIN cases c ON c.id=d.case_id "
                      "WHERE d.path=? ORDER BY c.archived, d.id DESC LIMIT 1", (path,))
        return r["cid"] if r else None

    def unlink_path(self, cid, path):
        self._exec("DELETE FROM docs WHERE case_id=? AND path=?", (cid, path))

    def delete_doc(self, did):
        self._exec("DELETE FROM docs WHERE id=?", (did,))

    def forget_path(self, path):
        """Файл удалён: убрать его из всех дел и комплектов."""
        self._exec("DELETE FROM docs WHERE path=?", (path,))
        self._exec("DELETE FROM pack_items WHERE path=?", (path,))

    # ---------------------------------------------------------------- время и оплаты
    def time_entries(self, cid):
        return self._all("SELECT * FROM time_entries WHERE case_id=? ORDER BY date", (cid,))

    def add_time(self, cid, date, hours, description, rate=0.0, amount=0.0):
        return self._exec("INSERT INTO time_entries(case_id,date,hours,rate,amount,description) VALUES "
                          "(?,?,?,?,?,?)", (cid, iso(date), hours, rate, amount, description))

    def delete_time(self, tid):
        self._exec("DELETE FROM time_entries WHERE id=?", (tid,))

    def payments(self, cid):
        return self._all("SELECT * FROM payments WHERE case_id=? ORDER BY date", (cid,))

    def add_payment(self, cid, date, amount, note=""):
        return self._exec("INSERT INTO payments(case_id,date,amount,note) VALUES (?,?,?,?)",
                          (cid, iso(date), amount, note))

    def delete_payment(self, pid):
        self._exec("DELETE FROM payments WHERE id=?", (pid,))

    def balance(self, cid):
        billed = sum((e["amount"] or (e["hours"] or 0) * (e["rate"] or 0)) for e in self.time_entries(cid))
        paid = sum(p["amount"] or 0 for p in self.payments(cid))
        hours = sum(e["hours"] or 0 for e in self.time_entries(cid))
        return dict(hours=hours, billed=billed, paid=paid, due=billed - paid)

    # ---------------------------------------------------------------- выписки
    def quotes(self, cid):
        return self._all("SELECT * FROM quotes WHERE case_id=? ORDER BY created", (cid,))

    def add_quote(self, cid, text, source="", page=0):
        return self._exec("INSERT INTO quotes(case_id,text,source,page,created) VALUES (?,?,?,?,?)",
                          (cid, text, source, page, dt.datetime.now().isoformat(timespec="seconds")))

    def delete_quote(self, qid):
        self._exec("DELETE FROM quotes WHERE id=?", (qid,))

    # ---------------------------------------------------------------- для шаблонов
    def template_values(self, cid):
        c = self.case(cid) or {}
        today = dt.date.today()
        return {"Дело": c.get("title", ""), "Номер_дела": c.get("number", ""), "Суд": c.get("court", ""),
                "Судья": c.get("judge", ""), "Доверитель": c.get("client", ""),
                "Оппонент": c.get("opponent", ""), "Третьи_лица": c.get("third", ""),
                "Предмет": c.get("claim", ""), "Дата": today.strftime("%d.%m.%Y"),
                **self._instance_values(cid)}

    def _instance_values(self, cid):
        inst = self.instances(cid) if cid else []
        if not inst:
            return {}
        first = inst[0]
        vals = {"Суд_первой_инстанции": first["court"], "Номер_дела_первой_инстанции": first["number"]}
        if len(inst) > 1:
            vals["Нижестоящий_суд"] = inst[-2]["court"]
        return vals


# ============================================================================
#  Подача: комплекты документов с чек-листом (сохраняются сразу при изменении)
# ============================================================================
def _now():
    return dt.datetime.now().isoformat(timespec="seconds")


def _packs(self, cid):
    return self._all("SELECT * FROM packs WHERE case_id=? ORDER BY id", (cid,))


def _add_pack(self, cid, title="Исковое заявление", portal=""):
    return self._exec("INSERT INTO packs(case_id,title,portal,created,updated) VALUES (?,?,?,?,?)",
                      (cid, title, portal, _now(), _now()))


def _update_pack(self, pid, **kw):
    keys = [k for k in kw if k in ("title", "portal")]
    if keys:
        self._exec(f"UPDATE packs SET {','.join(k + '=?' for k in keys)}, updated=? WHERE id=?",
                   [kw[k] for k in keys] + [_now(), pid])


def _delete_pack(self, pid):
    self.con.execute("DELETE FROM pack_items WHERE pack_id=?", (pid,))
    self._exec("DELETE FROM packs WHERE id=?", (pid,))


def _pack_items(self, pid):
    return self._all("SELECT * FROM pack_items WHERE pack_id=? ORDER BY pos, id", (pid,))


def _add_pack_item(self, pid, title, path="", copies=1, done=0, note="", pos=None):
    if pos is None:
        r = self._one("SELECT COALESCE(MAX(pos), -1) + 1 AS n FROM pack_items WHERE pack_id=?", (pid,))
        pos = r["n"]
    self._exec("UPDATE packs SET updated=? WHERE id=?", (_now(), pid))
    return self._exec("INSERT INTO pack_items(pack_id,pos,title,path,copies,done,note) VALUES (?,?,?,?,?,?,?)",
                      (pid, pos, title, path, copies, done, note))


def _update_pack_item(self, iid, **kw):
    keys = [k for k in kw if k in ("pos", "title", "path", "copies", "done", "note")]
    if keys:
        self._exec(f"UPDATE pack_items SET {','.join(k + '=?' for k in keys)} WHERE id=?",
                   [kw[k] for k in keys] + [iid])


def _delete_pack_item(self, iid):
    self._exec("DELETE FROM pack_items WHERE id=?", (iid,))


def _reorder_pack_items(self, ids):
    for pos, iid in enumerate(ids):
        self.con.execute("UPDATE pack_items SET pos=? WHERE id=?", (pos, iid))
    self.con.commit()


# ============================================================================
#  Нормы права: дерево (группа → акт → статья/пункт)
# ============================================================================
def _laws(self, cid):
    return self._all("SELECT * FROM laws WHERE case_id=? ORDER BY parent_id, pos, id", (cid,))


def _add_law(self, cid, parent_id=0, kind="norm", title="", body="", note="", url=""):
    r = self._one("SELECT COALESCE(MAX(pos), -1) + 1 AS n FROM laws WHERE case_id=? AND parent_id=?",
                  (cid, parent_id))
    return self._exec("INSERT INTO laws(case_id,parent_id,pos,kind,title,body,note,url) VALUES (?,?,?,?,?,?,?,?)",
                      (cid, parent_id, r["n"], kind, title, body, note, url))


def _update_law(self, lid, **kw):
    keys = [k for k in kw if k in ("parent_id", "pos", "kind", "title", "body", "note", "url")]
    if keys:
        self._exec(f"UPDATE laws SET {','.join(k + '=?' for k in keys)} WHERE id=?", [kw[k] for k in keys] + [lid])


def _delete_law(self, lid):
    for ch in self._all("SELECT id FROM laws WHERE parent_id=?", (lid,)):
        _delete_law(self, ch["id"])
    self._exec("DELETE FROM laws WHERE id=?", (lid,))


def _copy_laws(self, src_cid, dst_cid, ids=None):
    """Скопировать нормы из другого дела (всё дерево или выбранные узлы с потомками)."""
    rows = self.laws(src_cid)
    kids = {}
    for r in rows:
        kids.setdefault(r["parent_id"], []).append(r)
    roots = [r for r in rows if (ids is None and r["parent_id"] == 0) or (ids and r["id"] in ids)]

    def dup(r, parent):
        nid = self.add_law(dst_cid, parent, r["kind"], r["title"], r["body"], r["note"], r["url"])
        for ch in kids.get(r["id"], []):
            dup(ch, nid)
    for r in roots:
        dup(r, 0)
    return len(roots)


# ============================================================================
#  Карта дела (сцена Excalidraw в JSON)
# ============================================================================
def _board(self, cid):
    r = self._one("SELECT scene FROM boards WHERE case_id=?", (cid,))
    return r["scene"] if r else ""


def _save_board(self, cid, scene):
    self._exec("INSERT INTO boards(case_id,scene,updated) VALUES (?,?,?) "
               "ON CONFLICT(case_id) DO UPDATE SET scene=excluded.scene, updated=excluded.updated",
               (cid, scene, _now()))


for _n, _f in dict(packs=_packs, add_pack=_add_pack, update_pack=_update_pack, delete_pack=_delete_pack,
                   pack_items=_pack_items, add_pack_item=_add_pack_item, update_pack_item=_update_pack_item,
                   delete_pack_item=_delete_pack_item, reorder_pack_items=_reorder_pack_items,
                   laws=_laws, add_law=_add_law, update_law=_update_law, delete_law=_delete_law,
                   copy_laws=_copy_laws, board=_board, save_board=_save_board).items():
    setattr(CaseDB, _n, _f)
