# -*- coding: utf-8 -*-
"""
Своя верхняя полоса окна вместо стандартной рамки Windows — как в VS Code и Notion: логотип, где вы сейчас
(«Дело › Вкладка · файл»), поиск по центру, отметка о сохранении и кнопки «свернуть / развернуть / закрыть»
в стиле программы. Окно перетаскивается за полосу (к краю экрана — на половину экрана, как обычно), двойной
щелчок разворачивает, края тянутся мышью. Вернуть обычную рамку: ☰ → Вид → «Своя полоса заголовка».
"""
from PySide6.QtCore import Qt, QObject, QEvent, QTimer, QPoint, QSize
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (QWidget, QHBoxLayout, QVBoxLayout, QLabel, QToolButton, QPushButton, QApplication,
                               QSizePolicy)

KEY = "custom_titlebar"
EDGE = 6


def enabled(settings):
    return str(settings().value(KEY, "1")) != "0"


class TitleBar(QWidget):
    def __init__(self, main):
        super().__init__(main)
        self.main = main
        self.setObjectName("titlebar")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedHeight(36)
        h = QHBoxLayout(self)
        h.setContentsMargins(10, 0, 0, 0)
        h.setSpacing(8)
        logo = QLabel()
        dpr = main.devicePixelRatioF()
        pm = main.windowIcon().pixmap(QSize(64, 64)).scaled(int(18 * dpr), int(18 * dpr), Qt.KeepAspectRatio,
                                                             Qt.SmoothTransformation)
        pm.setDevicePixelRatio(dpr)
        logo.setPixmap(pm)
        h.addWidget(logo)
        self.crumb = QLabel()
        self.crumb.setObjectName("tbcrumb")
        self.crumb.setTextFormat(Qt.RichText)
        self.crumb.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.crumb.setMinimumWidth(60)
        h.addWidget(self.crumb, 3)
        self.search = QPushButton("🔍  Найти что угодно…        Ctrl+K")
        self.search.setObjectName("tbsearch")
        self.search.setCursor(Qt.PointingHandCursor)
        self.search.setFixedWidth(300)
        self.search.clicked.connect(lambda: __import__("palette").show(main))
        h.addWidget(self.search, 0, Qt.AlignVCenter)
        self.state = QLabel()
        self.state.setObjectName("tbstate")
        self.state.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.state.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.state.setMinimumWidth(60)
        h.addWidget(self.state, 2)
        self.b_min = self._btn("—", "Свернуть", main.showMinimized)
        self.b_max = self._btn("☐", "Развернуть на весь экран", self.toggle_max)
        self.b_close = self._btn("✕", "Закрыть", main.close)
        self.b_close.setObjectName("tbclose")
        for b in (self.b_min, self.b_max, self.b_close):
            h.addWidget(b)
        self._normal_geo = None
        main.windowTitleChanged.connect(lambda *_: self.refresh())
        QTimer.singleShot(0, self.refresh)

    def _btn(self, text, tip, fn):
        b = QToolButton()
        b.setText(text)
        b.setToolTip(tip)
        b.setObjectName("tbbtn")
        b.setFixedSize(46, 36)
        b.clicked.connect(fn)
        return b

    # ---------------------------------------------------------------- что показывать
    def refresh(self):
        m = self.main
        parts = []
        try:
            cur = m.stack.currentWidget()
            if cur is m.home_page:
                parts.append("Главная")
            elif cur is m.loose_page:
                parts.append("Без дела")
            elif cur is getattr(m, "folder_page", None):
                parts.append("Папка")
            elif cur is m.help_page:
                parts.append("Справка")
            elif getattr(m, "mode_cid", None):
                import legal_ui as U
                c = U.db().case(m.mode_cid) or {}
                t = c.get("title") or "Дело"
                parts.append(t if len(t) <= 34 else t[:32].rstrip() + "…")
                tabs = m.cases_page.tabs
                parts.append(tabs.tabText(tabs.currentIndex()))
        except Exception:
            pass
        title = m.windowTitle().rsplit(" — ", 1)[0].rstrip(" *") if " — " in m.windowTitle() else ""
        try:
            w = m.ws[m.cur_ws] if getattr(m, "ws", None) else {}
            if w.get("main"):
                title = "PDF дела"                  # файл дела называется как дело — не повторять название
        except Exception:
            pass
        esc = lambda s: s.replace("&", "&amp;").replace("<", "&lt;")
        html = "  <span style='opacity:.45'>›</span>  ".join(f"<b>{esc(p)}</b>" if i == 0 else esc(p)
                                                              for i, p in enumerate(parts))
        if title and title not in parts:
            html += ("  <span style='opacity:.45'>·</span>  " if html else "") + \
                f"<span style='opacity:.7'>{esc(title)}</span>"
        self.crumb.setText(html or "<b>LegalHelper</b>")
        self.crumb.setToolTip(" › ".join(parts + ([title] if title else [])))
        if getattr(m, "modified", False):
            self.state.setText("●  Не сохранено — Ctrl+S")
            self.state.setProperty("dirty", True)
        elif getattr(m, "doc", None) is not None and m.doc.page_count and getattr(m, "path", None):
            self.state.setText("✓  Сохранено")
            self.state.setProperty("dirty", False)
        else:
            self.state.setText("")
        self.state.style().unpolish(self.state)
        self.state.style().polish(self.state)
        self.b_max.setText("❐" if self.is_max() else "☐")
        self.b_max.setToolTip("Вернуть прежний размер" if self.is_max() else "Развернуть на весь экран")
        self.search.setVisible(self.width() > 900)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.search.setVisible(self.width() > 900)

    # ---------------------------------------------------------------- окно
    def is_max(self):
        return self.main.isMaximized() or self._normal_geo is not None

    def toggle_max(self):
        m = self.main
        if self._normal_geo is not None:          # своё «развернуть» — по рабочей области, не закрывая панель задач
            g, self._normal_geo = self._normal_geo, None
            m.setGeometry(g)
        elif m.isMaximized():
            m.showNormal()
        else:
            self._normal_geo = m.geometry()
            scr = m.screen() or QApplication.primaryScreen()
            m.setGeometry(scr.availableGeometry())
        self.refresh()
        g = getattr(m, "_grips", None)
        if g is not None:
            g.place()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._press = e.globalPosition().toPoint()
            e.accept()
            return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        """Тянем за полосу — двигаем окно (перетаскивание начинается после сдвига на пару точек, чтобы
        двойной щелчок по-прежнему разворачивал окно)."""
        press = getattr(self, "_press", None)
        if press is None or not e.buttons() & Qt.LeftButton:
            return super().mouseMoveEvent(e)
        gp = e.globalPosition().toPoint()
        if (gp - press).manhattanLength() < 4:
            return
        self._press = None
        if self._normal_geo is not None or self.main.isMaximized():   # тянут развёрнутое — вернуть размер
            g = self._normal_geo or self.main.normalGeometry()
            frac = e.position().x() / max(1, self.width())
            if self.main.isMaximized():
                self.main.showNormal()
            self._normal_geo = None
            self.main.setGeometry(gp.x() - int(g.width() * frac), gp.y() - 18, g.width(), g.height())
            self.refresh()
        h = self.main.windowHandle()
        if h is not None:
            h.startSystemMove()

    def mouseReleaseEvent(self, e):
        self._press = None
        super().mouseReleaseEvent(e)

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.toggle_max()
            e.accept()


