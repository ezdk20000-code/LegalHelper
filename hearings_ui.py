# -*- coding: utf-8 -*-
"""
Заседания и сроки из документов суда. Добавили определение — программа сама находит в нём
«назначить судебное заседание на 12 ноября 2026 года в 10 час. 30 мин., зал № 5» и «представить отзыв
в срок до…» и предлагает внести это в «Сроки и заседания» одной кнопкой. Для уже добавленных документов —
кнопка «📄 Даты из документов» во вкладке «Сроки и заседания».
"""
import os
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QTableWidget, QTableWidgetItem,
                               QHeaderView, QAbstractItemView, QDialogButtonBox, QApplication, QComboBox)

import hearings as H
import doc_names as N


def _db():
    import legal_ui as U
    return U.db()


def refresh(main, cid):
    page = getattr(main, "cases_page", None)
    if page is not None and getattr(page, "cid", None) == cid:
        for fn in ("load_events", "reload_upcoming"):
            try:
                getattr(page, fn)()
            except Exception:
                pass
    ov = getattr(main, "overview", None)
    if ov is not None and getattr(ov, "cid", None) == cid:
        try:
            ov.set_case(cid)
        except Exception:
            pass


def found_in(cid, paths):
    """Новые для дела события из файлов: [(событие, имя файла)]."""
    existing = _db().events(cid)
    out, seen = [], []
    for path in paths:
        text = N.read_text(path, pages=4)
        for ev in H.parse(text):
            if H.is_known(ev, existing) or H.is_known(ev, seen):
                continue
            seen.append(ev)
            out.append((ev, Path(path).name))
    return out


# ----------------------------------------------------------------------------- после добавления документа
def install(main):
    import cases
    main._hear_queue = []

    def hook(cid, did, path):
        if not cid or getattr(main, "tutor", None) or getattr(main, "_rename_busy", False):
            return
        main._hear_queue.append((cid, path))
        t = getattr(main, "_hear_timer", None)
        if t is None:
            t = main._hear_timer = QTimer(main)
            t.setSingleShot(True)
            t.timeout.connect(lambda: _flush(main))
        main._hear_pending = True                    # «назвать как в суде» подождёт, пока не ответят про даты
        t.start(600)
    cases.DOC_ADDED_HOOKS[:] = [h for h in cases.DOC_ADDED_HOOKS if not getattr(h, "_hear_hook", False)]
    hook._hear_hook = True
    cases.DOC_ADDED_HOOKS.insert(0, hook)


def _after(main, delay=300):
    """Плашку про даты закрыли — показать отложенное предложение назвать документ как в суде."""
    main._hear_pending = False
    main._hear_token = None
    fn = getattr(main, "_rename_deferred", None)
    main._rename_deferred = None
    if fn:
        QTimer.singleShot(delay, fn)


def _flush(main):
    queue, main._hear_queue = main._hear_queue, []
    by_case = {}
    for cid, path in queue:
        if path and os.path.isfile(path):
            by_case.setdefault(cid, []).append(path)
    rows = []
    for cid, paths in by_case.items():
        try:
            rows += [(cid, ev, name) for ev, name in found_in(cid, paths)]
        except Exception:
            pass
    if not rows:
        return _after(main)

    token = object()
    main._hear_token = token
    QTimer.singleShot(31000, lambda: _after(main) if getattr(main, "_hear_token", None) is token else None)

    def done(fn=None, delay=300):
        def run():
            if fn:
                fn()
            _after(main, delay)            # после «Добавить» дать время нажать «Отменить» на плашке
        return run
    names = {n for _c, _e, n in rows}
    if len(rows) <= 3 and len(names) == 1:
        lines = "\n".join("•  " + H.describe(e) for _c, e, _n in rows)
        what = "назначено заседание" if all(e["kind"] == "Заседание" for _c, e, _n in rows) else "есть даты"
        main.toast_actions(f"В документе «{rows[0][2]}» {what}:\n{lines}",
                           [("Добавить в сроки" if len(rows) == 1 else f"Добавить все ({len(rows)})",
                             done(lambda: add(main, rows), 5000)),
                            ("Выбрать…", done(lambda: open_dialog(main, rows))),
                            ("Не нужно", done())], ms=30000)
    else:
        hear = sum(1 for _c, e, _n in rows if e["kind"] == "Заседание")
        main.toast_actions(f"В добавленных документах нашлись даты: заседаний — {hear}, сроков — {len(rows) - hear}",
                           [("Посмотреть и добавить…", done(lambda: open_dialog(main, rows))),
                            ("Не нужно", done())], ms=30000)

