# -*- coding: utf-8 -*-
"""
Поиск по всему (Ctrl+K): одно поле — и сразу дела, документы, сроки, шаблоны, действия, инструменты
и статьи справки. Стрелки ↑↓ — выбрать, Enter — открыть, Esc — закрыть.
"""
import os
import datetime as dt
from pathlib import Path

from PySide6.QtCore import Qt, QEvent, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLineEdit, QListWidget, QListWidgetItem, QLabel,
                               QAbstractItemView, QFrame)

import legal_ui as U
import help_ui as H

LIMITS = {"Дела": 6, "Документы": 6, "Сроки и заседания": 4, "Действия": 8, "Шаблоны": 5, "Справка": 5}
ORDER = ["Действия", "Дела", "Документы", "Сроки и заседания", "Шаблоны", "Справка"]


def _norm(s):
    return (s or "").lower().replace("ё", "е")


class Entry:
    __slots__ = ("group", "icon", "title", "sub", "hay", "run")

    def __init__(self, group, icon, title, sub, run, extra=""):
        self.group, self.icon, self.title, self.sub, self.run = group, icon, title, sub, run
        self.hay = _norm(f"{title} {sub} {extra}")

    def score(self, words):
        if not all(w in self.hay for w in words):
            return None
        t = _norm(self.title)
        sc = 0
        for w in words:
            sc += 6 if t.startswith(w) else 4 if f" {w}" in f" {t}" else 2 if w in t else 1
        return sc


def _actions(m):
    """Что можно сделать: переходы, окна, вкладки дела, все инструменты."""
    out = []

    def a(icon, title, sub, fn, extra=""):
        out.append(Entry("Действия", icon, title, sub, fn, extra))
    a("➕", "Новое дело", "Завести дело с папкой", lambda: m.cases_page.new_case(), "создать добавить")
    a("🏠", "Главная", "Сегодня, неделя, горящие сроки", m.show_home, "сводка дашборд")
    a("📂", "Без дела — просто PDF", "Открыть и поправить любой PDF", m.enter_loose, "файл открыть редактор")
    a("🗑", "Корзина", "Вернуть удалённое за 30 дней", m.show_trash, "восстановить удалено")
    a("🎓", "Обучение со стрелками", "Пройти заново", lambda: __import__("tutorial").start(m), "урок помощь")
    a("❓", "Справка", "Как пользоваться программой", lambda: m.show_section(3), "помощь инструкция")
    a("🛟", "Резервные копии", "Восстановить данные за прошлый день", lambda: U.BackupsDialog(m).exec(),
      "бэкап копия восстановить")
    a("📱", "Дела на телефоне", "Настроить Яндекс Диск", m.phone_setup, "яндекс диск телефон iphone android")
    a("👤", "Мои реквизиты", "ФИО, адрес, телефон — для шаблонов", lambda: U.tool_profile(m),
      "профиль представитель доверенность")
    for key, title, sub in (("overview", "Обзор", "Главное по делу"),
                            ("docs", "Документы", "Документы и PDF дела"),
                            ("prepare", "Создать документ", "Шаблоны, пакет в суд, инструменты"),
                            ("events", "Сроки", "Заседания, сроки, задачи"),
                            ("money", "Деньги", "Время и оплата"),
                            ("calc", "Калькуляторы", "Пошлина, проценты, сроки"),
                            ("info", "Сведения", "Суд, номер, стороны, папка"),
                            ("board", "Карта дела", "Схема дела"),
                            ("laws", "Нормы права", "Статьи для позиции"),
                            ("quotes", "Выписки", "Цитаты с номером листа")):
        a("🗂", f"Вкладка дела: {title}", sub, lambda k=key: m.open_case_tab(k), "открыть перейти")
    for cat, items in U.M.TOOLS:
        for key, label, tip in items:
            a(U.TOOL_ICONS.get(key, "•"), label, tip, U.tool_callable(m, key), cat)
    return out


