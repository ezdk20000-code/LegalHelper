# -*- coding: utf-8 -*-
"""
Папки в списке дел. У одного доверителя бывает много процессов — они собираются в его папку
(можно и подпапки: «ООО Ромашка» → «Арбитраж», «Исполнительное»). Щелчок по папке разворачивает её,
а справа открывается общая сводка по доверителю: сроки и заседания всех его дел, деньги, список дел
со стадиями, связи между делами, контакты и заметки.

Папки создаются вручную («+ Папка», правый щелчок) — дело можно перетащить в папку мышью. Если у
нескольких дел без папки один и тот же доверитель, вверху списка появляется подсказка собрать их в папку.
"""
import datetime as dt

from PySide6.QtCore import Qt, QTimer, QEvent, QRect, QObject, QSize
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (QStyledItemDelegate, QListWidgetItem, QMenu, QInputDialog, QWidget, QVBoxLayout,
                               QHBoxLayout, QLabel, QPushButton, QScrollArea, QFrame, QListWidget, QPlainTextEdit,
                               QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView, QDialog, QComboBox,
                               QDialogButtonBox, QFormLayout, QMessageBox, QStyle, QSizePolicy)

FOLDER_ROLE = Qt.UserRole + 1          # номер папки (у строки-папки)
DEPTH_ROLE = Qt.UserRole + 2           # глубина вложенности (отступ слева)
HINT_ROLE = Qt.UserRole + 3            # подсказка «собрать дела доверителя в папку»: имя доверителя
COUNT_ROLE = Qt.UserRole + 4           # сколько дел в папке
INDENT = 16
LINK_KINDS = ["Апелляция по этому делу", "Кассация по этому делу", "Встречный иск", "Тот же спор",
              "Исполнительное производство", "Связанный процесс"]

U = None                               # legal_ui (подставляется в bind)


def bind(legal_ui):
    global U
    U = legal_ui


def db():
    return U.db()


def T():
    return U.M.T


# ============================================================================ список
class TreeDelegate(QStyledItemDelegate):
    """Строки списка дел с отступом по вложенности; папки — со стрелкой, значком и числом дел."""

    def paint(self, p, opt, idx):
        depth = idx.data(DEPTH_ROLE) or 0
        fid = idx.data(FOLDER_ROLE)
        opt2 = type(opt)(opt)
        opt2.rect = opt.rect.adjusted(depth * INDENT, 0, 0, 0)
        if fid is None:
            super().paint(p, opt2, idx)
            return
        t = T()
        sel = bool(opt.state & QStyle.State_Selected)
        hover = bool(opt.state & QStyle.State_MouseOver)
        r = opt2.rect.adjusted(0, 1, 0, -1)
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        if sel or hover:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(t["accent"]) if sel else QColor(t["side_hover"]))
            p.drawRoundedRect(r, 10, 10)
        fg = QColor("#ffffff") if sel else QColor(t["text"])
        mut = QColor("#ffffff") if sel else QColor(t["muted"])
        expanded = bool(idx.data(Qt.UserRole + 5))
        f = QFont(opt.font)
        p.setFont(f)
        p.setPen(mut)
        p.drawText(QRect(r.left() + 6, r.top(), 14, r.height()), Qt.AlignVCenter | Qt.AlignLeft, "▾" if expanded else "▸")
        p.setPen(fg)
        p.drawText(QRect(r.left() + 20, r.top(), 22, r.height()), Qt.AlignVCenter | Qt.AlignLeft, "📂" if expanded else "📁")
        f.setBold(True)
        p.setFont(f)
        n = idx.data(COUNT_ROLE) or 0
        badge = str(n)
        fm = p.fontMetrics()
        bw = fm.horizontalAdvance(badge) + 14
        name = fm.elidedText(idx.data(Qt.DisplayRole) or "", Qt.ElideRight, max(20, r.width() - 46 - bw - 10))
        p.drawText(QRect(r.left() + 44, r.top(), r.width() - 54 - bw, r.height()), Qt.AlignVCenter | Qt.AlignLeft, name)
        br = QRect(r.right() - bw - 6, r.center().y() - 9, bw, 18)
        p.setPen(Qt.NoPen)
        c = QColor("#ffffff") if sel else QColor(t["accent"])
        c.setAlpha(60 if sel else 34)
        p.setBrush(c)
        p.drawRoundedRect(br, 9, 9)
        f.setPointSizeF(max(7.0, f.pointSizeF() - 1.5))
        p.setFont(f)
        p.setPen(QColor("#ffffff") if sel else QColor(t["accent"]))
        p.drawText(br, Qt.AlignCenter, badge)
        p.restore()

    def sizeHint(self, opt, idx):
        s = super().sizeHint(opt, idx)
        if idx.data(FOLDER_ROLE) is not None:
            return QSize(s.width(), max(36, s.height()))
        depth = idx.data(DEPTH_ROLE) or 0
        if depth:                                    # отступ слева съедает ширину — строка выше из-за переноса
            o = type(opt)(opt)
            o.rect = opt.rect.adjusted(depth * INDENT, 0, 0, 0)
            s2 = super().sizeHint(o, idx)
            return QSize(s.width(), max(s.height(), s2.height()))
        return s


