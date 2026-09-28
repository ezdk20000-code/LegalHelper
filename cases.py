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
"""

CASE_FIELDS = [("title", "Название"), ("number", "Номер дела"), ("court", "Суд"), ("judge", "Судья"),
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
        self.con.executescript(SCHEMA)
        self.con.commit()

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
        now = dt.datetime.now().isoformat(timespec="seconds")
        kw.setdefault("title", "Новое дело")
        keys = [k for k, _ in CASE_FIELDS if k in kw]
        return self._exec(f"INSERT INTO cases({','.join(keys)},created,updated) VALUES "
                          f"({','.join('?' * len(keys))},?,?)", [kw[k] for k in keys] + [now, now])

    def update_case(self, cid, **kw):
        keys = [k for k in kw if k in dict(CASE_FIELDS) or k == "archived"]
        if not keys:
            return
        now = dt.datetime.now().isoformat(timespec="seconds")
        self._exec(f"UPDATE cases SET {','.join(k + '=?' for k in keys)}, updated=? WHERE id=?",
                   [kw[k] for k in keys] + [now, cid])

    def delete_case(self, cid):
        for t in ("events", "docs", "time_entries", "payments", "quotes"):
            self.con.execute(f"DELETE FROM {t} WHERE case_id=?", (cid,))
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

    def delete_event(self, eid):
        self._exec("DELETE FROM events WHERE id=?", (eid,))

    # ---------------------------------------------------------------- документы
    def docs(self, cid):
        return self._all("SELECT * FROM docs WHERE case_id=? ORDER BY added", (cid,))

    def add_doc(self, cid, path, title=""):
        if self._one("SELECT id FROM docs WHERE case_id=? AND path=?", (cid, path)):
            return None
        return self._exec("INSERT INTO docs(case_id,path,title,added) VALUES (?,?,?,?)",
                          (cid, path, title or os.path.splitext(os.path.basename(path))[0],
                           dt.datetime.now().isoformat(timespec="seconds")))

    def delete_doc(self, did):
        self._exec("DELETE FROM docs WHERE id=?", (did,))

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
                "Предмет": c.get("claim", ""), "Дата": today.strftime("%d.%m.%Y")}