def _cases(m):
    out = []
    for c in U.db().cases(False, "") + U.db().cases(True, ""):
        sub = " · ".join(x for x in (c.get("number"), c.get("client"), c.get("court")) if x)
        if c.get("archived"):
            sub = ("в архиве · " + sub).strip(" ·")
        out.append(Entry("Дела", "📁", c["title"], sub, lambda cid=c["id"]: _open_case(m, cid),
                         f"{c.get('opponent') or ''} {c.get('judge') or ''} {c.get('stage') or ''}"))
    seen, uniq = set(), []
    for e in out:
        if e.title + e.sub not in seen:
            seen.add(e.title + e.sub)
            uniq.append(e)
    return uniq


def _open_case(m, cid, tab=None):
    c = U.db().case(cid)
    if c and c.get("archived") and not m.cases_page.show_arch.isChecked():
        m.cases_page.show_arch.setChecked(True)
    m.enter_case(cid)
    if tab:
        m.open_case_tab(tab)


def _docs(m):
    rows = U.db()._all("SELECT d.id, d.title, d.path, d.case_id, c.title AS case_title FROM docs d "
                       "JOIN cases c ON c.id=d.case_id ORDER BY c.updated DESC, d.pos, d.id")
    out = []
    for d in rows:
        def run(d=d):
            _open_case(m, d["case_id"], "docs")
            if d["path"] and os.path.exists(d["path"]):
                m.cases_page.openFile.emit(d["path"], 0)
        out.append(Entry("Документы", U.default_icon(d["path"]), d["title"] or os.path.basename(d["path"] or ""),
                         d["case_title"], run, os.path.basename(d["path"] or "")))
    return out


def _events(m):
    out = []
    today = dt.date.today()
    for e in U.db().events(upcoming_days=90, include_done=False):
        try:
            d = dt.date.fromisoformat(e["date"])
        except Exception:
            continue
        if d < today - dt.timedelta(days=30):
            continue
        when = d.strftime("%d.%m.%Y") + (f" {e['time']}" if e.get("time") else "")
        out.append(Entry("Сроки и заседания", "📅", e["title"] or e["kind"],
                         f"{when} · {e['kind']} · {e.get('case_title') or 'без дела'}",
                         lambda cid=e["case_id"]: cid and _open_case(m, cid, "events")))
    return out


def _templates(m):
    out = []
    try:
        base = Path(U.templates_dir())
        __import__("templates_lib").ensure_builtin(str(base))          # встроенные шаблоны — даже если окно шаблонов ещё не открывали
        for p in sorted(base.rglob("*.docx")):
            if p.name.startswith("~$"):
                continue
            cat = " / ".join(x for x in p.parent.relative_to(base).parts if x != "Встроенные") or "Мои шаблоны"
            out.append(Entry("Шаблоны", "📝", p.stem, cat,
                             lambda stem=p.stem: U.tool_template(m, m.mode_cid or m.cases_page.cid, stem),
                             "шаблон документ создать"))
    except Exception as e:
        U.M.log_error("Поиск: шаблоны", e)
    return out


def _help(m):
    out = []
    hp = getattr(m, "help_page", None)
    for s, g, a in getattr(hp, "flat", []):
        where = " › ".join(x.get("title", "") for x in (s, g) if isinstance(x, dict) and x.get("title"))
        out.append(Entry("Справка", "📖", a["title"], f"Справка › {where}" if where else "Справка", lambda aid=a["id"]: (m.show_section(3),
                                                                                    hp.open_article(aid)),
                         H._text(a["html"])[:600]))
    return out