def setup_list(page):
    """Список дел: отступы, перетаскивание дел в папки, правый щелчок."""
    lst = page.list
    lst.setItemDelegate(TreeDelegate(lst))
    lst.setMouseTracking(True)
    lst.setDragEnabled(True)
    lst.setAcceptDrops(True)
    lst.viewport().setAcceptDrops(True)
    lst.setDragDropMode(QAbstractItemView.DragDrop)
    lst.setDefaultDropAction(Qt.MoveAction)
    lst.setContextMenuPolicy(Qt.CustomContextMenu)
    lst.customContextMenuRequested.connect(lambda pos: context_menu(page, pos))
    page._dnd = _DropFilter(page)
    lst.viewport().installEventFilter(page._dnd)


def _count(fid, by_folder, children):
    n = len(by_folder.get(fid, []))
    for ch in children.get(fid, []):
        n += _count(ch["id"], by_folder, children)
    return n


def fill(page, cases, cur_cid, cur_fid):
    """Заполнить список: подсказка (если есть), папки с делами (развёрнутые — с содержимым), дела без папки."""
    lst = page.list
    folders = db().folders()
    fids = {f["id"] for f in folders}
    children, by_folder = {}, {}
    for f in folders:
        parent = f["parent_id"] if f["parent_id"] in fids else None
        children.setdefault(parent, []).append(f)
    for c in cases:
        fid = c.get("folder_id") if c.get("folder_id") in fids else None
        by_folder.setdefault(fid, []).append(c)
    archived = page.show_arch.isChecked()
    sel_item = None

    hint = suggestion(page, by_folder.get(None, []))
    if hint and not archived:
        it = QListWidgetItem(f"💡  У «{hint[0]}» {hint[1]} {U.L.plural(hint[1], 'дело', 'дела', 'дел')} без папки — "
                             "собрать их в папку доверителя?")
        it.setData(HINT_ROLE, hint[0])
        it.setForeground(QColor(T()["accent"]))
        it.setToolTip("Щёлкните — программа создаст папку и перенесёт туда дела. Правый щелчок — скрыть подсказку.")
        lst.addItem(it)

    def case_item(c, depth):
        nonlocal sel_item
        sub = " · ".join(x for x in (c["number"], c["client"] if depth == 0 else "", c["stage"]) if x)
        it = QListWidgetItem(c["title"] + (f"\n{sub}" if sub else ""))
        it.setData(Qt.UserRole, c["id"])
        it.setData(DEPTH_ROLE, depth)
        lst.addItem(it)
        if c["id"] == cur_cid:
            sel_item = it

    def folder_rows(parent, depth):
        nonlocal sel_item
        for f in children.get(parent, []):
            n = _count(f["id"], by_folder, children)
            if archived and not n:
                continue
            it = QListWidgetItem(f["name"])
            it.setData(FOLDER_ROLE, f["id"])
            it.setData(DEPTH_ROLE, depth)
            it.setData(COUNT_ROLE, n)
            it.setData(Qt.UserRole + 5, bool(f["expanded"]))
            it.setToolTip(f"{f['name']}: {n} {U.L.plural(n, 'дело', 'дела', 'дел')}. Щелчок — сводка по папке, "
                          "повторный щелчок — свернуть. Дела можно перетаскивать в папку мышью.")
            lst.addItem(it)
            if f["id"] == cur_fid and not cur_cid:
                sel_item = it
            if f["expanded"]:
                folder_rows(f["id"], depth + 1)
                for c in by_folder.get(f["id"], []):
                    case_item(c, depth + 1)
    folder_rows(None, 0)
    for c in by_folder.get(None, []):
        case_item(c, 0)
    return sel_item