class Grip(QWidget):
    """Невидимая полоска по краю окна: курсор-стрелка и растягивание мышью (системное — плавное)."""

    def __init__(self, main, edges, shape):
        super().__init__(main)
        self.main, self.edges = main, edges
        self.setCursor(shape)
        self.setAttribute(Qt.WA_NoSystemBackground, True)

    def paintEvent(self, e):
        pass

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            h = self.main.windowHandle()
            if h is not None:
                h.startSystemResize(self.edges)
            e.accept()


class Grips(QObject):
    """Восемь полосок по краям и углам; следим только за размером самого окна (без слежки за всей программой —
    она мешала встроенному браузеру карты дела)."""

    def __init__(self, main, bar):
        super().__init__(main)
        self.main, self.bar = main, bar
        E = Qt.Edge
        spec = [(E.LeftEdge, Qt.SizeHorCursor), (E.RightEdge, Qt.SizeHorCursor), (E.TopEdge, Qt.SizeVerCursor),
                (E.BottomEdge, Qt.SizeVerCursor), (E.LeftEdge | E.TopEdge, Qt.SizeFDiagCursor),
                (E.RightEdge | E.BottomEdge, Qt.SizeFDiagCursor), (E.RightEdge | E.TopEdge, Qt.SizeBDiagCursor),
                (E.LeftEdge | E.BottomEdge, Qt.SizeBDiagCursor)]
        self.grips = [Grip(main, Qt.Edges(e), c) for e, c in spec]
        main.installEventFilter(self)
        QTimer.singleShot(0, self.place)

    def place(self):
        m = self.main
        w, h, k, c = m.width(), m.height(), EDGE, EDGE * 2
        off = m.isMaximized() or m.isFullScreen() or self.bar._normal_geo is not None
        geo = [(0, c, k, h - 2 * c), (w - k, c, k, h - 2 * c), (c, 0, w - 2 * c, k - 2), (c, h - k, w - 2 * c, k),
               (0, 0, c, c), (w - c, h - c, c, c), (w - c, 0, c, c), (0, h - c, c, c)]
        for g, (x, y, gw, gh) in zip(self.grips, geo):
            g.setGeometry(x, y, max(1, gw), max(1, gh))
            g.setVisible(not off)
            g.raise_()

    def eventFilter(self, obj, ev):
        if obj is self.main and ev.type() in (QEvent.Resize, QEvent.WindowStateChange, QEvent.Show):
            QTimer.singleShot(0, self.place)
        return False


def wrap(main, central, settings):
    """Положить полосу над содержимым окна (до setCentralWidget — без пересадки готового содержимого:
    пересадка ломала встроенный браузер карты дела). Возвращает то, что ставить в окно."""
    if not enabled(settings):
        return central
    box = QWidget()
    box.setObjectName("framebox")
    box.setAttribute(Qt.WA_StyledBackground, True)
    v = QVBoxLayout(box)
    v.setContentsMargins(1, 1, 1, 1)                # тонкая рамка вместо системной
    v.setSpacing(0)
    bar = TitleBar(main)
    v.addWidget(bar)
    v.addWidget(central, 1)
    main.titlebar = bar
    return box


def finish(main):
    """Убрать стандартную рамку (до первого показа окна) и включить растягивание за края."""
    bar = getattr(main, "titlebar", None)
    if bar is None:
        return None
    main.setWindowFlags(main.windowFlags() | Qt.FramelessWindowHint | Qt.WindowMinMaxButtonsHint)
    main._grips = Grips(main, bar)
    try:
        main.b_global_search.hide()                 # поиск теперь в верхней полосе
    except Exception:
        pass
    try:
        main.stack.currentChanged.connect(lambda *_: bar.refresh())
        main.cases_page.tabs.currentChanged.connect(lambda *_: bar.refresh())
    except Exception:
        pass
    return bar
