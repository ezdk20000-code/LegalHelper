# -*- coding: utf-8 -*-
"""
«Структура» — оглавление открытого PDF рядом со страницами, как в читалках: щелчок — переход к месту.
Берётся из закладок PDF; если их нет — программа сама собирает заголовки (крупный шрифт, «Глава 1…»,
«РЕШЕНИЕ», «ИСКОВОЕ ЗАЯВЛЕНИЕ»…). В PDF дела первый уровень — документы дела. Поле сверху ищет и по
оглавлению, и по всему тексту документа.
"""
import re
from collections import Counter

from PySide6.QtCore import Qt, QTimer, QEvent, QPoint
from PySide6.QtGui import QImage, QPixmap, QCursor, QGuiApplication
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLineEdit, QTreeWidget, QTreeWidgetItem,
                               QLabel, QStackedWidget, QTabBar, QAbstractItemView,
                               QToolButton)

HEAD_RX = re.compile(
    r"^(?:(?:Глава|Раздел|Часть|Приложение|Статья|Параграф|§)\s*[\dIVXLC]+[.)]?(?:\s|$)|"
    r"\d{1,2}(?:\.\d{1,2})?\.?\s+[А-ЯЁ][а-яё]|"
    r"(?:ИСКОВОЕ ЗАЯВЛЕНИЕ|ЗАЯВЛЕНИЕ|ОТЗЫВ|ВОЗРАЖЕНИЯ|ХОДАТАЙСТВО|ПРЕТЕНЗИЯ|ЖАЛОБА|АПЕЛЛЯЦИОННАЯ ЖАЛОБА|"
    r"КАССАЦИОННАЯ ЖАЛОБА|РЕШЕНИЕ|ОПРЕДЕЛЕНИЕ|ПОСТАНОВЛЕНИЕ|ПРИГОВОР|ДОГОВОР|ДОВЕРЕННОСТЬ|АКТ|ПРОТОКОЛ|"
    r"УСТАНОВИЛ|ОПРЕДЕЛИЛ|РЕШИЛ|ПОСТАНОВИЛ|ПРОШУ|Р\s?Е\s?Ш\s?Е\s?Н\s?И\s?Е|О\s?П\s?Р\s?Е\s?Д\s?Е\s?Л\s?Е\s?Н\s?И\s?Е)"
    r"(?:\s|:|$))")
MAX_AUTO_PAGES = 600


def _clean(s):
    return re.sub(r"\s+", " ", s or "").strip(" .:")