def suggestion(page, loose_cases):
    """Доверитель, у которого 2+ дела без папки (и подсказку для него не скрывали)."""
    hidden = set((U.M.settings().value("folder_hint_hidden", "") or "").split("\x1f"))
    names = {f["name"].strip().lower() for f in db().folders()}
    count = {}
    for c in loose_cases:
        cl = (c.get("client") or "").strip()
        if cl and cl.lower() not in names and cl not in hidden:
            count[cl] = count.get(cl, 0) + 1
    best = max(count.items(), key=lambda kv: kv[1], default=None)
    return best if best and best[1] >= 2 else None


def apply_hint(page, client):
    fid = db().add_folder(client)
    for c in db().cases(False) + db().cases(True):
        if (c.get("client") or "").strip() == client and not c.get("folder_id"):
            db().set_case_folder(c["id"], fid)
    page.cur_fid = fid
    page.reload()
    page.main.toast(f"📁  Папка «{client}»: дела доверителя собраны вместе")
    if hasattr(page.main, "show_folder"):
        page.main.show_folder(fid)


def hide_hint(client):
    s = U.M.settings()
    cur = [x for x in (s.value("folder_hint_hidden", "") or "").split("\x1f") if x]
    s.setValue("folder_hint_hidden", "\x1f".join(cur + [client]))


# ---------------------------------------------------------------------------- действия
def new_folder(page, parent=None):
    name, ok = QInputDialog.getText(page, "Новая папка", "Название папки (например, имя доверителя):")
    if not ok or not name.strip():
        return None
    fid = db().add_folder(name.strip(), parent)
    if parent:
        db().update_folder(parent, expanded=1)
    page.cur_fid = fid
    page.reload()
    if hasattr(page.main, "show_folder"):
        page.main.show_folder(fid)
    return fid


def rename_folder(page, fid):
    f = db().folder(fid)
    if not f:
        return
    name, ok = QInputDialog.getText(page, "Переименовать папку", "Новое название:", text=f["name"])
    if ok and name.strip():
        db().update_folder(fid, name=name.strip())
        page.reload()
        if hasattr(page.main, "folder_page"):
            page.main.folder_page.refresh()


def delete_folder(page, fid):
    f = db().folder(fid)
    if not f:
        return
    n = len(db().folder_cases(fid))
    if QMessageBox.question(page, "Удалить папку", f"Удалить папку «{f['name']}»?\n\nДела ({n}) и подпапки не "
                            "удаляются — они переместятся на уровень выше.") != QMessageBox.Yes:
        return
    db().delete_folder(fid)
    page.cur_fid = None
    page.reload()
    if hasattr(page.main, "show_home") and getattr(page.main, "folder_page", None) and \
            page.main.stack.currentWidget() is page.main.folder_page:
        page.main.show_home()


def move_case(page, cid, fid):
    db().set_case_folder(cid, fid)
    if fid:
        db().update_folder(fid, expanded=1)
    page.reload()
    f = db().folder(fid)
    page.main.toast(f"📁  Дело перенесено в «{f['name']}»" if f else "Дело вынесено из папки")
    fp = getattr(page.main, "folder_page", None)
    if fp is not None and fp.isVisible():
        fp.refresh()


