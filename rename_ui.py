# -*- coding: utf-8 -*-
"""
«Назвать как в суде»: после добавления документа программа читает его и предлагает понятное имя —
«2026-09-12 Определение о принятии искового заявления». Одно нажатие переименовывает и название в программе,
и сам файл на диске; «Отменить» на плашке возвращает как было. Для уже добавленных документов —
«Ещё ▾ → Назвать документы как в суде…» во вкладке «Документы».
"""
import os
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QTableWidget, QTableWidgetItem,
                               QHeaderView, QAbstractItemView, QDialogButtonBox, QPushButton, QApplication)

import doc_names as N
import pdf_core as C

SETTING = "court_names_offer"          # "0" — не предлагать после добавления


def _db():
    import legal_ui as U
    return U.db()


def _settings():
    import legal_ui as U
    return U.M.settings()


def offer_enabled():
    return str(_settings().value(SETTING, "1")) != "0"


# ----------------------------------------------------------------------------- после добавления
def install(main):
    """Подписаться на добавление документов: собрать пачку (перетащили сразу несколько) и предложить имена."""
    import cases
    main._rename_queue = []

    def hook(cid, did, path):
        if not offer_enabled() or getattr(main, "_rename_busy", False) or getattr(main, "tutor", None):
            return
        main._rename_queue.append((cid, did, path))
        t = getattr(main, "_rename_timer", None)
        if t is None:
            t = main._rename_timer = QTimer(main)
            t.setSingleShot(True)
            t.timeout.connect(lambda: _flush(main))
        t.start(900)
    cases.DOC_ADDED_HOOKS[:] = [h for h in cases.DOC_ADDED_HOOKS if getattr(h, "_rename_hook", False) is False]
    hook._rename_hook = True
    cases.DOC_ADDED_HOOKS.append(hook)


def _flush(main):
    queue, main._rename_queue = main._rename_queue, []
    rows = []
    for cid, did, path in queue:
        if not path or not os.path.isfile(path):
            continue
        s = N.suggest(path)
        if s and s["needed"] and not s["same"]:
            rows.append(dict(cid=cid, did=did, path=path, stem=s["stem"], kind=s["kind"], checked=True))
    if not rows:
        return
    if len(rows) == 1:
        r = rows[0]
        ext = Path(r["path"]).suffix
        main.toast_actions(f"Назвать документ как в суде?\n{Path(r['path']).name}  →  {r['stem']}{ext}",
                           [("Переименовать", lambda: apply(main, rows)),
                            ("Изменить…", lambda: open_dialog(main, rows)),
                            ("Не предлагать", lambda: _turn_off(main))], ms=20000, closable=True)
    else:
        main.toast_actions(f"Можно назвать как в суде: {len(rows)} {_docs_word(len(rows))} "
                           "(дата + что за документ)",
                           [("Посмотреть…", lambda: open_dialog(main, rows)),
                            ("Не предлагать", lambda: _turn_off(main))], ms=20000, closable=True)


def _docs_word(n):
    import legal_core as L
    return L.plural(n, "документ", "документа", "документов")


def _turn_off(main):
    _settings().setValue(SETTING, "0")
    main.toast("Больше не предлагаю. Вернуть: «Документы → Ещё ▾ → Назвать документы как в суде…»", 5000)


# ----------------------------------------------------------------------------- для всех документов дела
def tidy_case(main, cid):
    docs = [d for d in _db().docs(cid) if d["path"] and os.path.isfile(d["path"])] if cid else []
    if not docs:
        return main.toast("В деле нет документов-файлов")
    QApplication.setOverrideCursor(Qt.WaitCursor)
    try:
        rows = []
        for d in docs:
            s = N.suggest(d["path"])
            if s and not s["same"]:
                rows.append(dict(cid=cid, did=d["id"], path=d["path"], stem=s["stem"], kind=s["kind"],
                                 checked=s["needed"]))
    finally:
        QApplication.restoreOverrideCursor()
    if not rows:
        return main.toast("Названия уже в порядке — или в документах нет текста (сканы без распознавания)", 4500)
    open_dialog(main, rows, note=f"Проверено документов: {len(docs)}. Отмечены те, в названии которых не видно, "
                                 "что это за документ. Новое имя можно поправить — щёлкните по нему дважды.")