def page_headings(page, body=None):
    """Заголовки страницы: [(уровень, текст, y)] — по размеру шрифта и по типичным словам."""
    out = []
    try:
        d = page.get_text("dict", flags=0)
    except Exception:
        return out
    lines = []
    for b in d.get("blocks", []):
        for ln in b.get("lines", []):
            spans = [s for s in ln.get("spans", []) if s.get("text", "").strip()]
            if not spans:
                continue
            text = _clean("".join(s["text"] for s in spans))
            size = max(s["size"] for s in spans)
            bold = all("bold" in s.get("font", "").lower() or s.get("flags", 0) & 16 for s in spans)
            lines.append((text, size, bold, ln["bbox"][1]))
    if not lines:
        return out
    if body is None:
        body = Counter(round(sz) for t, sz, _b, _y in lines for _ in range(max(1, len(t) // 20))).most_common(1)[0][0]
    for text, size, bold, y in lines:
        if not (3 <= len(text) <= 120) or re.fullmatch(r"[\d\s.\-–—]+", text):
            continue
        big = size >= body * 1.25
        rx = HEAD_RX.match(text)
        if big or (rx and (bold or text.isupper() or size >= body * 1.1 or len(text) < 60)):
            lvl = 1 if size >= body * 1.5 or re.match(r"(?:Глава|Раздел|Часть)\b", text) or text.isupper() else 2
            if out and out[-1][2] > y - size * 1.6 and out[-1][0] == lvl:   # заголовок в две строки
                out[-1] = (lvl, out[-1][1] + " " + text, out[-1][2])
                continue
            out.append((lvl, text, y))
    return out


def body_size(doc, sample=8):
    c = Counter()
    n = doc.page_count
    for i in range(0, n, max(1, n // sample)):
        try:
            for b in doc[i].get_text("dict", flags=0).get("blocks", []):
                for ln in b.get("lines", []):
                    for s in ln.get("spans", []):
                        c[round(s["size"])] += len(s.get("text", ""))
        except Exception:
            pass
    return c.most_common(1)[0][0] if c else 11


class OutlinePanel(QWidget):
    def __init__(self, main):
        super().__init__()
        self.main = main
        self._sig = None
        self._pending = []
        v = QVBoxLayout(self)
        v.setContentsMargins(6, 6, 6, 6)
        v.setSpacing(6)
        self.find = QLineEdit()
        self.find.setPlaceholderText("Найти в структуре и тексте…  Enter")
        self.find.setClearButtonEnabled(True)
        self.find.textChanged.connect(self.filter)
        self.find.returnPressed.connect(self.search_text)
        v.addWidget(self.find)
        self.tree = QTreeWidget()
        self.tree.setObjectName("outline")
        self.tree.setHeaderHidden(True)
        self.tree.setWordWrap(True)
        self.tree.setIndentation(14)
        self.tree.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tree.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.tree.itemClicked.connect(self.go)
        self.tree.itemActivated.connect(self.go)
        v.addWidget(self.tree, 1)
        self.note = QLabel()
        self.note.setObjectName("hint")
        self.note.setWordWrap(True)
        v.addWidget(self.note)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._step)
        self.watch = QTimer(self)                 # документ поменялся (открыли другой, удалили страницы) — пересобрать
        self.watch.timeout.connect(self.refresh)
        self.watch.start(1500)

    # ---------------------------------------------------------------- сборка
    def signature(self):
        doc = getattr(self.main, "doc", None)
        return (id(doc), doc.page_count if doc is not None else 0, getattr(self.main, "path", None))

    def showEvent(self, e):
        super().showEvent(e)
        self.refresh()

    def refresh(self, force=False):
        if not self.isVisible():
            return
        sig = self.signature()
        if sig == self._sig and not force:
            return
        self._sig = sig
        self.timer.stop()
        self.tree.clear()
        self.find.clear()
        doc = self.main.doc
        if doc is None or not doc.page_count:
            self.note.setText("Откройте документ — здесь появится его оглавление.")
            return
        groups = self._groups(doc)
        toc = []
        try:
            toc = doc.get_toc(simple=True)
        except Exception:
            pass
        self._parents = {}
        if len(groups) > 1:                         # PDF дела: сверху — документы
            for start, name in groups:
                it = self._add(None, name, start, bold=True)
                self._parents[start] = it
        if toc:
            stack = []
            for lvl, title, page in toc:
                p = max(0, page - 1)
                while stack and stack[-1][0] >= lvl:
                    stack.pop()
                parent = stack[-1][1] if stack else self._group_item(p)
                it = self._add(parent, _clean(title), p)
                stack.append((lvl, it))
            self.note.setText("Оглавление из закладок PDF. Щелчок — перейти.")
            self.tree.expandToDepth(0)
            return
        if doc.page_count > MAX_AUTO_PAGES:
            self.note.setText(f"В документе нет закладок, а страниц много ({doc.page_count}) — "
                              "ищите по тексту в поле сверху.")
            return
        self._body = body_size(doc)
        self._pending = list(range(doc.page_count))
        self._last = {}
        self.note.setText("Собираю заголовки…")
        self.timer.start(0)

    def _groups(self, doc):
        """Части PDF дела: [(первая страница, название документа)]."""
        out, last = [], None
        for i in range(doc.page_count):
            try:
                g, name = self.main._page_group(i)
            except Exception:
                g, name = None, None
            if g and g != last:
                nm = re.sub(r"_+", " ", re.sub(r"\.(pdf|docx?|rtf|odt|xlsx?|jpe?g|png|tiff?)$", "", name or g, flags=re.I))
                out.append((i, nm.strip()))
            last = g
        return out

    def _group_item(self, p):
        best = None
        for start, it in getattr(self, "_parents", {}).items():
            if start <= p and (best is None or start > best[0]):
                best = (start, it)
        return best[1] if best else None

    def _step(self):
        doc = self.main.doc
        if self.signature() != self._sig:
            return self.refresh()
        for _ in range(6):
            if not self._pending:
                self.timer.stop()
                n = self.tree.topLevelItemCount()
                self.note.setText("Заголовки найдены автоматически. Щелчок — перейти." if n else
                                  "Заголовков не нашлось (скан без текста или сплошной текст) — ищите по тексту "
                                  "в поле сверху.")
                self.tree.expandToDepth(0)
                return
            p = self._pending.pop(0)
            for lvl, text, _y in page_headings(doc[p], self._body):
                group = self._group_item(p)
                if lvl == 1 or group is None and not self._last.get(1):
                    parent = group
                else:
                    parent = self._last.get(1) or group
                if self._last.get("text") == text:   # колонтитул повторяется на каждой странице
                    continue
                it = self._add(parent, text, p)
                self._last["text"] = text
                if lvl == 1:
                    self._last[1] = it

    def _add(self, parent, text, page, bold=False):
        it = QTreeWidgetItem([text])
        it.setData(0, Qt.UserRole, page)
        it.setToolTip(0, f"{text}\nстр. {page + 1}")
        if bold:
            f = it.font(0)
            f.setBold(True)
            it.setFont(0, f)
        (parent.addChild(it) if parent is not None else self.tree.addTopLevelItem(it))
        return it

    # ---------------------------------------------------------------- переход и поиск
    def go(self, it, _col=0):
        p = it.data(0, Qt.UserRole)
        if p is None:
            return
        pv = getattr(self.main, "preview", None)
        if pv is not None and not pv.isVisible() and hasattr(self.main, "set_preview"):
            self.main.set_preview(True)              # миниатюры скрыты структурой — показать страницу крупно
        self.main.goto_page(int(p))

    def filter(self, text):
        text = text.strip().lower()
        self._drop_results()

        def walk(it):
            own = not text or text in it.text(0).lower()
            child = False
            for i in range(it.childCount()):
                child = walk(it.child(i)) or child
            it.setHidden(not (own or child))
            if text and child:
                it.setExpanded(True)
            return own or child
        for i in range(self.tree.topLevelItemCount()):
            walk(self.tree.topLevelItem(i))

    def _drop_results(self):
        r = getattr(self, "_results", None)
        if r is not None:
            i = self.tree.indexOfTopLevelItem(r)
            if i >= 0:
                self.tree.takeTopLevelItem(i)
        self._results = None

    def search_text(self):
        """Enter: найти слова во всём тексте документа — список «стр. N: …фрагмент…»."""
        q = self.find.text().strip()
        doc = self.main.doc
        if len(q) < 2 or doc is None:
            return
        self._drop_results()
        res = QTreeWidgetItem([f"Найдено в тексте: «{q}»"])
        f = res.font(0)
        f.setBold(True)
        res.setFont(0, f)
        self.tree.insertTopLevelItem(0, res)
        self._results = res
        count = 0
        for p in range(doc.page_count):
            try:
                text = doc[p].get_text()
            except Exception:
                continue
            flat = re.sub(r"\s+", " ", text)
            for m in re.finditer(re.escape(q), flat, re.I):
                a = max(0, m.start() - 40)
                snip = ("…" if a else "") + flat[a:m.end() + 50].strip() + "…"
                it = QTreeWidgetItem([f"стр. {p + 1}: {snip}"])
                it.setData(0, Qt.UserRole, p)
                it.setToolTip(0, snip)
                res.addChild(it)
                count += 1
                if count >= 300:
                    break
            if count >= 300:
                break
        res.setText(0, f"Найдено в тексте: «{q}» — {count}" + (" (первые 300)" if count >= 300 else "")
                    if count else f"В тексте нет «{q}» (сканы без распознавания не ищутся)")
        res.setExpanded(True)
        res.setHidden(False)
        if count:
            first = res.child(0)
            self.tree.setCurrentItem(first)
            self.go(first)


class PagesWithOutline(QWidget):
    """Над миниатюрами — переключатель «Страницы | Структура»."""

    def __init__(self, main, pages):
        super().__init__()
        self.main = main
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        bar = QWidget()
        h = QHBoxLayout(bar)
        h.setContentsMargins(8, 6, 8, 4)
        h.setSpacing(2)
        self.seg = QTabBar()
        self.seg.setObjectName("docseg")
        self.seg.setDrawBase(False)
        self.seg.setExpanding(False)
        self.seg.addTab("▦  Страницы")
        self.seg.addTab("☰  Структура")
        self.seg.setTabToolTip(0, "Миниатюры страниц")
        self.seg.setTabToolTip(1, "Оглавление документа и поиск по тексту — щелчок по заголовку переходит к нему")
        h.addWidget(self.seg)
        h.addStretch(1)
        self.page_tools = []
        for text, tip, fn in (("⊟ Свернуть всё", "Каждый файл — одной стопкой (удобно двигать файлы целиком)",
                               lambda: main.collapse_all(True)),
                              ("⊞ Развернуть всё", "Показать все страницы всех файлов",
                               lambda: main.collapse_all(False))):
            b = QToolButton()
            b.setText(text)
            b.setToolTip(tip)
            b.setObjectName("moretabs")
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(fn)
            h.addWidget(b)
            self.page_tools.append(b)
        self.b_lens = QToolButton()
        self.b_lens.setText("🔎 Лупа")
        self.b_lens.setObjectName("moretabs")
        self.b_lens.setCheckable(True)
        self.b_lens.setCursor(Qt.PointingHandCursor)
        self.b_lens.setToolTip("Лупа: наведите мышь на страницу — она покажется крупно, открывать не нужно.\n"
                               "Без лупы: выделите страницу и нажмите пробел — крупный просмотр, ещё раз пробел или Esc "
                               "— закрыть.")
        self.b_lens.toggled.connect(self._lens_toggled)
        h.addWidget(self.b_lens)
        self.page_tools.append(self.b_lens)
        v.addWidget(bar)
        self.pages = pages
        self.lens = Magnifier(main)
        pages.viewport().setMouseTracking(True)
        pages.viewport().installEventFilter(self)
        pages.installEventFilter(self)
        try:
            import legal_ui as U
            self.b_lens.setChecked(str(U.M.settings().value("lens_on", "0")) == "1")
        except Exception:
            pass
        self.stack = QStackedWidget()
        self.outline = OutlinePanel(main)
        self.stack.addWidget(pages)
        self.stack.addWidget(self.outline)
        v.addWidget(self.stack, 1)
        self.seg.currentChanged.connect(self.show_part)

    def _lens_toggled(self, on):
        try:
            import legal_ui as U
            U.M.settings().setValue("lens_on", "1" if on else "0")
        except Exception:
            pass
        if not on:
            self.lens.hide()

    def eventFilter(self, obj, e):
        t = e.type()
        if obj is self.pages.viewport():
            if t == QEvent.MouseMove and self.b_lens.isChecked() and not e.buttons():
                it = self.pages.itemAt(e.position().toPoint())
                if it is None:
                    self.lens.hide()
                else:
                    self.lens.show_page(self.pages.row(it), QCursor.pos())
            elif t in (QEvent.Leave, QEvent.MouseButtonPress, QEvent.Wheel):
                self.lens.hide()
        elif obj is self.pages and t == QEvent.KeyPress:
            if e.key() == Qt.Key_Space and not e.modifiers():
                if self.lens.isVisible():
                    self.lens.hide()
                else:
                    row = self.pages.currentRow()
                    if row >= 0:
                        r = self.pages.visualItemRect(self.pages.item(row))
                        self.lens.show_page(row, self.pages.viewport().mapToGlobal(r.center()), big=True)
                return True
            if e.key() == Qt.Key_Escape and self.lens.isVisible():
                self.lens.hide()
                return True
            if self.lens.isVisible() and e.key() in (Qt.Key_Left, Qt.Key_Right, Qt.Key_Up, Qt.Key_Down):
                QTimer.singleShot(0, lambda: self._follow())
        return False

    def _follow(self):
        row = self.pages.currentRow()
        if row >= 0 and self.lens.isVisible():
            r = self.pages.visualItemRect(self.pages.item(row))
            self.lens.show_page(row, self.pages.viewport().mapToGlobal(r.center()), big=True)

    def show_part(self, i):
        if self.seg.currentIndex() != i:
            self.seg.setCurrentIndex(i)
            return
        for b in self.page_tools:
            b.setVisible(i == 0)
        self.lens.hide()
        self.stack.setCurrentIndex(i)
        if i == 1:
            self.outline.refresh()
            self.outline.find.setFocus()


class Magnifier(QLabel):
    """Крупный просмотр страницы поверх окна — без открытия документа."""

    def __init__(self, main):
        super().__init__(None, Qt.ToolTip | Qt.FramelessWindowHint)
        self.main = main
        self.setObjectName("lens")
        self.setStyleSheet("QLabel#lens { background: white; border: 1px solid #9aa4b2; }")
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self._cache = {}
        self._want = None
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self._render)

    def show_page(self, i, at, big=False):
        self._want = (i, at, big)
        if self.isVisible():
            self._render()
        else:
            self.timer.start(220)                 # короткая задержка: не мигать, когда мышь просто проходит мимо

    def hide(self):
        self.timer.stop()
        self._want = None
        super().hide()

    def _render(self):
        if not self._want:
            return
        i, at, big = self._want
        doc = getattr(self.main, "doc", None)
        if doc is None or not (0 <= i < doc.page_count):
            return self.hide()
        scr = QGuiApplication.screenAt(at) or QGuiApplication.primaryScreen()
        geo = scr.availableGeometry()
        hmax = int(geo.height() * (0.92 if big else 0.8))
        key = (id(doc), doc.page_count, i, hmax)
        pm = self._cache.get(key)
        if pm is None:
            page = doc[i]
            dpr = self.devicePixelRatioF()
            z = min(hmax / page.rect.height, geo.width() * 0.6 / page.rect.width) * dpr
            pix = page.get_pixmap(matrix=__import__("pymupdf").Matrix(z, z), alpha=False)
            img = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format_RGB888).copy()
            pm = QPixmap.fromImage(img)
            pm.setDevicePixelRatio(dpr)
            if len(self._cache) > 12:
                self._cache.clear()
            self._cache[key] = pm
        self.setPixmap(pm)
        self.resize(int(pm.width() / pm.devicePixelRatio()) + 2, int(pm.height() / pm.devicePixelRatio()) + 2)
        # справа от курсора, если есть место, иначе слева; по высоте — в пределах экрана
        x = at.x() + 24 if at.x() + 24 + self.width() <= geo.right() else at.x() - 24 - self.width()
        if big:
            x = geo.left() + (geo.width() - self.width()) // 2
        x = max(geo.left(), x)
        y = min(max(geo.top(), at.y() - self.height() // 2), geo.bottom() - self.height())
        self.move(QPoint(x, y))
        self.show()
        self.raise_()