def _move_menu(page, menu, cid):
    sub = menu.addMenu("📁  Переместить в папку")
    cur = (db().case(cid) or {}).get("folder_id")
    folders = db().folders()
    by_id = {f["id"]: f for f in folders}

    def path(f):
        parts, seen = [f["name"]], {f["id"]}
        while f["parent_id"] in by_id and f["parent_id"] not in seen:
            f = by_id[f["parent_id"]]
            seen.add(f["id"])
            parts.insert(0, f["name"])
        return " › ".join(parts)
    for f in sorted(folders, key=path):
        a = sub.addAction(("✓  " if f["id"] == cur else "") + path(f))
        a.triggered.connect(lambda _=False, fid=f["id"]: move_case(page, cid, fid))
    if folders:
        sub.addSeparator()

    def new_and_move():
        fid = new_folder(page)
        if fid:
            move_case(page, cid, fid)
    sub.addAction("+ Новая папка…").triggered.connect(new_and_move)
    if cur:
        sub.addAction("Вынести из папки").triggered.connect(lambda: move_case(page, cid, None))


def context_menu(page, pos):
    lst = page.list
    it = lst.itemAt(pos)
    m = QMenu(page)
    if it is not None and it.data(HINT_ROLE):
        client = it.data(HINT_ROLE)
        m.addAction(f"📁  Собрать дела «{client}» в папку").triggered.connect(lambda: apply_hint(page, client))
        m.addAction("Скрыть эту подсказку").triggered.connect(lambda: (hide_hint(client), page.reload()))
    elif it is not None and it.data(FOLDER_ROLE) is not None:
        fid = it.data(FOLDER_ROLE)
        m.addAction("➕  Новое дело в этой папке").triggered.connect(lambda: page.new_case(folder_id=fid))
        m.addAction("📁  Новая подпапка…").triggered.connect(lambda: new_folder(page, fid))
        m.addSeparator()
        m.addAction("✏️  Переименовать…").triggered.connect(lambda: rename_folder(page, fid))
        m.addAction("🗑  Удалить папку (дела останутся)").triggered.connect(lambda: delete_folder(page, fid))
    elif it is not None and it.data(Qt.UserRole):
        cid = it.data(Qt.UserRole)
        _move_menu(page, m, cid)
        m.addSeparator()
        m.addAction("🗑  Удалить дело").triggered.connect(lambda: page.delete_case(cid))
    else:
        m.addAction("📁  Новая папка…").triggered.connect(lambda: new_folder(page))
        m.addAction("➕  Новое дело").triggered.connect(lambda: page.new_case())
    m.exec(lst.viewport().mapToGlobal(pos))


class _DropFilter(QObject):
    """Перетаскивание внутри списка: дело (или папку) — в папку. Файлы из проводника не перехватываются."""

    def __init__(self, page):
        super().__init__(page)
        self.page = page

    def eventFilter(self, obj, e):
        t = e.type()
        if t not in (QEvent.DragEnter, QEvent.DragMove, QEvent.Drop):
            return False
        lst = self.page.list
        if e.source() is not lst:                    # файлы и прочее — пусть обрабатывает окно, как раньше
            e.ignore()
            return True
        if t in (QEvent.DragEnter, QEvent.DragMove):
            e.setDropAction(Qt.MoveAction)
            e.accept()
            return True
        src = lst.currentItem()
        target = lst.itemAt(e.position().toPoint() if hasattr(e, "position") else e.pos())
        e.setDropAction(Qt.IgnoreAction)             # сами переносим — список не должен переставлять строки
        e.accept()
        if src is None:
            return True
        tf = None
        if target is not None:
            if target.data(FOLDER_ROLE) is not None:
                tf = target.data(FOLDER_ROLE)
            elif target.data(Qt.UserRole):
                tf = (db().case(target.data(Qt.UserRole)) or {}).get("folder_id")
        page = self.page
        if src.data(Qt.UserRole):
            cid = src.data(Qt.UserRole)
            if (db().case(cid) or {}).get("folder_id") != tf:
                QTimer.singleShot(0, lambda: move_case(page, cid, tf))
        elif src.data(FOLDER_ROLE) is not None:
            fid = src.data(FOLDER_ROLE)
            if fid != tf:
                def mv():
                    if db().move_folder(fid, tf):
                        if tf:
                            db().update_folder(tf, expanded=1)
                        page.reload()
                    else:
                        page.main.toast("Папку нельзя положить в её же подпапку")
                QTimer.singleShot(0, mv)
        return True


