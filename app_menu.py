# -*- coding: utf-8 -*-
"""
Меню программы (кнопка ☰): вместо старого выпадающего списка «как в Windows 98» — панель-карточка.
Слева разделы (Файл, Правка, Вид, Инструменты, Юристу, Справка), справа — их команды крупно,
с пояснением и сочетанием клавиш. Сверху поиск по всем командам, темы оформления — цветными кружками.
Пункты берутся из обычного QMenu программы, поэтому всё, что добавлено в меню, появляется и здесь.
"""
import re

from PySide6.QtCore import Qt, QTimer, QPoint, QRectF, QEvent, QObject
from PySide6.QtGui import QColor, QPainter, QPen, QBrush, QKeySequence
from PySide6.QtWidgets import (QFrame, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QLineEdit, QPushButton,
                               QScrollArea, QWidget, QGraphicsDropShadowEffect, QApplication, QSizePolicy)

SECTION_ICONS = {"Файл": "📄", "Правка": "✏️", "Вид": "🎨", "Инструменты": "🧰", "Юристу": "⚖️", "Справка": "💬"}
SECTION_HINTS = {"Файл": "Открыть, сохранить, копии", "Правка": "Отмена, страницы, корзина",
                 "Вид": "Тема, вкладки, панель", "Инструменты": "Всё для PDF", "Юристу": "Пакеты, описи, расчёты",
                 "Справка": "Обучение, обновления"}
GROUP_ICONS = {"Страницы": "📑", "Редактирование": "🖊", "Оптимизация": "⚡", "Конвертировать в PDF": "⤵",
               "Конвертировать из PDF": "⤴", "Защита и сравнение": "🔒", "Тема оформления": "🎨"}
ITEM_ICONS = {"Открыть": "📂", "Добавить": "➕", "Сохранить": "💾", "Сохранить как…": "🗂",
              "Новый (пустой) документ": "📄", "Закрыть документ": "✖", "Выход": "🚪",
              "Отменить": "↶", "Повторить": "↷", "Выделить всё": "☑", "Удалить": "🗑", "Дублировать": "⧉",
              "Пустая страница": "▭", "Извлечь": "📤", "Обзор дела": "📋", "Документы": "📚",
              "Создать документ": "📝", "Сроки": "⏰", "Деньги": "💰", "Сведения": "ℹ", "Левая панель": "◧",
              "Анимации": "✨", "Главная": "🏠", "Без дела — просто PDF": "📂", "Дела и сроки": "📁",
              "Шаблоны документов…": "📝", "Карта дела (Excalidraw)": "🗺", "Мои реквизиты…": "👤",
              "Пакет в суд / на почту": "📦", "Опись вложения (ф. 107)": "📮", "Нумерация листов дела": "🔢",
              "Штамп «Копия верна»": "🖃", "Проверка перед подачей": "✅", "Обезличить (152-ФЗ)": "🕶",
              "Сравнить редакции": "⚖", "Карта дела (схема)": "🗺", "Поиск по документам дела": "🔎",
              "Выписка с номером листа": "📎", "Документ по шаблону": "📝", "Процессуальные сроки": "📅",
              "Госпошлина": "🏛", "Проценты ст. 395 ГК и неустойка": "％", "Руководство пользователя": "📖",
              "Как пользоваться": "💡", "Проверить обновления…": "⬇", "Проверять обновления при запуске": "🔔",
              "Установить обновление из архива…": "🗜", "Проверить часы компьютера…": "🕒",
              "Вернуть предыдущую версию программы…": "⏪", "Создать ярлык на рабочем столе": "🖥",
              "Журнал ошибок": "🧾", "О программе": "ⓘ"}
EMOJI_HEAD = re.compile(r"^([^\w\s«(\"'№%]+)\s*")


def _norm(s):
    return (s or "").lower().replace("ё", "е")


def _clean(text):
    return text.replace("&&", "\0").replace("&", "").replace("\0", "&").strip()