def add(main, rows):
    added = []
    for cid, ev, _name in rows:
        eid = _db().add_event(cid, ev["date"], ev["kind"], ev["title"], ev.get("time", ""), ev.get("place", ""))
        added.append((cid, eid))
    for cid in {c for c, _e in added}:
        refresh(main, cid)

    def undo():
        for cid, eid in added:
            _db().delete_event(eid)
        for cid in {c for c, _e in added}:
            refresh(main, cid)
    one = rows[0][1]
    main.toast_undo(f"✓  Добавлено в «Сроки и заседания»: {H.describe(one)}" if len(rows) == 1 else
                    f"✓  Добавлено в «Сроки и заседания»: {len(rows)}", undo)


# ----------------------------------------------------------------------------- по всем документам дела
def scan_case(main, cid):
    docs = [d["path"] for d in _db().docs(cid) if d["path"] and os.path.isfile(d["path"])] if cid else []
    if not docs:
        return main.toast("В деле нет документов-файлов")
    QApplication.setOverrideCursor(Qt.WaitCursor)
    try:
        rows = [(cid, ev, name) for ev, name in found_in(cid, docs)]
    finally:
        QApplication.restoreOverrideCursor()
    if not rows:
        return main.toast("Новых дат заседаний и сроков в документах не нашлось (сканы без текста программа не читает)",
                          5000)
    open_dialog(main, rows)


class HearingsDialog(QDialog):
    COLS = ["Вид", "Дата", "Время", "Что", "Место", "Откуда"]

    def __init__(self, parent, rows):
        super().__init__(parent)
        self.setWindowTitle("Даты из документов")
        self.resize(1000, min(600, 230 + 36 * len(rows)))
        self.rows = rows
        v = QVBoxLayout(self)
        lab = QLabel("Программа нашла в документах суда даты заседаний и сроки. Отметьте нужные — они появятся во "
                     "вкладке «Сроки и заседания», и программа заранее напомнит о них. Любую ячейку можно "
                     "поправить двойным щелчком.")
        lab.setWordWrap(True)
        lab.setObjectName("hint")
        v.addWidget(lab)
        t = self.t = QTableWidget(len(rows), len(self.COLS))
        t.setHorizontalHeaderLabels(self.COLS)
        t.verticalHeader().hide()
        t.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed)
        hh = t.horizontalHeader()
        for i, w in enumerate((120, 100, 70, 260, 260)):
            t.setColumnWidth(i, w)
        hh.setSectionResizeMode(5, QHeaderView.Stretch)
        import legal_data as D
        for i, (_cid, ev, name) in enumerate(rows):
            kind = QComboBox()
            kind.addItems(D.EVENT_KINDS)
            kind.setCurrentText(ev["kind"])
            t.setCellWidget(i, 0, kind)
            y, m, d = ev["date"].split("-")
            vals = [f"{d}.{m}.{y}", ev.get("time", ""), ev["title"], ev.get("place", ""), name]
            for j, val in enumerate(vals, 1):
                it = QTableWidgetItem(val)
                if j == 1:
                    it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
                    it.setCheckState(Qt.Checked)
                if j == 5:
                    it.setFlags(Qt.ItemIsEnabled)
                    it.setToolTip(ev.get("snippet", ""))
                t.setItem(i, j, it)
        v.addWidget(t, 1)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Добавить отмеченные")
        bb.button(QDialogButtonBox.Cancel).setText("Отмена")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def chosen(self):
        import datetime as dt
        out = []
        for i, (cid, ev, name) in enumerate(self.rows):
            if self.t.item(i, 1).checkState() != Qt.Checked:
                continue
            try:
                d = dt.datetime.strptime(self.t.item(i, 1).text().strip(), "%d.%m.%Y").date().isoformat()
            except ValueError:
                d = ev["date"]
            out.append((cid, dict(ev, kind=self.t.cellWidget(i, 0).currentText(), date=d,
                                  time=self.t.item(i, 2).text().strip(), title=self.t.item(i, 3).text().strip(),
                                  place=self.t.item(i, 4).text().strip()), name))
        return out


def open_dialog(main, rows):
    d = HearingsDialog(main, rows)
    if d.exec() == QDialog.Accepted:
        rows = d.chosen()
        if rows:
            add(main, rows)