# ============================================================================ сводка по папке
def _box(title):
    box = QFrame()
    box.setObjectName("card")
    v = QVBoxLayout(box)
    v.setContentsMargins(16, 12, 16, 14)
    v.setSpacing(8)
    lab = QLabel(title)
    lab.setObjectName("subtitle")
    v.addWidget(lab)
    return box, v


class LinkDialog(QDialog):
    """Связать два дела: апелляция по этому делу, встречный иск, тот же спор…"""

    def __init__(self, parent, cases, a=None):
        super().__init__(parent)
        self.setWindowTitle("Связать дела")
        self.setMinimumWidth(520)
        lay = QVBoxLayout(self)
        note = QLabel("Связь видна в сводке папки и в обоих делах: например, апелляция по делу первой инстанции "
                      "или встречный иск.")
        note.setWordWrap(True)
        note.setObjectName("hint")
        lay.addWidget(note)
        form = QFormLayout()
        self.a, self.b = QComboBox(), QComboBox()
        for box in (self.a, self.b):
            for c in cases:
                box.addItem(c["title"] + (f"  ({c['number']})" if c["number"] else ""), c["id"])
        if a is not None:
            self.a.setCurrentIndex(max(0, self.a.findData(a)))
        if self.b.count() > 1 and self.b.currentIndex() == self.a.currentIndex():
            self.b.setCurrentIndex(1 if self.a.currentIndex() == 0 else 0)
        self.kind = QComboBox()
        self.kind.setEditable(True)
        self.kind.addItems(LINK_KINDS)
        form.addRow("Дело", self.a)
        form.addRow("Связано с", self.b)
        form.addRow("Как связаны", self.kind)
        lay.addLayout(form)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Связать")
        bb.button(QDialogButtonBox.Cancel).setText("Отмена")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def value(self):
        return self.a.currentData(), self.b.currentData(), self.kind.currentText().strip()