def _split(a):
    """(значок, название, пояснение) для пункта меню."""
    text = _clean(a.text())
    tip = re.sub(r"\s*\((Ctrl|Del|F\d|Shift)[^)]*\)?\s*$", "", (a.toolTip() or "").strip())
    icon = ""
    m = EMOJI_HEAD.match(text)
    if m and len(text) > len(m.group(0)):
        icon, text = m.group(1), text[m.end():]
    elif m:                                   # пункт-значок (↺ ↻): название — из подсказки
        icon, text, tip = text, tip or text, ""
    icon = icon or ITEM_ICONS.get(text, "")
    tip_c = re.sub(EMOJI_HEAD, "", tip)
    sub = tip if tip and _norm(tip_c).rstrip("…. ") != _norm(text).rstrip("…. ") else ""
    return icon, text.rstrip(), sub


class Swatch(QPushButton):
    """Кружок темы оформления: фон и акцент темы; выбранная — с кольцом."""

    def __init__(self, a, colors, t):
        super().__init__()
        self.a, self.colors, self.t = a, colors, t
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(58, 58)
        self.setToolTip(_clean(a.text()))
        self.setStyleSheet("QPushButton { border: none; background: transparent; }")

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(9, 5, 40, 40)
        on = self.a.isChecked()
        if on or self.underMouse() or self.hasFocus():
            p.setPen(QPen(QColor(self.t["accent"] if on else self.t["muted"]), 2.2))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(r.adjusted(-4, -4, 4, 4))
        cols = self.colors
        p.setPen(QPen(QColor(self.t["border"]), 1))
        if len(cols) == 3:                       # «Как в Windows»: половина светлая, половина тёмная
            p.setBrush(QColor(cols[0]))
            p.drawPie(r, 90 * 16, 180 * 16)
            p.setBrush(QColor(cols[1]))
            p.drawPie(r, 270 * 16, 180 * 16)
            acc = cols[2]
        else:
            p.setBrush(QColor(cols[0]))
            p.drawEllipse(r)
            acc = cols[1]
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(acc))
        p.drawEllipse(r.center(), 7, 7)
        if on:
            p.setPen(QPen(QColor("#ffffff"), 1.8))
            c = r.center()
            p.drawPolyline([c + QPoint(-3, 0), c + QPoint(-1, 2), c + QPoint(3, -2)])
        p.end()