class Palette(QDialog):
    def __init__(self, main):
        super().__init__(main, Qt.FramelessWindowHint | Qt.Dialog)
        self.main = main
        self.setAttribute(Qt.WA_DeleteOnClose)
        T = U.M.T
        self.setObjectName("palette")
        self.setStyleSheet(f"""
            QDialog#palette {{ background: {T['panel']}; border: 1px solid {T['border']}; border-radius: 14px; }}
            QLineEdit#palq {{ font-size: 15pt; padding: 10px 14px; border: none; border-radius: 10px;
                              background: {T['win']}; }}
            QListWidget#pallist {{ border: none; background: transparent; outline: none; }}
            QPushButton#palclose {{ border: none; border-radius: 10px; background: {T['fill']}; color: {T['muted']};
                                   font-size: 13pt; padding: 0; }}
            QPushButton#palclose:hover {{ background: {T['fill_hover']}; color: {T['text']}; }}
            QListWidget#pallist::item {{ padding: 6px 10px; border-radius: 8px; }}
            QListWidget#pallist::item:selected {{ background: {T['accent']}; color: white; }}
        """)
        v = QVBoxLayout(self)
        v.setContentsMargins(12, 12, 12, 10)
        v.setSpacing(8)
        self.q = QLineEdit()
        self.q.setObjectName("palq")
        self.q.setPlaceholderText("🔍  Найти: дело, документ, шаблон, срок, «сжать», «пошлина»…")
        self.q.setClearButtonEnabled(True)
        top = QHBoxLayout()
        top.setSpacing(6)
        top.addWidget(self.q, 1)
        x = QPushButton("✕")
        x.setObjectName("palclose")
        x.setToolTip("Закрыть (Esc)")
        x.setCursor(Qt.PointingHandCursor)
        x.setFixedSize(40, 40)
        x.setFocusPolicy(Qt.NoFocus)
        x.clicked.connect(self.reject)
        top.addWidget(x)
        v.addLayout(top)
        self.list = QListWidget()
        self.list.setObjectName("pallist")
        self.list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.list.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list.setWordWrap(True)
        self.list.itemActivated.connect(self.activate)
        self.list.itemClicked.connect(self.activate)
        v.addWidget(self.list, 1)
        hint = QLabel("↑ ↓ — выбрать · Enter — открыть · Esc, ✕ или щелчок мимо окна — закрыть")
        hint.setObjectName("hint")
        hint.setAlignment(Qt.AlignCenter)
        v.addWidget(hint)
        self.muted = QColor(T["muted"])
        self.entries = {}
        try:
            self.entries = {"Действия": _actions(main), "Дела": _cases(main), "Документы": _docs(main),
                            "Сроки и заседания": _events(main), "Шаблоны": _templates(main), "Справка": _help(main)}
        except Exception as e:
            U.M.log_error("Поиск по всему", e)
        self.q.textChanged.connect(self.refresh)
        self.q.installEventFilter(self)
        w = min(680, max(420, main.width() - 120))
        h = min(560, max(320, main.height() - 140))
        self.resize(w, h)
        g = main.geometry()
        self.move(g.x() + (g.width() - w) // 2, g.y() + 70)
        self.refresh("")
        QTimer.singleShot(0, self.q.setFocus)
        from PySide6.QtWidgets import QApplication
        QApplication.instance().focusWindowChanged.connect(self._focus_moved)

    def _focus_moved(self, win):
        """Фокус ушёл в главное окно (щелчок мимо поиска) — закрыть поиск."""
        try:
            mine = self.windowHandle()
            if self.isVisible() and win is not None and win is not mine:
                QTimer.singleShot(0, self._close_if_inactive)
        except RuntimeError:
            pass

    def done(self, r):
        try:
            from PySide6.QtWidgets import QApplication
            QApplication.instance().focusWindowChanged.disconnect(self._focus_moved)
        except (RuntimeError, TypeError):
            pass
        super().done(r)

    # ------------------------------------------------------------ список
    def _header(self, text):
        it = QListWidgetItem(text.upper())
        it.setFlags(Qt.NoItemFlags)
        f = it.font()
        f.setBold(True)
        f.setPointSize(max(7, f.pointSize() - 1))
        it.setFont(f)
        it.setForeground(self.muted)
        self.list.addItem(it)

    def _add(self, e):
        it = QListWidgetItem(f"{e.icon}   {e.title}" + (f"\n        {e.sub}" if e.sub else ""))
        it.setData(Qt.UserRole, e)
        it.setToolTip(e.sub or e.title)
        self.list.addItem(it)

    def refresh(self, text=None):
        words = [w for w in _norm(self.q.text()).split() if w]
        self.list.clear()
        if not words:                           # пустое поле — подсказки: дела и частые действия
            groups = [("Дела", self.entries.get("Дела", [])[:5]),
                      ("Действия", [e for e in self.entries.get("Действия", [])
                                    if e.title in ("Новое дело", "Главная", "Без дела — просто PDF", "Корзина",
                                                   "Справка")])]
        else:
            groups = []
            for g in ORDER:
                scored = [(e.score(words), i, e) for i, e in enumerate(self.entries.get(g, []))]
                scored = sorted((x for x in scored if x[0] is not None), key=lambda x: (-x[0], x[1]))
                groups.append((g, [e for _s, _i, e in scored[:LIMITS[g]]]))
            # сначала группы, где совпадение лучше всего
            best = {g: max((e.score(words) for e in es), default=0) for g, es in groups}
            groups.sort(key=lambda ge: -best[ge[0]])
        n = 0
        for g, es in groups:
            if not es:
                continue
            self._header(g)
            for e in es:
                self._add(e)
                n += 1
        if not n:
            it = QListWidgetItem("Ничего не найдено. Попробуйте другое слово — например, номер дела или фамилию.")
            it.setFlags(Qt.NoItemFlags)
            it.setForeground(self.muted)
            self.list.addItem(it)
        self._select_from(0, 1)

    def _select_from(self, start, step):
        i = start
        while 0 <= i < self.list.count():
            if self.list.item(i).flags() & Qt.ItemIsEnabled:
                self.list.setCurrentRow(i)
                return
            i += step

    def eventFilter(self, obj, ev):
        if obj is self.q and ev.type() == QEvent.KeyPress:
            k = ev.key()
            if k in (Qt.Key_Down, Qt.Key_Up):
                step = 1 if k == Qt.Key_Down else -1
                self._select_from(self.list.currentRow() + step, step)
                return True
            if k in (Qt.Key_Return, Qt.Key_Enter):
                self.activate(self.list.currentItem())
                return True
            if k == Qt.Key_Escape:
                self.reject()
                return True
        return super().eventFilter(obj, ev)

    def event(self, e):
        # щелчок в любом месте мимо окна (окно перестало быть активным) — закрыть, как обычный поиск
        if e.type() == QEvent.WindowDeactivate and self.isVisible():
            QTimer.singleShot(0, self._close_if_inactive)
        return super().event(e)

    def _close_if_inactive(self):
        try:
            from PySide6.QtWidgets import QApplication
            if self.isVisible() and QApplication.activeWindow() is not self:
                import time
                self.main._palette_closed_at = time.monotonic()
                self.reject()
        except RuntimeError:
            pass

    def activate(self, it):
        e = it.data(Qt.UserRole) if it else None
        if not isinstance(e, Entry):
            return
        self.hide()
        self.accept()
        QTimer.singleShot(0, lambda: _run(self.main, e))


def _run(main, e):
    try:
        e.run()
    except Exception as ex:
        main.error(f"Не удалось открыть «{e.title}»", ex)


def show(main):
    import time
    if time.monotonic() - getattr(main, "_palette_closed_at", -9) < 0.4:
        return None              # щелчок по «Найти…» сам закрыл окно (оно потеряло фокус) — не открывать снова
    old = getattr(main, "_palette", None)
    try:
        if old is not None and old.isVisible():      # повторное Ctrl+K или щелчок по «Найти…» — закрыть
            old.reject()
            return None
    except RuntimeError:
        pass
    p = Palette(main)
    main._palette = p
    p.show()
    p.raise_()
    p.activateWindow()
    return p