class FolderPage(QWidget):
    """Сводка по папке (доверителю): всё по всем его делам на одном экране."""

    def __init__(self, main):
        super().__init__()
        self.main = main
        self.fid = None
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setFrameShape(QFrame.NoFrame)
        outer.addWidget(sc)
        body = QWidget()
        sc.setWidget(body)
        v = QVBoxLayout(body)
        v.setContentsMargins(26, 20, 26, 20)
        v.setSpacing(14)
        head = QHBoxLayout()
        self.title = QLabel()
        self.title.setObjectName("title")
        self.title.setWordWrap(True)
        head.addWidget(self.title, 1)
        b_new = QPushButton("➕  Новое дело в папке")
        b_new.setObjectName("primary")
        b_new.clicked.connect(lambda: self.main.cases_page.new_case(folder_id=self.fid))
        b_sub = QPushButton("📁  Подпапка")
        b_sub.clicked.connect(lambda: new_folder(self.main.cases_page, self.fid))
        b_ren = QPushButton("Переименовать")
        b_ren.clicked.connect(lambda: rename_folder(self.main.cases_page, self.fid))
        b_del = QPushButton("Удалить папку")
        b_del.setProperty("danger", True)
        b_del.clicked.connect(lambda: delete_folder(self.main.cases_page, self.fid))
        for b in (b_new, b_sub, b_ren, b_del):
            b.setCursor(Qt.PointingHandCursor)
            head.addWidget(b, 0, Qt.AlignTop)
        v.addLayout(head)
        self.sub = QLabel()
        self.sub.setObjectName("hint")
        v.addWidget(self.sub)
        tiles = QHBoxLayout()
        tiles.setSpacing(12)
        self.t_cases = U.StatTile("📁", "дел в работе", lambda: self.l_cases.setFocus())
        self.t_next = U.StatTile("📅", "ближайшее событие", lambda: self.l_events.setFocus())
        self.t_over = U.StatTile("🔥", "просрочено", lambda: self.l_events.setFocus())
        self.t_money = U.StatTile("💰", "долг доверителя", lambda: None)
        for t in (self.t_cases, self.t_next, self.t_over, self.t_money):
            tiles.addWidget(t)
        v.addLayout(tiles)

        row = QHBoxLayout()
        row.setSpacing(12)
        box, bv = _box("🗓  Сроки и заседания по всем делам")
        self.l_events = QListWidget()
        self.l_events.setObjectName("overlist")
        self.l_events.setWordWrap(True)
        self.l_events.setMinimumHeight(220)
        self.l_events.itemClicked.connect(self._open_event)
        bv.addWidget(self.l_events, 1)
        row.addWidget(box, 3)
        box, bv = _box("💰  Деньги")
        self.money = QTableWidget(0, 4)
        self.money.setHorizontalHeaderLabels(["Дело", "Начислено", "Оплачено", "Долг"])
        self.money.verticalHeader().hide()
        self.money.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.money.setSelectionMode(QAbstractItemView.NoSelection)
        self.money.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        for k in (1, 2, 3):
            self.money.horizontalHeader().setSectionResizeMode(k, QHeaderView.ResizeToContents)
        self.money.setMinimumHeight(220)
        self.money.setWordWrap(True)
        bv.addWidget(self.money, 1)
        row.addWidget(box, 2)
        v.addLayout(row)

        box, bv = _box("📚  Дела доверителя")
        self.l_cases = QListWidget()
        self.l_cases.setObjectName("overlist")
        self.l_cases.setWordWrap(True)
        self.l_cases.setMinimumHeight(160)
        self.l_cases.itemClicked.connect(self._open_case)
        bv.addWidget(self.l_cases)
        v.addWidget(box)

        row2 = QHBoxLayout()
        row2.setSpacing(12)
        box, bv = _box("🔗  Связанные дела")
        hint = QLabel("Апелляция по этому же делу, встречный иск, исполнительное производство — свяжите дела, "
                      "чтобы видеть их вместе.")
        hint.setWordWrap(True)
        hint.setObjectName("hint")
        bv.addWidget(hint)
        self.l_links = QListWidget()
        self.l_links.setObjectName("overlist")
        self.l_links.setWordWrap(True)
        self.l_links.setMinimumHeight(120)
        self.l_links.itemClicked.connect(self._open_case)
        self.l_links.setContextMenuPolicy(Qt.CustomContextMenu)
        self.l_links.customContextMenuRequested.connect(self._link_menu)
        bv.addWidget(self.l_links, 1)
        lb = QHBoxLayout()
        b_link = QPushButton("+ Связать дела")
        b_link.clicked.connect(self.add_link)
        lb.addWidget(b_link)
        lb.addStretch(1)
        bv.addLayout(lb)
        row2.addWidget(box, 1)
        box, bv = _box("👤  Контакты и заметки о доверителе")
        cl = QLabel("Контакты (телефон, e-mail, представитель, реквизиты)")
        cl.setObjectName("hint")
        bv.addWidget(cl)
        self.contacts = QPlainTextEdit()
        self.contacts.setPlaceholderText("Иванов Иван, директор · +7 900 000-00-00 · ivanov@romashka.ru")
        self.contacts.setFixedHeight(80)
        bv.addWidget(self.contacts)
        nl = QLabel("Общие заметки по всем делам")
        nl.setObjectName("hint")
        bv.addWidget(nl)
        self.notes = QPlainTextEdit()
        self.notes.setPlaceholderText("Особенности доверителя, договорённости, общая позиция…")
        self.notes.setMinimumHeight(90)
        bv.addWidget(self.notes, 1)
        row2.addWidget(box, 1)
        v.addLayout(row2)
        v.addStretch(1)
        self.save_timer = QTimer(self)
        self.save_timer.setSingleShot(True)
        self.save_timer.setInterval(700)
        self.save_timer.timeout.connect(self.save_notes)
        self.contacts.textChanged.connect(lambda: self._loading or self.save_timer.start())
        self.notes.textChanged.connect(lambda: self._loading or self.save_timer.start())
        self._loading = False

    # ---- данные
    def set_folder(self, fid):
        if self.save_timer.isActive():
            self.save_timer.stop()
            self.save_notes()
        self.fid = fid
        self.refresh()

    def save_notes(self):
        if self.fid and db().folder(self.fid):
            db().update_folder(self.fid, contacts=self.contacts.toPlainText(), notes=self.notes.toPlainText())

    def refresh(self):
        f = db().folder(self.fid)
        if not f:
            return
        today = dt.date.today()
        self.title.setText(f"📁  {f['name']}")
        cases = db().folder_cases(self.fid, archived=False)
        arch = db().folder_cases(self.fid, archived=True)
        subs = [x for x in db().folders() if x["parent_id"] == self.fid]
        parts = [f"{len(cases)} {U.L.plural(len(cases), 'дело', 'дела', 'дел')} в работе"]
        if arch:
            parts.append(f"{len(arch)} в архиве")
        if subs:
            parts.append(f"подпапки: {', '.join(s['name'] for s in subs)}")
        self.sub.setText(" · ".join(parts))
        ids = {c["id"] for c in cases}
        events = [e for e in db().events(include_done=False) if e["case_id"] in ids]
        over = [e for e in events if e["date"] < today.isoformat() and e["kind"] != U.CS.CaseDB.REMINDER]
        upcoming = sorted((e for e in events if e["date"] >= today.isoformat()), key=lambda e: (e["date"], e["time"] or ""))
        self.t_cases.set(str(len(cases)))
        self.t_over.set(str(len(over)), T()["danger"] if over else None)
        nd = dt.date.fromisoformat(upcoming[0]["date"]) if upcoming else None
        self.t_next.set(f"{nd.day:02d}.{nd.month:02d}" if nd else "—")
        # события
        self.l_events.clear()
        for e in sorted(over, key=lambda e: e["date"]) + upcoming:
            d = dt.date.fromisoformat(e["date"])
            left = (d - today).days
            when = ("сегодня" if left == 0 else "завтра" if left == 1 else
                    f"просрочено {U.CS.ru(e['date'])}" if left < 0 else U.CS.ru(e["date"]))
            t = f" {e['time']}" if e["time"] else ""
            it = QListWidgetItem(f"{U.KIND_ICON.get(e['kind'], '•')}  {e['title'] or e['kind']}\n"
                                 f"     {when}{t} · {e['case_title']}")
            it.setData(Qt.UserRole, e["case_id"])
            if left < 0 or (left <= 2 and e["kind"] in ("Срок", "Заседание")):
                it.setForeground(QColor(T()["danger"]))
            self.l_events.addItem(it)
        if not self.l_events.count():
            self._empty(self.l_events, "Сроков и заседаний нет")
        # деньги
        rows = []
        for c in cases + arch:
            b = db().balance(c["id"])
            if b["billed"] or b["paid"]:
                rows.append((c["title"], b))
        self.money.setRowCount(len(rows) + (1 if rows else 0))
        tot = {"billed": 0.0, "paid": 0.0, "due": 0.0}
        for r, (title, b) in enumerate(rows):
            ti = QTableWidgetItem(title)
            ti.setToolTip(title)
            self.money.setItem(r, 0, ti)
            for k, key in enumerate(("billed", "paid", "due"), 1):
                it = QTableWidgetItem(f"{U.L.money(b[key], cents=False)} ₽")
                it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                if key == "due" and b[key] > 0:
                    it.setForeground(QColor(T()["danger"]))
                self.money.setItem(r, k, it)
                tot[key] += b[key]
        if rows:
            r = len(rows)
            it = QTableWidgetItem("Итого")
            fb = it.font()
            fb.setBold(True)
            it.setFont(fb)
            self.money.setItem(r, 0, it)
            for k, key in enumerate(("billed", "paid", "due"), 1):
                it = QTableWidgetItem(f"{U.L.money(tot[key], cents=False)} ₽")
                it.setFont(fb)
                it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.money.setItem(r, k, it)
        self.money.resizeRowsToContents()
        due = max(0.0, tot["due"])
        self.t_money.set(f"{U.L.money(due, cents=False)} ₽" if due else "0 ₽", T()["danger"] if due else None)
        # дела
        nexts = {}
        for e in upcoming:
            nexts.setdefault(e["case_id"], e)
        self.l_cases.clear()
        for c in cases + arch:
            info = " · ".join(x for x in (c["number"], c["court"], c["stage"]) if x)
            ne = nexts.get(c["id"])
            extra = f"\n     ближайшее: {U.CS.ru(ne['date'])} {ne['time'] or ''} {ne['title'] or ne['kind']}" if ne else ""
            it = QListWidgetItem(f"{'🗄' if c['archived'] else '⚖️'}  {c['title']}\n     {info or 'без номера'}{extra}")
            it.setData(Qt.UserRole, c["id"])
            if c["archived"]:
                it.setForeground(QColor(T()["muted"]))
            self.l_cases.addItem(it)
        if not self.l_cases.count():
            self._empty(self.l_cases, "В папке пока нет дел — «➕ Новое дело в папке» или перетащите дело в папку слева")
        # связи
        self.l_links.clear()
        all_ids = ids | {c["id"] for c in arch}
        seen = set()
        for cid in all_ids:
            for l in db().links(cid):
                if l["id"] in seen:
                    continue
                seen.add(l["id"])
                a, b = db().case(l["a"]) or {}, db().case(l["b"]) or {}
                it = QListWidgetItem(f"🔗  {a.get('title', '?')}  ⇄  {b.get('title', '?')}"
                                     + (f"\n     {l['note']}" if l["note"] else ""))
                it.setData(Qt.UserRole, l["b"] if l["a"] in all_ids else l["a"])
                it.setData(Qt.UserRole + 1, l["id"])
                it.setToolTip("Щелчок — открыть связанное дело. Правый щелчок — убрать связь.")
                self.l_links.addItem(it)
        if not self.l_links.count():
            self._empty(self.l_links, "Связей пока нет")
        self._loading = True
        self.contacts.setPlainText(f.get("contacts") or "")
        self.notes.setPlainText(f.get("notes") or "")
        self._loading = False

    @staticmethod
    def _empty(lst, text):
        it = QListWidgetItem(text)
        it.setFlags(Qt.NoItemFlags)
        it.setForeground(QColor(T()["muted"]))
        lst.addItem(it)

    # ---- действия
    def _open_case(self, it):
        cid = it.data(Qt.UserRole)
        if cid:
            self.main.enter_case(cid)
            self.main.open_case_tab("overview")

    def _open_event(self, it):
        cid = it.data(Qt.UserRole)
        if cid:
            self.main.enter_case(cid)
            self.main.open_case_tab("events")

    def add_link(self):
        cases = db().folder_cases(self.fid) if self.fid else []
        others = [c for c in db().cases(False) + db().cases(True) if c["id"] not in {x["id"] for x in cases}]
        allc = cases + others
        if len(allc) < 2:
            QMessageBox.information(self, "Связать дела", "Для связи нужно хотя бы два дела.")
            return
        d = LinkDialog(self, allc, cases[0]["id"] if cases else None)
        if d.exec() == QDialog.Accepted:
            a, b, note = d.value()
            if a == b:
                QMessageBox.information(self, "Связать дела", "Выберите два разных дела.")
                return
            if db().add_link(a, b, note) is None:
                self.main.toast("Эти дела уже связаны")
            self.refresh()

    def _link_menu(self, pos):
        it = self.l_links.itemAt(pos)
        if it is None or not it.data(Qt.UserRole + 1):
            return
        m = QMenu(self)
        m.addAction("Открыть связанное дело").triggered.connect(lambda: self._open_case(it))
        m.addAction("Убрать связь").triggered.connect(
            lambda: (db().delete_link(it.data(Qt.UserRole + 1)), self.refresh()))
        m.exec(self.l_links.viewport().mapToGlobal(pos))