class RenameDialog(QDialog):
    def __init__(self, parent, rows, note=""):
        super().__init__(parent)
        self.setWindowTitle("Назвать как в суде")
        self.resize(900, min(620, 220 + 34 * len(rows)))
        self.rows = rows
        v = QVBoxLayout(self)
        lab = QLabel(note or "Дата и что это за документ — так файлы легко найти и в программе, и в папке на диске. "
                             "Новое имя можно поправить: двойной щелчок по нему.")
        lab.setWordWrap(True)
        lab.setObjectName("hint")
        v.addWidget(lab)
        t = self.t = QTableWidget(len(rows), 2)
        t.setHorizontalHeaderLabels(["Сейчас", "Будет"])
        t.verticalHeader().hide()
        t.setSelectionMode(QAbstractItemView.NoSelection)
        t.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed)
        t.horizontalHeader().setSectionResizeMode(0, QHeaderView.Interactive)
        t.setColumnWidth(0, 280)
        t.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        for i, r in enumerate(rows):
            a = QTableWidgetItem(Path(r["path"]).name)
            a.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
            a.setCheckState(Qt.Checked if r.get("checked", True) else Qt.Unchecked)
            a.setToolTip(r["path"])
            b = QTableWidgetItem(r["stem"])
            b.setToolTip(f"Похоже на: {r['kind']}. Расширение ({Path(r['path']).suffix}) останется прежним.")
            t.setItem(i, 0, a)
            t.setItem(i, 1, b)
        t.resizeRowsToContents()
        v.addWidget(t, 1)
        row = QHBoxLayout()
        for text, on in (("Отметить все", True), ("Снять все", False)):
            b = QPushButton(text)
            b.clicked.connect(lambda _=False, o=on: self._all(o))
            row.addWidget(b)
        row.addStretch(1)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Переименовать отмеченные")
        bb.button(QDialogButtonBox.Cancel).setText("Отмена")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        row.addWidget(bb)
        v.addLayout(row)

    def _all(self, on):
        for i in range(self.t.rowCount()):
            self.t.item(i, 0).setCheckState(Qt.Checked if on else Qt.Unchecked)

    def chosen(self):
        out = []
        for i, r in enumerate(self.rows):
            if self.t.item(i, 0).checkState() == Qt.Checked:
                stem = N.safe_stem(self.t.item(i, 1).text())
                if stem:
                    out.append(dict(r, stem=stem))
        return out


def open_dialog(main, rows, note=""):
    d = RenameDialog(main, rows, note)
    if d.exec() == QDialog.Accepted:
        apply(main, d.chosen())


def apply(main, rows):
    """Переименовать; на плашке — «Отменить» (вернуть прежние имена файлов и названия)."""
    done = []
    main._rename_busy = True
    try:
        for r in rows:
            old = r["path"]
            if not os.path.isfile(old):
                continue
            new = N.unique_path(os.path.dirname(old), r["stem"], Path(old).suffix, skip=old)
            if main.rename_doc_file(old, new):
                done.append((old, new))
    finally:
        main._rename_busy = False
    if not done:
        return

    def undo():
        main._rename_busy = True
        try:
            for old, new in reversed(done):
                if os.path.isfile(new) and not os.path.exists(old):
                    main.rename_doc_file(new, old)
        finally:
            main._rename_busy = False
    text = (f"✓  Переименовано: «{Path(done[0][1]).name}»" if len(done) == 1 else
            f"✓  Переименовано документов: {len(done)}")
    main.toast_undo(text, undo)