class AppMenu(QFrame):
    last_section = None

    def __init__(self, win, menu, theme, swatch=None, footer=""):
        super().__init__(win, Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        self.win, self.menu, self.t, self.swatch = win, menu, theme, swatch or (lambda text: None)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.sections = [a for a in menu.actions() if a.menu() and a.isVisible()]
        self.rows = []
        t = theme
        dark = QColor(t["panel"]).lightness() < 128
        self.setStyleSheet(f"""
            #card {{ background: {t['panel']}; border: 1px solid {t['border']}; border-radius: 16px; }}
            #rail {{ background: {t['side']}; border-top-left-radius: 16px; border-bottom-left-radius: 16px;
                     border-right: 1px solid {t['border']}; }}
            QLabel {{ background: transparent; color: {t['text']}; }}
            #brand {{ font-size: 15px; font-weight: 700; padding: 2px 6px 8px 6px; }}
            #sec {{ text-align: left; border: none; border-radius: 10px; padding: 8px 10px; background: transparent;
                    color: {t['text']}; font-size: 13px; }}
            #sec:hover {{ background: {t['side_hover']}; }}
            #sec:checked {{ background: {t['accent_soft']}; color: {t['accent']}; font-weight: 600; }}
            #search {{ border: 1px solid {t['input_border']}; border-radius: 10px; padding: 8px 12px;
                       font-size: 14px; background: {t['base']}; color: {t['text']}; }}
            #search:focus {{ border: 1.5px solid {t['accent']}; }}
            #title {{ font-size: 20px; font-weight: 700; }}
            #hint {{ color: {t['muted']}; font-size: 12px; }}
            #group {{ color: {t['muted']}; font-size: 11px; font-weight: 700; letter-spacing: 1px;
                      padding: 10px 2px 2px 2px; }}
            #line {{ background: {t['border']}; max-height: 1px; min-height: 1px; }}
            #row, #tile {{ text-align: left; border: 1px solid transparent; border-radius: 10px;
                           background: transparent; padding: 0; }}
            #tile {{ border: 1px solid {t['border']}; background: {t['alt']}; }}
            #row:hover, #row:focus, #tile:hover, #tile:focus {{ background: {t['hover']}; border-color: {t['border']}; }}
            #tile:hover, #tile:focus {{ border-color: {t['accent']}; }}
            #row:disabled, #tile:disabled {{ background: transparent; }}
            #ico {{ font-size: 16px; min-width: 26px; max-width: 26px; }}
            #name {{ font-size: 13px; }}
            #sub {{ color: {t['muted']}; font-size: 11px; }}
            #key {{ color: {t['muted']}; font-size: 11px; border: 1px solid {t['border']}; border-radius: 6px;
                    padding: 1px 6px; background: {t['base']}; }}
            #path {{ color: {t['accent']}; font-size: 11px; }}
            #foot {{ color: {t['muted']}; font-size: 11px; }}
            QScrollBar:vertical {{ background: transparent; width: 8px; margin: 2px; }}
            QScrollBar::handle:vertical {{ background: {t['fill_hover']}; border-radius: 3px; min-height: 30px; }}
            QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
            QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
            QScrollArea {{ background: transparent; border: none; }}
            QScrollArea > QWidget > QWidget {{ background: transparent; }}
        """)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 14, 18, 22)
        card = QFrame()
        card.setObjectName("card")
        sh = QGraphicsDropShadowEffect(card)
        sh.setBlurRadius(42)
        sh.setOffset(0, 12)
        sh.setColor(QColor(0, 0, 0, 150 if dark else 60))
        card.setGraphicsEffect(sh)
        outer.addWidget(card)
        h = QHBoxLayout(card)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)

        rail = QFrame()
        rail.setObjectName("rail")
        rail.setFixedWidth(196)
        rv = QVBoxLayout(rail)
        rv.setContentsMargins(10, 14, 10, 12)
        rv.setSpacing(2)
        brand = QLabel("☰  Меню")
        brand.setObjectName("brand")
        rv.addWidget(brand)
        self.sec_btns = []
        for i, a in enumerate(self.sections):
            name = _clean(a.text())
            b = QPushButton(f"{SECTION_ICONS.get(name, '•')}   {name}")
            b.setObjectName("sec")
            b.setCheckable(True)
            b.setAutoExclusive(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setFocusPolicy(Qt.NoFocus)
            b.clicked.connect(lambda _=False, i=i: self.show_section(i))
            b.installEventFilter(self)
            rv.addWidget(b)
            self.sec_btns.append(b)
        rv.addStretch(1)
        foot = QLabel(footer + ("\n" if footer else "") + "Esc — закрыть\nCtrl+K — поиск по делам")
        foot.setObjectName("foot")
        foot.setContentsMargins(8, 0, 0, 0)
        rv.addWidget(foot)
        h.addWidget(rail)

        right = QVBoxLayout()
        right.setContentsMargins(18, 14, 12, 12)
        right.setSpacing(8)
        self.search = QLineEdit()
        self.search.setObjectName("search")
        self.search.setPlaceholderText("🔍  Найти команду…  например: «сжать», «опись», «тема»")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.refresh)
        self.search.installEventFilter(self)
        right.addWidget(self.search)
        self.head = QLabel()
        self.head.setObjectName("title")
        self.hint = QLabel()
        self.hint.setObjectName("hint")
        hh = QHBoxLayout()
        hh.setContentsMargins(4, 6, 0, 0)
        hh.addWidget(self.head)
        hh.addSpacing(10)
        hh.addWidget(self.hint, 0, Qt.AlignBottom)
        hh.addStretch(1)
        right.addLayout(hh)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        right.addWidget(self.scroll, 1)
        h.addLayout(right, 1)
        self.resize(880 + 36, 560 + 36)
        self._hover = QTimer(self, singleShot=True, interval=140)
        self._hover.timeout.connect(self._hover_switch)
        self._hover_i = None
        names = [_clean(a.text()) for a in self.sections]
        i = names.index(AppMenu.last_section) if AppMenu.last_section in names else 0
        self.show_section(i)

    # --- разделы
    def eventFilter(self, o, e):
        if o in getattr(self, "sec_btns", ()) and e.type() == QEvent.Enter and not self.search.text():
            self._hover_i = self.sec_btns.index(o)
            self._hover.start()
        elif o in getattr(self, "sec_btns", ()) and e.type() == QEvent.Leave:
            self._hover.stop()
        elif o is getattr(self, "search", None) and e.type() == QEvent.KeyPress:
            k = e.key()
            if k == Qt.Key_Down and self.rows:
                self.rows[0].setFocus()
                return True
            if k in (Qt.Key_Return, Qt.Key_Enter) and self.rows:
                self.rows[0].click()
                return True
            if not self.search.text() and k in (Qt.Key_PageUp, Qt.Key_PageDown):
                self.show_section((self.cur + (1 if k == Qt.Key_PageDown else -1)) % len(self.sections))
                return True
        return super().eventFilter(o, e)

    def _hover_switch(self):
        if self._hover_i is not None and self._hover_i != self.cur:
            self.show_section(self._hover_i)

    def show_section(self, i):
        self.cur = i
        if self.sec_btns:
            self.sec_btns[i].setChecked(True)
        if self.search.text():
            self.search.blockSignals(True)
            self.search.clear()
            self.search.blockSignals(False)
        AppMenu.last_section = _clean(self.sections[i].text())
        self.refresh()

    def refresh(self):
        q = _norm(self.search.text()).split()
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 0, 8, 6)
        v.setSpacing(2)
        self.rows = []
        for b in self.sec_btns:                  # при поиске ни один раздел не подсвечен
            b.setAutoExclusive(False)
            b.setChecked(not q and b is self.sec_btns[self.cur])
            b.setAutoExclusive(True)
        if q:
            self.head.setText("Поиск")
            found = []
            for sec in self.sections:
                self._collect(sec.menu(), [_clean(sec.text())], found)
            hits = []
            for a, path in found:
                icon, name, sub = _split(a)
                hay = _norm(f"{name} {sub} {' '.join(path)}")
                if all(w in hay for w in q):
                    hits.append((0 if _norm(name).startswith(q[0]) else 1, a, path))
            hits.sort(key=lambda x: x[0])
            self.hint.setText(f"найдено: {len(hits)}" if hits else "ничего не найдено")
            for _, a, path in hits[:40]:
                v.addWidget(self._row(a, " › ".join(path), GROUP_ICONS.get(path[-1]) or SECTION_ICONS.get(path[0])))
            if not hits:
                lab = QLabel("Попробуйте другое слово. Дела, документы и сроки ищутся через Ctrl+K.")
                lab.setObjectName("hint")
                lab.setWordWrap(True)
                v.addWidget(lab)
        else:
            sec = self.sections[self.cur]
            name = _clean(sec.text())
            self.head.setText(name)
            self.hint.setText(SECTION_HINTS.get(name, ""))
            self._fill(sec.menu(), v)
        v.addStretch(1)
        self.scroll.setWidget(page)

    def _collect(self, menu, path, out):
        for a in menu.actions():
            if a.isSeparator() or not a.isVisible():
                continue
            if a.menu():
                self._collect(a.menu(), path + [_clean(a.text())], out)
            else:
                out.append((a, path))

    def _fill(self, menu, v):
        first = True
        for a in menu.actions():
            if not a.isVisible():
                continue
            if a.isSeparator():
                if not first:
                    v.addSpacing(6)
                    line = QFrame()
                    line.setObjectName("line")
                    v.addWidget(line)
                    v.addSpacing(6)
                continue
            first = False
            if a.menu():
                self._group(a, v)
            else:
                v.addWidget(self._row(a))

    def _group(self, a, v):
        name = _clean(a.text())
        lab = QLabel(f"{GROUP_ICONS.get(name, '')}  {name.upper()}".strip())
        lab.setObjectName("group")
        v.addWidget(lab)
        acts = [x for x in a.menu().actions() if x.isVisible()]
        if any(self.swatch(_clean(x.text())) for x in acts if not x.isSeparator()):
            self._swatches(acts, v)
            return
        grid = QGridLayout()
        grid.setSpacing(6)
        grid.setContentsMargins(0, 2, 0, 6)
        cols = 3
        n = 0
        for x in acts:
            if x.isSeparator() or x.menu():
                continue
            grid.addWidget(self._tile(x), n // cols, n % cols)
            n += 1
        for c in range(cols):
            grid.setColumnStretch(c, 1)
        v.addLayout(grid)

    def _swatches(self, acts, v):
        wrap = QGridLayout()
        wrap.setSpacing(4)
        wrap.setContentsMargins(0, 4, 0, 8)
        n = 0
        for x in acts:
            if x.isSeparator():
                continue
            cols = self.swatch(_clean(x.text()))
            if not cols:
                continue
            cell = QVBoxLayout()
            cell.setSpacing(0)
            s = Swatch(x, cols, self.t)
            s.clicked.connect(lambda _=False, x=x: self._run(x, keep=True))
            self.rows.append(s)
            cell.addWidget(s, 0, Qt.AlignHCenter)
            lab = QLabel(_clean(x.text()).split(" — ")[0])
            lab.setObjectName("sub")
            lab.setAlignment(Qt.AlignHCenter)
            cell.addWidget(lab)
            wrap.addLayout(cell, n // 6, n % 6)
            n += 1
        v.addLayout(wrap)

    def _row(self, a, path="", fallback=""):
        icon, name, sub = _split(a)
        icon = icon or fallback
        b = QPushButton()
        b.setObjectName("row")
        b.setCursor(Qt.PointingHandCursor)
        b.setEnabled(a.isEnabled())
        h = QHBoxLayout(b)
        h.setContentsMargins(10, 7, 10, 7)
        h.setSpacing(10)
        ic = QLabel(icon or "·")
        ic.setObjectName("ico")
        ic.setAlignment(Qt.AlignCenter)
        h.addWidget(ic)
        col = QVBoxLayout()
        col.setSpacing(0)
        nm = QLabel(name)
        nm.setObjectName("name")
        col.addWidget(nm)
        if path:
            p = QLabel(path)
            p.setObjectName("path")
            col.addWidget(p)
        elif sub:
            s = QLabel(sub)
            s.setObjectName("sub")
            col.addWidget(s)
        h.addLayout(col, 1)
        if a.isCheckable():
            h.addWidget(Toggle(a.isChecked(), self.t))
        ks = a.shortcut().toString(QKeySequence.NativeText)
        if ks:
            k = QLabel(ks)
            k.setObjectName("key")
            h.addWidget(k)
        b.setMinimumHeight(48 if (sub or path) else 38)
        for w in b.findChildren(QLabel):
            w.setAttribute(Qt.WA_TransparentForMouseEvents)
            if not a.isEnabled():
                w.setEnabled(False)
        b.clicked.connect(lambda _=False, a=a: self._run(a, keep=a.isCheckable()))
        b.installEventFilter(self._nav)
        self.rows.append(b)
        return b

    def _tile(self, a):
        icon, name, sub = _split(a)
        b = QPushButton()
        b.setObjectName("tile")
        b.setCursor(Qt.PointingHandCursor)
        b.setEnabled(a.isEnabled())
        b.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        b.setFixedHeight(44)
        b.setToolTip(sub or name)
        h = QHBoxLayout(b)
        h.setContentsMargins(12, 2, 8, 2)
        h.setSpacing(6)
        nm = QLabel(name)
        nm.setObjectName("name")
        nm.setWordWrap(True)
        nm.setAttribute(Qt.WA_TransparentForMouseEvents)
        h.addWidget(nm, 1)
        b.clicked.connect(lambda _=False, a=a: self._run(a))
        b.installEventFilter(self._nav)
        self.rows.append(b)
        return b

    @property
    def _nav(self):
        if not hasattr(self, "_navf"):
            self._navf = _Nav(self)
        return self._navf

    def _run(self, a, keep=False):
        if keep and a.isCheckable():
            a.trigger()                      # переключатели (тема, анимации) — меню остаётся открытым
            if self.isVisible():
                pos = self.scroll.verticalScrollBar().value()
                self.refresh()
                QTimer.singleShot(0, lambda: self.scroll.verticalScrollBar().setValue(pos))
            return
        self.close()
        QTimer.singleShot(0, a.trigger)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.close()
            return
        if e.text() and e.text().isprintable() and not e.modifiers() & (Qt.ControlModifier | Qt.AltModifier):
            self.search.setFocus()
            self.search.insert(e.text())
            return
        super().keyPressEvent(e)

    def popup_at(self, anchor):
        g = anchor.mapToGlobal(QPoint(-18, anchor.height() - 6))
        scr = (anchor.screen() or QApplication.primaryScreen()).availableGeometry()
        x = min(max(g.x(), scr.left()), scr.right() - self.width())
        y = min(max(g.y(), scr.top()), scr.bottom() - self.height())
        if anchor.width() < 60 and anchor.mapToGlobal(QPoint(0, 0)).x() < scr.left() + 120 and \
                anchor.objectName() == "railbtn":           # из узкой полоски — справа от неё
            p = anchor.mapToGlobal(QPoint(anchor.width() - 8, -14))
            x, y = p.x(), min(max(p.y(), scr.top()), scr.bottom() - self.height())
        self.move(x, y)
        self.show()
        self.search.setFocus()


class _Nav(QObject):
    """Стрелки ↑↓ ходят по пунктам, Enter — выполнить, ↑ с первого пункта — в поиск."""

    def __init__(self, menu):
        super().__init__(menu)
        self.m = menu

    def eventFilter(self, o, e):
        if e.type() == QEvent.KeyPress and o in self.m.rows:
            rows = [r for r in self.m.rows if r.isEnabled()]
            i = rows.index(o) if o in rows else 0
            k = e.key()
            if k in (Qt.Key_Down, Qt.Key_Right):
                rows[min(i + 1, len(rows) - 1)].setFocus()
                self.m.scroll.ensureWidgetVisible(rows[min(i + 1, len(rows) - 1)])
                return True
            if k in (Qt.Key_Up, Qt.Key_Left):
                if i == 0:
                    self.m.search.setFocus()
                else:
                    rows[i - 1].setFocus()
                    self.m.scroll.ensureWidgetVisible(rows[i - 1])
                return True
            if k in (Qt.Key_Return, Qt.Key_Enter):
                o.click()
                return True
        return False


class Toggle(QWidget):
    """Переключатель «вкл/выкл» для пунктов-флажков."""

    def __init__(self, on, t):
        super().__init__()
        self.on, self.t = on, t
        self.setFixedSize(36, 20)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(self.t["accent"] if self.on else self.t["input_border"]))
        p.drawRoundedRect(QRectF(0, 0, 36, 20), 10, 10)
        p.setBrush(QBrush(QColor("#ffffff")))
        p.drawEllipse(QRectF(18 if self.on else 2, 2, 16, 16))
        p.end()


def show(win, anchor, menu, theme, swatch=None, footer=""):
    m = AppMenu(win, menu, theme, swatch, footer)
    m.popup_at(anchor)
    return m
