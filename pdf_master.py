# -*- coding: utf-8 -*-
"""
LegalHelper — рабочее место юриста и настольный редактор PDF.
Запуск:  python pdf_master.py [файлы...]
"""
import os
import sys
import html
import tempfile
import traceback
import subprocess
from pathlib import Path

import pymupdf as fitz
from PySide6.QtCore import (Qt, QSize, QTimer, Signal, QPointF, QRectF, QUrl, QByteArray, QBuffer,
                            QIODevice, QEvent, QElapsedTimer, QEventLoop)
from PySide6.QtGui import (QAction, QActionGroup, QIcon, QImage, QPixmap, QPainter, QPen, QColor,
                           QFont, QKeySequence, QDesktopServices, QPainterPath, QPalette, QFontDatabase,
                           QCursor)
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QListWidget, QListWidgetItem, QListView, QAbstractItemView,
    QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QPushButton, QToolBar, QFileDialog, QMessageBox,
    QInputDialog, QLineEdit, QDialog, QDialogButtonBox, QSpinBox, QDoubleSpinBox, QComboBox,
    QCheckBox, QPlainTextEdit, QColorDialog, QProgressDialog, QTreeWidget, QTreeWidgetItem, QSplitter,
    QScrollArea, QMenu, QSlider, QTabWidget, QTableWidget, QTableWidgetItem, QHeaderView, QToolButton,
    QSizePolicy, QStyle, QFrame, QGridLayout, QRadioButton, QButtonGroup, QStackedWidget, QTabBar, QTextBrowser)

import pdf_core as C
import legal_core as L
import legal_ui as U
import help_ui as H
import updater as UPD
import timecheck as TC
import backup as BK
import casefile as CF
import anim
import timer_widget as TW
import extwatch
import tutorial
import phone_export as PHX
import palette
import app_menu
import modern_ui


class _LazyModule:
    """Модуль, который загружается при первом обращении (редактор Word тянет python-docx — это время
    на запуске, а нужен он только когда открывают документ Word)."""

    def __init__(self, name):
        self._name, self._mod = name, None

    def __getattr__(self, attr):
        if self._mod is None:
            import importlib
            self._mod = importlib.import_module(self._name)
        return getattr(self._mod, attr)


WE = _LazyModule("word_editor")

class _Spilled:
    """Старый шаг отмены, вынесенный из памяти во временный файл (до 25 шагов «Отменить» — это до 25 копий
    документа; у большого дела в памяти они занимали гигабайт). Файл удаляется, когда шаг больше не нужен."""
    __slots__ = ("path",)

    def __init__(self, data):
        d = os.path.join(tempfile.gettempdir(), "LegalHelper_undo")
        os.makedirs(d, exist_ok=True)
        fd, self.path = tempfile.mkstemp(prefix="undo_", suffix=".pdf", dir=d)
        with os.fdopen(fd, "wb") as f:
            f.write(data)

    def read(self):
        with open(self.path, "rb") as f:
            return f.read()

    def __del__(self):
        try:
            os.remove(self.path)
        except (OSError, TypeError, AttributeError):
            pass


def spill_old(stack, keep=3, min_size=1 << 20):
    """В памяти — последние keep шагов, более старые крупные копии — во временные файлы."""
    for i in range(max(0, len(stack) - keep)):
        d = stack[i]
        if isinstance(d, (bytes, bytearray)) and len(d) >= min_size:
            try:
                stack[i] = _Spilled(d)
            except OSError:
                return


def undo_data(d):
    return d.read() if isinstance(d, _Spilled) else d


def cleanup_undo_files(max_age=24 * 3600):
    """Удалить временные файлы отмены, оставшиеся после аварийного закрытия программы."""
    import time
    d = os.path.join(tempfile.gettempdir(), "LegalHelper_undo")
    try:
        for n in os.listdir(d):
            p = os.path.join(d, n)
            if time.time() - os.path.getmtime(p) > max_age:
                os.remove(p)
    except OSError:
        pass


APP_NAME = "LegalHelper"
APP_VERSION = "3.4.1"
DEV_EMAIL = "axis.juris@bk.ru"
DEV_TELEGRAM = "axis_juris"
CLOCK_OFFSET = 0.0          # поправка к часам компьютера по точному времени, сек (см. timecheck.py)
ACCENT = "#007aff"
FAILED = object()
PDF_FILTER = "PDF (*.pdf)"
OPEN_FILTER = ("Все поддерживаемые (*.pdf *.jpg *.jpeg *.png *.bmp *.gif *.tif *.tiff *.webp "
               "*.doc *.docx *.rtf *.odt *.xls *.xlsx *.ppt *.pptx *.html *.htm *.xps *.epub *.fb2 *.svg *.txt);;"
               "PDF (*.pdf);;Изображения (*.jpg *.jpeg *.png *.bmp *.gif *.tif *.tiff *.webp);;"
               "Документы Office (*.doc *.docx *.rtf *.odt *.xls *.xlsx *.ppt *.pptx);;Все файлы (*)")
IMG_FILTER = "Изображения (*.jpg *.jpeg *.png *.bmp *.gif *.tif *.tiff *.webp)"


def data_dir():
    """Папка для журналов и настроек: %LOCALAPPDATA%\\PDFMaster (или ~/.pdfmaster)."""
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    d = os.path.join(base, "PDFMaster" if os.environ.get("LOCALAPPDATA") else ".pdfmaster")
    os.makedirs(d, exist_ok=True)
    return d


def log_path():
    return os.path.join(data_dir(), "errors.log")


def log_error(title, exc=None, tb=None):
    """Записать ошибку в журнал (его можно прислать для исправления)."""
    try:
        import datetime, platform
        text = tb or ("".join(traceback.format_exception(type(exc), exc, exc.__traceback__)) if exc else "")
        p = log_path()
        if os.path.exists(p) and os.path.getsize(p) > 2_000_000:      # не разрастаться
            os.replace(p, p + ".old")
        with open(p, "a", encoding="utf-8") as f:
            f.write(f"\n===== {datetime.datetime.now():%Y-%m-%d %H:%M:%S} | {APP_NAME} {APP_VERSION} | "
                    f"PyMuPDF {fitz.VersionBind} | {platform.platform()}\n{title}\n{text}\n")
    except Exception:
        pass


def glyph_icon(ch, color, size=22):
    """Иконка из символа нужного цвета (видна и на светлой, и на тёмной теме)."""
    pm = QPixmap(size * 2, size * 2)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    f = QFont()
    f.setPixelSize(int(size * 1.6))
    f.setBold(True)
    p.setFont(f)
    p.setPen(QColor(color))
    p.drawText(pm.rect(), Qt.AlignCenter, ch)
    p.end()
    pm.setDevicePixelRatio(2)
    return QIcon(pm)


def resource(name):
    return os.path.join(getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__))), name)


def to_qimage(pix):
    fmt = QImage.Format_RGB888 if pix.n == 3 else QImage.Format_RGBA8888
    return QImage(pix.samples, pix.width, pix.height, pix.stride, fmt).copy()


def qimage_png(img):
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.WriteOnly)
    img.save(buf, "PNG")
    return bytes(ba)


def with_opacity(png_bytes, opacity):
    img = QImage.fromData(png_bytes)
    out = QImage(img.size(), QImage.Format_ARGB32)
    out.fill(Qt.transparent)
    p = QPainter(out)
    p.setOpacity(opacity)
    p.drawImage(0, 0, img)
    p.end()
    return qimage_png(out)


def rgb_to_qcolor(c):
    return QColor.fromRgbF(*c)


def reveal_in_folder(path):
    path = os.path.abspath(path)
    if C.IS_WIN:
        subprocess.Popen(["explorer", "/select,", path])
    else:
        QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(path) if os.path.isfile(path) else path))


def tag_pages(doc, start, n, name, src=None, gid=None):
    """Пометить страницы: из какого файла они пришли (имя, полный путь, общий код группы).
    Пометки хранятся в самих страницах PDF и сохраняются вместе с файлом."""
    import uuid
    g = fitz.get_pdf_str(gid or uuid.uuid4().hex[:10])
    nm = fitz.get_pdf_str(name)
    sp = fitz.get_pdf_str(os.path.abspath(src)) if src else None
    for i in range(start, start + n):
        x = doc[i].xref
        doc.xref_set_key(x, "LHGroup", g)
        doc.xref_set_key(x, "LHName", nm)
        if sp:
            doc.xref_set_key(x, "LHSrc", sp)


def _pdf_key(doc, i, key):
    t, v = doc.xref_get_key(doc[i].xref, key)
    return v if t == "string" else None


def replace_source_pages(doc, path, new):
    """Страницы, пришедшие из файла path, заменить свежей версией new (файл поправили в Word и т. п.).
    Каждый непрерывный кусок заменяется на месте, с тем же кодом группы (свёрнутое остаётся свёрнутым).
    Возвращает число заменённых кусков."""
    key = os.path.normcase(os.path.abspath(path))
    runs, i, n = [], 0, doc.page_count
    while i < n:
        src = _pdf_key(doc, i, "LHSrc")
        if src and os.path.normcase(src) == key:
            g = _pdf_key(doc, i, "LHGroup")
            j = i
            while j + 1 < n and _pdf_key(doc, j + 1, "LHGroup") == g:
                j += 1
            runs.append((i, j, g, _pdf_key(doc, i, "LHName") or Path(path).name))
            i = j + 1
        else:
            i += 1
    for a, b, g, name in reversed(runs):
        doc.delete_pages(a, b)
        doc.insert_pdf(new, start_at=a)
        tag_pages(doc, a, new.page_count, name, path, g)
    return len(runs)


def changes_html(changes, notes=()):
    """Подробное «Что нового»: по версиям, с пунктами; если подробностей нет — краткие заметки."""
    import html as _h
    parts = []
    for ver, title, items in changes:
        parts.append(f"<h3 style='margin:14px 0 4px 0'>Версия {_h.escape(ver)}"
                     + (f" — {_h.escape(title)}" if title else "") + "</h3>")
        lis = []
        for it in items:
            t = _h.escape(it)
            if ":" in t[:80]:                                       # «Главное: пояснение» — главное жирным
                a, b = t.split(":", 1)
                t = f"<b>{a}:</b>{b}"
            lis.append(f"<li style='margin-bottom:6px'>{t}</li>")
        parts.append("<ul style='margin-top:2px'>" + "".join(lis) + "</ul>")
    if not parts:
        parts.append("<ul>" + "".join(f"<li style='margin-bottom:6px'>{_h.escape(n)}</li>" for n in notes)
                     + "</ul>" if notes else "<p>Исправления и улучшения.</p>")
    return "".join(parts)


class WhatsNewDialog(QDialog):
    """«Что нового» перед установкой: все версии, которые пользователь пропустил, подробно."""

    def __init__(self, parent, info):
        super().__init__(parent)
        self.setWindowTitle(f"Что нового — {APP_NAME} {info['version']}")
        self.resize(640, 560)
        v = QVBoxLayout(self)
        t = QLabel(f"<b style='font-size:15pt'>Новая версия {info['version']}</b>&nbsp;&nbsp;(у вас {APP_VERSION})")
        v.addWidget(t)
        sub = QLabel("Ниже — что изменилось, по версиям. Дела, документы, шаблоны и настройки при обновлении "
                     "сохраняются.")
        sub.setObjectName("hint")
        sub.setWordWrap(True)
        v.addWidget(sub)
        br = QTextBrowser()
        br.setOpenExternalLinks(True)
        br.setHtml(changes_html(info.get("changes") or [], info.get("notes") or []))
        v.addWidget(br, 1)
        h = QHBoxLayout()
        h.addStretch(1)
        later = QPushButton("Позже")
        later.clicked.connect(self.reject)
        now = QPushButton("Установить сейчас")
        now.setObjectName("primary")
        now.setDefault(True)
        now.clicked.connect(self.accept)
        h.addWidget(later)
        h.addWidget(now)
        v.addLayout(h)


def send_to_trash(path):
    """Удалить файл в Корзину (в Windows — можно вернуть). Где Корзины нет — удалить насовсем."""
    path = os.path.abspath(path)
    if not os.path.exists(path):
        return True
    if C.IS_WIN:
        try:
            import ctypes
            from ctypes import wintypes

            class SHFILEOPSTRUCTW(ctypes.Structure):
                _fields_ = [("hwnd", wintypes.HWND), ("wFunc", ctypes.c_uint), ("pFrom", wintypes.LPCWSTR),
                            ("pTo", wintypes.LPCWSTR), ("fFlags", ctypes.c_ushort), ("fAnyOperationsAborted", wintypes.BOOL),
                            ("hNameMappings", ctypes.c_void_p), ("lpszProgressTitle", wintypes.LPCWSTR)]
            FO_DELETE, FOF_SILENT, FOF_NOCONFIRMATION, FOF_ALLOWUNDO, FOF_NOERRORUI = 3, 4, 0x10, 0x40, 0x400
            op = SHFILEOPSTRUCTW(None, FO_DELETE, path + "\0", None,
                                 FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT | FOF_NOERRORUI, False, None, None)
            if ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op)) == 0 and not os.path.exists(path):
                return True
        except Exception:
            pass
    os.remove(path)
    return True


def cleanup_junk(days=1):
    """Убрать временные файлы программы старше суток: конвертации, загрузки обновлений, кэш поиска
    по удалённым файлам. Возвращает, сколько удалено."""
    import shutil
    import time
    tmp, n = tempfile.gettempdir(), 0
    limit = time.time() - days * 86400
    try:
        names = os.listdir(tmp)
    except OSError:
        names = []
    for fn in names:
        if not (fn.startswith(("pdfm_", "lh_", "LegalHelper_update_"))
                or (fn.startswith("LegalHelper_") and fn.endswith((".zip", ".zip.part")))):
            continue
        full = os.path.join(tmp, fn)
        try:
            if os.path.getmtime(full) > limit:
                continue
            if os.path.isdir(full):
                shutil.rmtree(full, ignore_errors=True)
            else:
                os.remove(full)
            n += 1
        except OSError:
            pass
    try:                                                  # кэш поиска: строки по файлам, которых больше нет
        import sqlite3
        cp = os.path.join(data_dir(), "search_cache.sqlite")
        if os.path.exists(cp):
            con = sqlite3.connect(cp, timeout=5)
            try:
                gone = [(r[0],) for r in con.execute("SELECT path FROM texts") if not os.path.exists(r[0])]
                if gone:
                    con.executemany("DELETE FROM texts WHERE path=?", gone)
                    con.commit()
                    con.execute("VACUUM")
                    n += len(gone)
            finally:
                con.close()
    except Exception:
        pass
    return n


# =============================================================================
#  Мелкие виджеты
# =============================================================================
class ColorButton(QPushButton):
    def __init__(self, color=(0, 0, 0)):
        super().__init__()
        self.color = tuple(color)
        self.setFixedSize(46, 26)
        self.clicked.connect(self.pick)
        self._paint()

    def _paint(self):
        c = rgb_to_qcolor(self.color)
        self.setStyleSheet(f"QPushButton{{background:{c.name()};border:1px solid #888;border-radius:4px}}")

    def pick(self):
        c = QColorDialog.getColor(rgb_to_qcolor(self.color), self, "Цвет")
        if c.isValid():
            self.color = (c.redF(), c.greenF(), c.blueF())
            self._paint()


class PathEdit(QWidget):
    def __init__(self, mode="file", flt="", default=""):
        super().__init__()
        self.mode, self.flt = mode, flt
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.edit = QLineEdit(default)
        b = QPushButton("Обзор…")
        b.clicked.connect(self.browse)
        lay.addWidget(self.edit, 1)
        lay.addWidget(b)

    def browse(self):
        if self.mode == "folder":
            p = QFileDialog.getExistingDirectory(self, "Папка", self.edit.text())
        else:
            p, _ = QFileDialog.getOpenFileName(self, "Файл", self.edit.text(), self.flt)
        if p:
            self.edit.setText(p)

    def text(self):
        return self.edit.text().strip()


def font_combo(default=None):
    cb = QComboBox()
    names = list(C.available_fonts().keys()) or ["Helvetica (без кириллицы)"]
    cb.addItems(names)
    if default in names:
        cb.setCurrentText(default)
    return cb


class PagePreview(QWidget):
    """Крупный просмотр выбранной страницы справа от миниатюр: прочитать и рассмотреть."""

    def __init__(self, main):
        super().__init__()
        self.main = main
        self.index = None
        self.zoom = 1.0                           # 1.0 — по ширине окна
        v = QVBoxLayout(self)
        v.setContentsMargins(8, 8, 8, 8)
        v.setSpacing(6)
        h = QHBoxLayout()
        self.title = QLabel("Выберите страницу")
        self.title.setObjectName("hint")
        h.addWidget(self.title, 1)
        for text, tip, fn in (("−", "Мельче", lambda: self.set_zoom(self.zoom / 1.25)),
                              ("По ширине", "Вписать по ширине", lambda: self.set_zoom(1.0)),
                              ("+", "Крупнее", lambda: self.set_zoom(self.zoom * 1.25))):
            b = QPushButton(text)
            b.setObjectName("compact")
            b.setToolTip(tip)
            b.clicked.connect(fn)
            h.addWidget(b)
        close = QPushButton("✕")
        close.setObjectName("compact")
        close.setToolTip("Скрыть просмотр («Вид ▾ → Просмотр страницы крупно»)")
        close.clicked.connect(lambda: main.set_preview(False))
        h.addWidget(close)
        v.addLayout(h)
        self.sc = QScrollArea()
        self.sc.setWidgetResizable(False)
        self.sc.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
        self.sc.setObjectName("canvasArea")
        self.img = QLabel()
        self.img.setAlignment(Qt.AlignCenter)
        self.sc.setWidget(self.img)
        v.addWidget(self.sc, 1)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(90)
        self.timer.timeout.connect(self.render)

    def show_page(self, i):
        self.index = i
        self.timer.start()

    def set_zoom(self, z):
        self.zoom = max(0.3, min(4.0, z))
        self.render()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.timer.start()

    def render(self):
        doc = self.main.doc
        i = self.index
        if not self.isVisible() or i is None or not (0 <= i < doc.page_count):
            self.img.clear()
            self.title.setText("Выберите страницу слева" if doc.page_count else "Документ не открыт")
            return
        page = doc[i]
        dpr = self.devicePixelRatioF()
        width = max(200, self.sc.viewport().width() - 16) * self.zoom
        z = width / page.rect.width
        pix = page.get_pixmap(matrix=fitz.Matrix(z * dpr, z * dpr), alpha=False)
        pm = QPixmap.fromImage(to_qimage(pix))
        pm.setDevicePixelRatio(dpr)
        self.img.setPixmap(pm)
        self.img.resize(int(pix.width / dpr), int(pix.height / dpr))
        self.title.setText(f"Страница {i + 1} из {doc.page_count}")


class GrowEdit(QPlainTextEdit):
    """Поле ввода, которое не уезжает вправо: длинный текст переносится на следующую строку, а поле
    вырастает по высоте (до max_lines строк, дальше — прокрутка). Совместимо с QLineEdit: text() / setText().
    multiline=False — Enter не вставляет перевод строки (переход к следующему полю)."""
    returnPressed = Signal()

    def __init__(self, text="", placeholder="", multiline=False, max_lines=6, parent=None):
        super().__init__(parent)
        self.multiline = multiline
        self.max_lines = max_lines
        self.setTabChangesFocus(True)
        self.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.document().setDocumentMargin(2)
        if placeholder:
            self.setPlaceholderText(placeholder)
        self.textChanged.connect(self._fit)
        self.setPlainText(text or "")
        self._fit()

    # совместимость с QLineEdit
    def text(self):
        t = self.toPlainText()
        return t if self.multiline else " ".join(t.split("\n"))

    def setText(self, t):
        self.setPlainText(str(t or ""))

    def keyPressEvent(self, e):
        if not self.multiline and e.key() in (Qt.Key_Return, Qt.Key_Enter) and not e.modifiers() & Qt.ShiftModifier:
            self.returnPressed.emit()
            self.focusNextChild()
            return
        super().keyPressEvent(e)

    def insertFromMimeData(self, src):
        if not self.multiline and src.hasText():
            self.insertPlainText(" ".join(src.text().split()))
            return
        super().insertFromMimeData(src)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._fit()

    def _fit(self):
        need = int(self.document().size().height() + 0.5)
        lines = max(1, min(self.max_lines, need))
        # прокрутка — только если текста больше, чем max_lines строк
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded if need > self.max_lines else Qt.ScrollBarAlwaysOff)
        fm = self.fontMetrics()
        h = lines * fm.lineSpacing() + 2 * 2 + 18           # строки + поля документа + внутренние отступы
        if self.height() != h:
            self.setFixedHeight(h)

    def sizeHint(self):
        return QSize(260, self.height())


TOOL_EMOJI = {"Разделить PDF": "✂️", "Повернуть страницы": "🔄", "Удалить страницы": "🗑", "Извлечь страницы": "📤",
              "Вставить пустую страницу": "📄", "Размер страниц": "📐", "Сжать PDF": "🗜", "OCR": "🔤",
              "Картинки в PDF": "🖼", "HTML в PDF": "🌐", "PDF в изображения": "🖼", "Водяной знак": "💧",
              "Номера страниц": "🔢", "Обрезка PDF": "✂️", "Скрыть данные": "⬛", "Найти и выделить": "🖍",
              "Свойства документа": "ℹ️", "Защитить паролем": "🔒", "Сравнение редакций": "⚖️",
              "Нумерация листов дела": "🔢", "Штамп заверения": "🖃"}


class OptionsDialog(QDialog):
    """Универсальный диалог параметров — карточка: значок и название сверху, поля с подписями над ними
    (короткие — по два в ряд), внизу «Отмена» и главная кнопка.
    fields: (ключ, подпись, тип, значение_по_умолчанию, доп)"""
    NARROW = ("int", "float", "color", "combo", "ecombo", "font")

    def __init__(self, parent, title, fields, note=None, ok_text="Выполнить", depends=None, help=None, icon=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setObjectName("tooldlg")
        self.setMinimumWidth(520)
        self.w = {}
        self.lbls = {}
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        head = QHBoxLayout()
        head.setContentsMargins(24, 22, 24, 12)
        head.setSpacing(14)
        emoji = icon or next((e for k, e in TOOL_EMOJI.items() if title.startswith(k)), "⚙️")
        ic = QLabel()
        ic.setPixmap(modern_ui.emoji_tile(emoji, T["accent"], 48))
        ic.setFixedSize(48, 48)
        head.addWidget(ic, 0, Qt.AlignTop)
        col = QVBoxLayout()
        col.setSpacing(3)
        t = QLabel(title)
        t.setObjectName("dlgtitle")
        col.addWidget(t)
        if note:
            lab = QLabel(note)
            lab.setWordWrap(True)
            lab.setObjectName("dlgsub")
            col.addWidget(lab)
        col.addStretch(1)
        head.addLayout(col, 1)
        lay.addLayout(head)
        grid = QGridLayout()
        grid.setContentsMargins(24, 6, 24, 16)
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(10)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        r = c = 0
        kinds = [f[2] for f in fields]
        for i, f in enumerate(fields):
            key, label, kind = f[0], f[1], f[2]
            default = f[3] if len(f) > 3 else None
            extra = f[4] if len(f) > 4 else None
            w = self._make(kind, label, default, extra)
            self.w[key] = (kind, w)
            cell = QVBoxLayout()
            cell.setSpacing(5)
            if kind != "check":
                lb = QLabel(label)
                lb.setObjectName("fieldlabel")
                lb.setBuddy(w)
                self.lbls[key] = lb
                cell.addWidget(lb)
            cell.addWidget(w)
            pair = kind in self.NARROW and (c == 1 or (i + 1 < len(kinds) and kinds[i + 1] in self.NARROW))
            if pair:                                # короткое поле — по два в ряд, одинокое — на всю ширину
                grid.addLayout(cell, r, c)
                c += 1
                if c == 2:
                    r, c = r + 1, 0
            else:
                if c:
                    r, c = r + 1, 0
                grid.addLayout(cell, r, 0, 1, 2)
                r += 1
        lay.addLayout(grid)
        lay.addStretch(1)
        # depends: {поле: (управляющее_поле, функция(значение) -> bool)} — включать поле по условию
        for dep, (ctrl, cond) in (depends or {}).items():
            cw = self.w[ctrl][1]
            dw = self.w[dep][1]
            lbl = self.lbls.get(dep)

            def upd(*_, cw=cw, dw=dw, lbl=lbl, cond=cond):
                on = bool(cond(cw.currentText() if isinstance(cw, QComboBox) else
                               cw.isChecked() if isinstance(cw, QCheckBox) else cw.text()))
                dw.setEnabled(on)
                if lbl:
                    lbl.setEnabled(on)
            if isinstance(cw, QComboBox):
                cw.currentTextChanged.connect(upd)
            elif isinstance(cw, QCheckBox):
                cw.toggled.connect(upd)
            upd()
        foot = QFrame()
        foot.setObjectName("dlgfoot")
        row = QHBoxLayout(foot)
        row.setContentsMargins(24, 12, 24, 14)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText(ok_text)
        bb.button(QDialogButtonBox.Cancel).setText("Отмена")
        for b in bb.buttons():
            b.setCursor(Qt.PointingHandCursor)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        if help:                                   # кнопка «?» с подсказкой к функции
            row.addWidget(U.HelpButton(help))
            hl = QLabel("Как это работает")
            hl.setObjectName("hint")
            row.addWidget(hl)
        row.addStretch(1)
        row.addWidget(bb)
        lay.addWidget(foot)

    def _make(self, kind, label, default, extra):
        if kind == "int":
            w = QSpinBox()
            lo, hi = extra or (0, 10000)
            w.setRange(lo, hi)
            w.setValue(default or 0)
        elif kind == "float":
            w = QDoubleSpinBox()
            lo, hi = extra or (0, 10000)
            w.setRange(lo, hi)
            w.setDecimals(1)
            w.setValue(default or 0)
        elif kind == "text":
            w = GrowEdit(default or "", extra or "")
        elif kind in ("password", "pages"):
            w = QLineEdit(default or "")
            if kind == "password":
                w.setEchoMode(QLineEdit.Password)
            if kind == "pages":
                w.setPlaceholderText("все   (например: 1-3, 5, 8-)")
            if extra:
                w.setPlaceholderText(extra)
        elif kind == "multiline":
            w = QPlainTextEdit(default or "")
            w.setFixedHeight(80)
        elif kind in ("combo", "ecombo"):
            w = QComboBox()
            w.addItems(extra or [])
            w.setEditable(kind == "ecombo")
            if default:
                w.setCurrentText(default)
        elif kind == "check":
            w = QCheckBox(label)
            w.setChecked(bool(default))
        elif kind == "color":
            w = ColorButton(default or (0, 0, 0))
        elif kind == "file":
            w = PathEdit("file", extra or "", default or "")
        elif kind == "folder":
            w = PathEdit("folder", "", default or "")
        elif kind == "font":
            w = font_combo(default)
        else:
            raise ValueError(kind)
        return w

    def values(self):
        v = {}
        for key, (kind, w) in self.w.items():
            if kind in ("int", "float"):
                v[key] = w.value()
            elif kind in ("text", "password", "pages"):
                v[key] = w.text()
            elif kind == "multiline":
                v[key] = w.toPlainText()
            elif kind in ("combo", "ecombo", "font"):
                v[key] = w.currentText()
            elif kind == "check":
                v[key] = w.isChecked()
            elif kind == "color":
                v[key] = w.color
            elif kind in ("file", "folder"):
                v[key] = w.text()
        return v

    @staticmethod
    def ask(parent, title, fields, note=None, ok_text="Выполнить", depends=None, help=None, icon=None):
        d = OptionsDialog(parent, title, fields, note, ok_text, depends, help, icon)
        return d.values() if d.exec() == QDialog.Accepted else None


class Progress:
    def __init__(self, parent, title):
        self.dlg = QProgressDialog(title, "Отмена", 0, 0, parent)
        self.dlg.setWindowTitle(APP_NAME)
        self.dlg.setWindowModality(Qt.WindowModal)
        self.dlg.setMinimumDuration(0)
        self.dlg.setAutoClose(False)
        self.dlg.setAutoReset(False)
        self.dlg.setMinimumWidth(380)
        self.dlg.show()
        QApplication.processEvents()

    def __call__(self, i, total):
        if total and self.dlg.maximum() != total:
            self.dlg.setMaximum(total)
        if total:
            self.dlg.setValue(i)
        QApplication.processEvents()
        if self.dlg.wasCanceled():
            raise C.Cancelled()

    def close(self):
        if self.dlg is not None:
            self.dlg.close()
            self.dlg.deleteLater()
            self.dlg = None


# =============================================================================
#  Список страниц (миниатюры с перетаскиванием)
# =============================================================================
class PageList(QListWidget):
    orderChanged = Signal()
    filesDropped = Signal(list, int)

    def __init__(self):
        super().__init__()
        self.setViewMode(QListView.ListMode)
        self.setFlow(QListView.LeftToRight)
        self.setWrapping(True)
        self.setResizeMode(QListView.Adjust)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setDragDropMode(QAbstractItemView.InternalMove)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setSpacing(6)
        self.setUniformItemSizes(True)
        self.setObjectName("pages")

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
        else:
            super().dragEnterEvent(e)

    def dragMoveEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
        else:
            super().dragMoveEvent(e)

    def dropEvent(self, e):
        if e.mimeData().hasUrls():
            paths = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
            idx = self.indexAt(e.position().toPoint()).row()
            e.acceptProposedAction()
            self.filesDropped.emit(paths, idx)
            return
        super().dropEvent(e)
        QTimer.singleShot(0, self.orderChanged.emit)

    def paintEvent(self, e):
        super().paintEvent(e)
        if self.count() == 0:
            p = QPainter(self.viewport())
            p.setPen(QColor(T["muted"]))
            f = p.font()
            f.setPointSize(13)
            p.setFont(f)
            p.drawText(self.viewport().rect().adjusted(20, 0, -20, 0), Qt.AlignCenter | Qt.TextWordWrap,
                       getattr(self, "empty_text", "") or
                       "Перетащите сюда PDF, картинки или документы Word/Excel\n"
                       "или нажмите «Открыть» (Ctrl+O)\n\n"
                       "Страницы можно менять местами мышью")
            p.end()


# =============================================================================
#  Подпись
# =============================================================================
class SignaturePad(QWidget):
    def __init__(self):
        super().__init__()
        self.setMinimumSize(520, 200)
        self.paths = []
        self.color = QColor(15, 30, 120)
        self.setCursor(Qt.CrossCursor)

    def clear(self):
        self.paths = []
        self.update()

    def mousePressEvent(self, e):
        p = QPainterPath(e.position())
        self.paths.append(p)
        self.update()

    def mouseMoveEvent(self, e):
        if self.paths and e.buttons() & Qt.LeftButton:
            self.paths[-1].lineTo(e.position())
            self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), Qt.white)
        p.setPen(QPen(QColor("#ccc"), 1, Qt.DashLine))
        y = int(self.height() * 0.75)
        p.drawLine(20, y, self.width() - 20, y)
        p.setPen(QPen(self.color, 2.6, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        for path in self.paths:
            p.drawPath(path)
        p.end()

    def to_png(self):
        if not self.paths:
            return None
        br = QRectF()
        for path in self.paths:
            br = br.united(path.boundingRect())
        br.adjust(-6, -6, 6, 6)
        sc = 3
        img = QImage(int(br.width() * sc), int(br.height() * sc), QImage.Format_ARGB32)
        img.fill(Qt.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing)
        p.scale(sc, sc)
        p.translate(-br.topLeft())
        p.setPen(QPen(self.color, 2.6, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        for path in self.paths:
            p.drawPath(path)
        p.end()
        return qimage_png(img)


class SignatureDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Создать подпись")
        self.png = None
        lay = QVBoxLayout(self)
        self.tabs = QTabWidget()
        lay.addWidget(self.tabs)
        # 1. Нарисовать
        w1 = QWidget()
        l1 = QVBoxLayout(w1)
        self.pad = SignaturePad()
        l1.addWidget(QLabel("Распишитесь мышью или на сенсорном экране:"))
        l1.addWidget(self.pad)
        row = QHBoxLayout()
        bclr = QPushButton("Очистить")
        bclr.clicked.connect(self.pad.clear)
        self.pad_color = QComboBox()
        self.pad_color.addItems(["Синий", "Чёрный", "Красный"])
        self.pad_color.currentIndexChanged.connect(self._color)
        row.addWidget(QLabel("Цвет:"))
        row.addWidget(self.pad_color)
        row.addStretch()
        row.addWidget(bclr)
        l1.addLayout(row)
        self.tabs.addTab(w1, "Нарисовать")
        # 2. Напечатать
        w2 = QWidget()
        l2 = QVBoxLayout(w2)
        self.typed = QLineEdit()
        self.typed.setPlaceholderText("Иванов И.И.")
        self.typed_font = QComboBox()
        fams = [f for f in ("Segoe Script", "Segoe Print", "Monotype Corsiva", "Gabriola",
                            "Lucida Handwriting", "Brush Script MT", "Times New Roman")
                if f in QFontDatabase.families()] or ["Serif"]
        self.typed_font.addItems(fams)
        self.preview = QLabel()
        self.preview.setMinimumHeight(110)
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setStyleSheet("background:white;border:1px solid #ddd")
        self.typed.textChanged.connect(self._render_typed)
        self.typed_font.currentIndexChanged.connect(self._render_typed)
        l2.addWidget(QLabel("Имя или инициалы:"))
        l2.addWidget(self.typed)
        l2.addWidget(QLabel("Шрифт:"))
        l2.addWidget(self.typed_font)
        l2.addWidget(self.preview)
        self.tabs.addTab(w2, "Напечатать")
        # 3. Картинка
        w3 = QWidget()
        l3 = QVBoxLayout(w3)
        self.img_path = PathEdit("file", IMG_FILTER)
        self.remove_white = QCheckBox("Сделать белый фон прозрачным (для скана подписи/печати)")
        self.remove_white.setChecked(True)
        l3.addWidget(QLabel("Скан или фото подписи / печати:"))
        l3.addWidget(self.img_path)
        l3.addWidget(self.remove_white)
        l3.addStretch()
        self.tabs.addTab(w3, "Из файла")
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Готово — разместить на странице")
        bb.button(QDialogButtonBox.Cancel).setText("Отмена")
        bb.accepted.connect(self.finish)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _color(self, i):
        self.pad.color = [QColor(15, 30, 120), QColor(10, 10, 10), QColor(170, 20, 20)][i]
        self.pad.update()

    def _typed_image(self):
        text = self.typed.text().strip()
        if not text:
            return None
        f = QFont(self.typed_font.currentText(), 48)
        from PySide6.QtGui import QFontMetrics
        fm = QFontMetrics(f)
        w, h = fm.horizontalAdvance(text) + 30, fm.height() + 20
        img = QImage(w, h, QImage.Format_ARGB32)
        img.fill(Qt.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        p.setFont(f)
        p.setPen(self.pad.color)
        p.drawText(img.rect(), Qt.AlignCenter, text)
        p.end()
        return img

    def _render_typed(self):
        img = self._typed_image()
        self.preview.setPixmap(QPixmap.fromImage(img).scaledToHeight(80, Qt.SmoothTransformation) if img else QPixmap())

    def finish(self):
        i = self.tabs.currentIndex()
        if i == 0:
            self.png = self.pad.to_png()
        elif i == 1:
            img = self._typed_image()
            self.png = qimage_png(img) if img else None
        else:
            p = self.img_path.text()
            if p and os.path.isfile(p):
                img = QImage(p).convertToFormat(QImage.Format_ARGB32)
                if self.remove_white.isChecked():
                    for y in range(img.height()):
                        for x in range(img.width()):
                            c = img.pixelColor(x, y)
                            lum = (c.red() + c.green() + c.blue()) / 3
                            if lum > 200:
                                c.setAlpha(int(max(0, 255 - (lum - 200) * 255 / 55)))
                                img.setPixelColor(x, y, c)
                self.png = qimage_png(img)
        if not self.png:
            QMessageBox.warning(self, APP_NAME, "Подпись пустая.")
            return
        self.accept()


class TextDialog(QDialog):
    last = {"font": None, "size": 12, "color": (0, 0, 0), "align": 0}

    def __init__(self, parent, title="Текст", text="", size=None, color=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(460)
        lay = QVBoxLayout(self)
        self.edit = QPlainTextEdit(text)
        self.edit.setMinimumHeight(120)
        lay.addWidget(self.edit)
        row = QHBoxLayout()
        self.font = font_combo(self.last["font"])
        self.size = QDoubleSpinBox()
        self.size.setRange(4, 200)
        self.size.setDecimals(1)
        self.size.setValue(size or self.last["size"])
        self.color = ColorButton(color or self.last["color"])
        self.align = QComboBox()
        self.align.addItems(["Слева", "По центру", "Справа", "По ширине"])
        self.align.setCurrentIndex(self.last["align"])
        for w in (QLabel("Шрифт:"), self.font, QLabel("Размер:"), self.size, QLabel("Цвет:"),
                  self.color, self.align):
            row.addWidget(w)
        lay.addLayout(row)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Cancel).setText("Отмена")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.edit.setFocus()

    def values(self):
        v = {"text": self.edit.toPlainText(), "font": self.font.currentText(), "size": self.size.value(),
             "color": self.color.color, "align": self.align.currentIndex()}
        TextDialog.last.update({k: v[k] for k in ("font", "size", "color", "align")})
        return v


# =============================================================================
#  Редактор страницы
# =============================================================================
class PageCanvas(QLabel):
    rectDone = Signal(QRectF)
    lineDone = Signal(QPointF, QPointF)
    strokeDone = Signal(list)
    clicked = Signal(QPointF)

    def __init__(self):
        super().__init__()
        self.kind = "rect"
        self.start = None
        self.cur = None
        self.stroke = []
        self.color = QColor("#e0322b")
        self.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.setMouseTracking(False)

    def mousePressEvent(self, e):
        if e.button() != Qt.LeftButton:
            return
        pos = e.position()
        if self.kind == "point":
            self.clicked.emit(pos)
            return
        if self.kind == "none":
            return
        self.start = self.cur = pos
        self.stroke = [pos]

    def mouseMoveEvent(self, e):
        if self.start is None:
            return
        self.cur = e.position()
        if self.kind == "stroke":
            self.stroke.append(self.cur)
        self.update()

    def mouseReleaseEvent(self, e):
        if self.start is None:
            return
        a, b = self.start, e.position()
        self.start = None
        self.update()
        if self.kind == "rect":
            self.rectDone.emit(QRectF(a, b).normalized())
        elif self.kind == "line":
            self.lineDone.emit(a, b)
        elif self.kind == "stroke" and len(self.stroke) > 1:
            self.strokeDone.emit(list(self.stroke))
        self.stroke = []

    def paintEvent(self, e):
        super().paintEvent(e)
        if self.start is None:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(self.color, 1.5, Qt.DashLine))
        if self.kind == "rect":
            c = QColor(self.color)
            c.setAlpha(40)
            p.setBrush(c)
            p.drawRect(QRectF(self.start, self.cur).normalized())
        elif self.kind == "line":
            p.drawLine(self.start, self.cur)
        elif self.kind == "stroke":
            p.setPen(QPen(self.color, 2))
            for i in range(1, len(self.stroke)):
                p.drawLine(self.stroke[i - 1], self.stroke[i])
        p.end()


class PageEditor(QDialog):
    MODES = [
        ("text", "Добавить текст", "rect", "Выделите область и введите текст"),
        ("replace", "Изменить текст", "rect", "Выделите существующий текст — он будет заменён новым"),
        ("image", "Картинка", "rect", "Выделите область, куда вставить изображение"),
        ("sign", "Подпись / печать", "rect", "Выделите место для подписи"),
        ("highlight", "Маркер", "rect", "Выделите текст, чтобы подсветить его"),
        ("rect", "Прямоугольник", "rect", "Нарисуйте прямоугольник"),
        ("ellipse", "Овал", "rect", "Нарисуйте овал"),
        ("line", "Линия", "line", "Проведите линию"),
        ("arrow", "Стрелка", "line", "Проведите стрелку"),
        ("ink", "Карандаш", "stroke", "Рисуйте мышью от руки"),
        ("note", "Заметка", "point", "Щёлкните, чтобы добавить заметку-комментарий"),
        ("link", "Ссылка", "rect", "Выделите область, которая станет ссылкой"),
        ("whiteout", "Ластик (белым)", "rect", "Выделите область — содержимое будет удалено и закрашено белым"),
        ("redact", "Скрыть данные", "rect", "Выделите область — данные будут удалены безвозвратно (чёрная плашка)"),
        ("crop", "Обрезать", "rect", "Выделите область, которая останется на странице"),
        ("field_text", "Поле ввода", "rect", "Нарисуйте поле формы для ввода текста"),
        ("field_check", "Флажок", "rect", "Нарисуйте поле-флажок"),
        ("erase", "Удалить объект", "point", "Щёлкните по заметке, пометке, полю или ссылке, чтобы удалить"),
        ("quote", "Выписка в дело", "rect", "Выделите фрагмент текста — он попадёт в заметки дела с номером листа"),
    ]
    GROUPS = [("Текст", ["text", "replace", "highlight", "quote"]),
              ("Вставить", ["sign", "image", "note", "link"]),
              ("Рисовать", ["rect", "ellipse", "line", "arrow", "ink"]),
              ("Убрать", ["whiteout", "redact", "crop", "erase"]),
              ("Поля формы", ["field_text", "field_check"])]
    ICONS = {"text": "🅰", "replace": "✏️", "highlight": "🖍", "quote": "📌", "sign": "✍️", "image": "🖼",
             "note": "💬", "link": "🔗", "rect": "▭", "ellipse": "◯", "line": "╱", "arrow": "➚", "ink": "✎",
             "whiteout": "🧽", "redact": "⬛", "crop": "✂️", "erase": "🗑", "field_text": "⌨", "field_check": "☑"}

    def __init__(self, main, index, mode="text"):
        super().__init__(main)
        self.main = main
        self.index = index
        self.zoom = 1.4
        self.image_bytes = None
        self.signature = None
        self.changed = False
        self.setWindowTitle("Редактор страницы")
        self.resize(1200, 900)
        self.setWindowFlag(Qt.WindowMaximizeButtonHint, True)

        self.setObjectName("pageeditor")
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        # ---- панель инструментов слева: группы, у каждого инструмента значок
        sw = QFrame()
        sw.setObjectName("edside")
        sw.setFixedWidth(214)
        side = QVBoxLayout(sw)
        side.setContentsMargins(12, 16, 12, 12)
        side.setSpacing(1)
        head = QLabel("✎  Редактор")
        head.setObjectName("edtitle")
        side.addWidget(head)
        side.addSpacing(6)
        self.group = QButtonGroup(self)
        self.btns = {}
        modes = {m[0]: m for m in self.MODES}
        for gname, keys in self.GROUPS:
            gl = QLabel(gname.upper())
            gl.setObjectName("edgroup")
            side.addWidget(gl)
            for key in keys:
                _, label, kind, tip = modes[key]
                b = QPushButton(f"{self.ICONS.get(key, '•')}   {label}")
                b.setCheckable(True)
                b.setToolTip(tip)
                b.setFocusPolicy(Qt.NoFocus)
                b.setCursor(Qt.PointingHandCursor)
                b.setObjectName("edtool")
                self.group.addButton(b)
                b.clicked.connect(lambda _=False, k=key: self.set_mode(k))
                self.btns[key] = b
                side.addWidget(b)
            side.addSpacing(6)
        side.addStretch()
        root.addWidget(sw)

        # ---- правая часть
        right = QVBoxLayout()
        right.setContentsMargins(14, 12, 14, 12)
        right.setSpacing(10)
        topf = QFrame()
        topf.setObjectName("edbar")
        top = QHBoxLayout(topf)
        top.setContentsMargins(12, 6, 10, 6)
        top.setSpacing(8)
        self.hint_icon = QLabel()
        self.hint_icon.setObjectName("edhinticon")
        top.addWidget(self.hint_icon)
        self.hint = QLabel()
        self.hint.setObjectName("edhint")
        self.hint.setWordWrap(True)
        top.addWidget(self.hint, 1)
        lc = QLabel("Цвет")
        lc.setObjectName("edlabel")
        top.addWidget(lc)
        self.color = ColorButton((0.85, 0.1, 0.1))
        top.addWidget(self.color)
        top.addSpacing(6)
        lw = QLabel("Толщина")
        lw.setObjectName("edlabel")
        top.addWidget(lw)
        self.width = QDoubleSpinBox()
        self.width.setRange(0.5, 20)
        self.width.setValue(2)
        self.width.setFixedWidth(76)
        top.addWidget(self.width)
        right.addWidget(topf)

        self.canvas = PageCanvas()
        self.canvas.rectDone.connect(self.on_rect)
        self.canvas.lineDone.connect(self.on_line)
        self.canvas.strokeDone.connect(self.on_stroke)
        self.canvas.clicked.connect(self.on_click)
        self.scroll = QScrollArea()
        self.scroll.setWidget(self.canvas)
        self.scroll.setAlignment(Qt.AlignCenter)
        self.scroll.setObjectName("canvasArea")
        right.addWidget(self.scroll, 1)

        bottom = QHBoxLayout()
        bottom.setSpacing(8)

        def pill(*ws):
            f = QFrame()
            f.setObjectName("edpill")
            h = QHBoxLayout(f)
            h.setContentsMargins(3, 3, 3, 3)
            h.setSpacing(2)
            for w in ws:
                h.addWidget(w)
            return f

        def pbtn(text, tip):
            b = QPushButton(text)
            b.setObjectName("edpillbtn")
            b.setToolTip(tip)
            b.setCursor(Qt.PointingHandCursor)
            return b
        self.b_prev = pbtn("‹", "Предыдущая страница")
        self.b_next = pbtn("›", "Следующая страница")
        self.lbl = QLabel()
        self.lbl.setObjectName("edpilltext")
        b_zo = pbtn("−", "Уменьшить")
        b_zi = pbtn("+", "Увеличить")
        self.zoom_lbl = QLabel()
        self.zoom_lbl.setObjectName("edpilltext")
        b_fit = pbtn("По ширине", "Вписать страницу по ширине окна")
        b_fit.setStyleSheet("font-size: 9pt;")
        b_undo = QPushButton("↶  Отменить")
        b_undo.setToolTip("Отменить последнее действие (Ctrl+Z)")
        b_close = QPushButton("Готово")
        self.b_close = b_close
        b_close.setObjectName("primary")
        b_close.setMinimumWidth(110)
        self.b_prev.clicked.connect(lambda: self.goto(self.index - 1))
        self.b_next.clicked.connect(lambda: self.goto(self.index + 1))
        b_zo.clicked.connect(lambda: self.set_zoom(self.zoom / 1.2))
        b_zi.clicked.connect(lambda: self.set_zoom(self.zoom * 1.2))
        b_fit.clicked.connect(self.fit_width)
        b_undo.clicked.connect(self.undo)
        b_close.clicked.connect(self.accept)
        bottom.addWidget(pill(self.b_prev, self.lbl, self.b_next))
        bottom.addStretch()
        bottom.addWidget(pill(b_zo, self.zoom_lbl, b_zi, b_fit))
        bottom.addSpacing(6)
        bottom.addWidget(b_undo)
        bottom.addWidget(b_close)
        right.addLayout(bottom)
        root.addLayout(right, 1)

        act = QAction(self)
        act.setShortcut(QKeySequence.Undo)
        act.triggered.connect(self.undo)
        self.addAction(act)

        self.set_mode(mode)
        QTimer.singleShot(0, self.fit_width)

    # ---- служебное
    @property
    def doc(self):
        return self.main.doc

    def page(self):
        return self.doc[self.index]

    def set_mode(self, key):
        self.mode = key
        for k, label, kind, tip in self.MODES:
            if k == key:
                self.canvas.kind = kind
                self.hint.setText(f"<b>{label}.</b> {tip}")
                self.hint_icon.setText(self.ICONS.get(k, ""))
                self.btns[k].setChecked(True)
        if key == "sign" and not self.signature:
            d = SignatureDialog(self)
            if d.exec() == QDialog.Accepted:
                self.signature = d.png
        if key == "image":
            p, _ = QFileDialog.getOpenFileName(self, "Изображение", "", IMG_FILTER)
            if p:
                try:
                    self.image_bytes = C.image_bytes(p)[0]
                except Exception as e:
                    QMessageBox.warning(self, APP_NAME, str(e))

    def render(self):
        dpr = self.devicePixelRatioF()
        pix = self.page().get_pixmap(matrix=fitz.Matrix(self.zoom * dpr, self.zoom * dpr), alpha=False)
        qp = QPixmap.fromImage(to_qimage(pix))
        qp.setDevicePixelRatio(dpr)
        self.canvas.setPixmap(qp)
        self.canvas.resize(int(pix.width / dpr), int(pix.height / dpr))
        self.lbl.setText(f"  Страница {self.index + 1} из {self.doc.page_count}  ")
        if hasattr(self, "zoom_lbl"):
            self.zoom_lbl.setText(f" {round(self.zoom / 1.4 * 100)}% ")
        self.b_prev.setEnabled(self.index > 0)
        self.b_next.setEnabled(self.index < self.doc.page_count - 1)

    def set_zoom(self, z):
        self.zoom = max(0.2, min(6.0, z))
        self.render()

    def fit_width(self):
        w = self.scroll.viewport().width() - 30
        self.set_zoom(w / max(1, self.page().rect.width))

    def goto(self, i):
        if 0 <= i < self.doc.page_count:
            self.index = i
            self.render()

    def undo(self):
        if self.main.undo():
            self.index = min(self.index, self.doc.page_count - 1)
            self.render()

    def modify(self):
        self.main.push_undo()
        self.changed = True

    def to_vis(self, qr):
        z = self.zoom
        return fitz.Rect(qr.left() / z, qr.top() / z, qr.right() / z, qr.bottom() / z)

    def to_vis_pt(self, qp):
        return fitz.Point(qp.x() / self.zoom, qp.y() / self.zoom)

    def _style_annot(self, a, fill=False):
        c = self.color.color
        a.set_colors(stroke=c, fill=c if fill else None)
        a.set_border(width=self.width.value())
        a.update()

    # ---- действия
    def on_rect(self, qr):
        vis = self.to_vis(qr)
        page = self.page()
        tiny = vis.width < 4 or vis.height < 4
        u = C.vis_to_unrot_rect(page, vis)
        m = self.mode
        try:
            if m == "quote":
                if not tiny:
                    U.save_quote(self.parent(), L.quote_from_rect(page, u), self.index + 1)
                return
            if m == "text":
                d = TextDialog(self, "Добавить текст")
                if d.exec() != QDialog.Accepted or not d.values()["text"].strip():
                    return
                v = d.values()
                self.modify()
                C.write_text(page, vis, v["text"], v["size"], v["color"], v["font"], v["align"])
            elif m == "replace":
                if tiny:
                    return
                old = page.get_textbox(u).strip()
                size, color, _ = C.text_style_in_rect(page, u)
                d = TextDialog(self, "Изменить текст", old, round(size, 1), color)
                if d.exec() != QDialog.Accepted:
                    return
                v = d.values()
                self.modify()
                page.add_redact_annot(u, fill=(1, 1, 1))
                page.apply_redactions(images=getattr(fitz, "PDF_REDACT_IMAGE_NONE", 0))
                if v["text"].strip():
                    C.write_text(page, vis, v["text"], v["size"], v["color"], v["font"], v["align"])
            elif m in ("image", "sign"):
                data = self.image_bytes if m == "image" else self.signature
                if not data:
                    self.set_mode(m)
                    return
                if tiny:
                    vis = fitz.Rect(vis.x0, vis.y0, vis.x0 + 150, vis.y0 + 60)
                self.modify()
                page.insert_image(C.vis_to_shape_rect(page, vis), stream=data, keep_proportion=True,
                                  rotate=page.rotation)
            elif m == "highlight":
                words = [fitz.Rect(w[:4]) for w in page.get_text("words") if fitz.Rect(w[:4]).intersects(u)]
                self.modify()
                if words:
                    a = page.add_highlight_annot(words)
                    a.set_colors(stroke=(1, 0.9, 0.1) if self.color.color == (0.85, 0.1, 0.1) else self.color.color)
                    a.update()
                else:
                    a = page.add_rect_annot(u)
                    a.set_colors(stroke=None, fill=(1, 0.9, 0.1))
                    a.set_opacity(0.4)
                    a.set_border(width=0)
                    a.update()
            elif m in ("rect", "ellipse"):
                if tiny:
                    return
                self.modify()
                a = page.add_rect_annot(u) if m == "rect" else page.add_circle_annot(u)
                self._style_annot(a)
            elif m == "link":
                url, ok = QInputDialog.getText(self, "Ссылка", "Адрес (https://…) или номер страницы:")
                if not ok or not url.strip():
                    return
                self.modify()
                url = url.strip()
                if url.isdigit():
                    page.insert_link({"kind": fitz.LINK_GOTO, "from": u,
                                      "page": max(0, min(self.doc.page_count - 1, int(url) - 1))})
                else:
                    if "://" not in url and not url.startswith("mailto:"):
                        url = "https://" + url
                    page.insert_link({"kind": fitz.LINK_URI, "from": u, "uri": url})
            elif m in ("whiteout", "redact"):
                if tiny:
                    return
                self.modify()
                page.add_redact_annot(u, fill=(1, 1, 1) if m == "whiteout" else (0, 0, 0))
                page.apply_redactions()
            elif m == "crop":
                if tiny:
                    return
                self.modify()
                C.set_visible_crop(page, vis & page.rect)
                QTimer.singleShot(0, self.fit_width)
            elif m in ("field_text", "field_check"):
                if tiny:
                    u = C.vis_to_unrot_rect(page, fitz.Rect(vis.x0, vis.y0, vis.x0 + (160 if m == "field_text" else 14),
                                                            vis.y0 + (20 if m == "field_text" else 14)))
                name, ok = QInputDialog.getText(self, "Поле формы", "Имя поля:",
                                                text=f"{'Поле' if m == 'field_text' else 'Флажок'}_{self.index + 1}_{len(list(page.widgets())) + 1}")
                if not ok:
                    return
                self.modify()
                w = fitz.Widget()
                w.rect = u
                w.field_name = name or "field"
                if m == "field_text":
                    w.field_type = fitz.PDF_WIDGET_TYPE_TEXT
                    w.text_fontsize = 0
                    w.field_value = ""
                else:
                    w.field_type = fitz.PDF_WIDGET_TYPE_CHECKBOX
                    w.field_value = False
                w.border_color = (0.3, 0.3, 0.6)
                w.border_width = 1
                page.add_widget(w)
        except Exception as e:
            self.main.error("Не удалось выполнить действие", e)
        self.render()

    def on_line(self, a, b):
        p1, p2 = self.to_vis_pt(a), self.to_vis_pt(b)
        if abs(p1 - p2) < 3:
            return
        page = self.page()
        self.modify()
        an = page.add_line_annot(C.vis_to_unrot_point(page, p1), C.vis_to_unrot_point(page, p2))
        if self.mode == "arrow":
            an.set_line_ends(fitz.PDF_ANNOT_LE_NONE, fitz.PDF_ANNOT_LE_CLOSED_ARROW)
        self._style_annot(an, fill=self.mode == "arrow")
        self.render()

    def on_stroke(self, pts):
        page = self.page()
        self.modify()
        stroke = [tuple(C.vis_to_unrot_point(page, self.to_vis_pt(p))) for p in pts]
        a = page.add_ink_annot([stroke])
        self._style_annot(a)
        self.render()

    def on_click(self, qp):
        page = self.page()
        pt = C.vis_to_unrot_point(page, self.to_vis_pt(qp))
        if self.mode == "note":
            text, ok = QInputDialog.getMultiLineText(self, "Заметка", "Текст заметки:")
            if ok and text.strip():
                self.modify()
                a = page.add_text_annot(pt, text, icon="Comment")
                a.set_colors(stroke=(1, 0.85, 0.1))
                a.update()
        elif self.mode == "erase":
            for a in page.annots():
                if (a.rect + (-3, -3, 3, 3)).contains(pt):
                    self.modify()
                    page.delete_annot(a)
                    break
            else:
                for w in page.widgets():
                    if w.rect.contains(pt):
                        self.modify()
                        page.delete_widget(w)
                        break
                else:
                    for ln in page.get_links():
                        if ln["from"].contains(pt):
                            self.modify()
                            page.delete_link(ln)
                            break
                    else:
                        QMessageBox.information(
                            self, APP_NAME,
                            "Здесь нет удаляемого объекта.\nТекст и картинки самой страницы удаляются "
                            "инструментом «Ластик (белым)» или «Изменить текст».")
        self.render()


# =============================================================================
#  Формы и свойства
# =============================================================================
class FormsDialog(QDialog):
    def __init__(self, main):
        super().__init__(main)
        self.main = main
        self.setWindowTitle("Заполнение PDF-формы")
        self.resize(760, 560)
        lay = QVBoxLayout(self)
        self.entries = []
        for page in main.doc:
            for w in page.widgets():
                if w.field_type in (fitz.PDF_WIDGET_TYPE_BUTTON, fitz.PDF_WIDGET_TYPE_SIGNATURE):
                    continue
                self.entries.append(dict(page=page.number, xref=w.xref, type=w.field_type,
                                         name=w.field_name or "", label=w.field_label or "",
                                         value=w.field_value, choices=w.choice_values or [],
                                         on=w.on_state() if w.field_type in (fitz.PDF_WIDGET_TYPE_CHECKBOX,
                                                                              fitz.PDF_WIDGET_TYPE_RADIOBUTTON) else None))
        if not self.entries:
            lay.addWidget(QLabel("В документе нет заполняемых полей.\n\n"
                                 "Чтобы создать форму, откройте страницу в редакторе и используйте "
                                 "инструменты «Поле ввода» и «Флажок»."))
        self.table = QTableWidget(len(self.entries), 3)
        self.table.setHorizontalHeaderLabels(["Стр.", "Поле", "Значение"])
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.verticalHeader().hide()
        self.editors = []
        for r, e in enumerate(self.entries):
            self.table.setItem(r, 0, QTableWidgetItem(str(e["page"] + 1)))
            self.table.setItem(r, 1, QTableWidgetItem(e["label"] or e["name"]))
            for c in (0, 1):
                self.table.item(r, c).setFlags(Qt.ItemIsEnabled)
            t = e["type"]
            if t in (fitz.PDF_WIDGET_TYPE_CHECKBOX, fitz.PDF_WIDGET_TYPE_RADIOBUTTON):
                ed = QCheckBox()
                ed.setChecked(e["value"] not in (False, "Off", "", None))
            elif t in (fitz.PDF_WIDGET_TYPE_COMBOBOX, fitz.PDF_WIDGET_TYPE_LISTBOX):
                ed = QComboBox()
                ed.setEditable(t == fitz.PDF_WIDGET_TYPE_COMBOBOX)
                ed.addItems([c if isinstance(c, str) else str(c[-1]) for c in e["choices"]])
                ed.setCurrentText(str(e["value"] or ""))
            else:
                ed = QLineEdit(str(e["value"] or ""))
            self.table.setCellWidget(r, 2, ed)
            self.editors.append(ed)
        lay.addWidget(self.table)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Применить")
        bb.button(QDialogButtonBox.Cancel).setText("Отмена")
        self.flatten = QCheckBox("Сделать поля нередактируемыми (вшить значения в страницу)")
        lay.addWidget(self.flatten)
        bb.accepted.connect(self.apply)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def apply(self):
        if self.entries:
            self.main.push_undo()
            doc = self.main.doc
            for e, ed in zip(self.entries, self.editors):
                page = doc[e["page"]]
                w = page.load_widget(e["xref"])
                if w is None:
                    continue
                if isinstance(ed, QCheckBox):
                    w.field_value = (e["on"] or True) if ed.isChecked() else "Off"
                elif isinstance(ed, QComboBox):
                    w.field_value = ed.currentText()
                else:
                    w.field_value = ed.text()
                try:
                    w.update()
                except Exception:
                    pass
            if self.flatten.isChecked():
                try:
                    doc.bake(annots=False, widgets=True)
                except Exception:
                    data = doc.convert_to_pdf()
                    self.main.doc = fitz.open("pdf", data)
            self.main.after_change()
        self.accept()


# =============================================================================
#  Главное окно
# =============================================================================
TOOLS = [
    ("Для суда и почты", [
        ("package", "Пакет в суд / на почту", "Иск и приложения — под «Мой арбитр», ГАС «Правосудие» или Почту России"),
        ("f107", "Опись вложения (ф. 107)", "Бланк описи для ценного письма, два экземпляра на листе"),
        ("sheetnum", "Нумерация листов дела", "Номера листов в углу, разбивка на тома по 250 листов"),
        ("certify", "Штамп «Копия верна»", "Заверительная надпись на страницах"),
        ("preflight", "Проверка перед подачей", "Размер, формат, пустые и перевёрнутые страницы, текстовый слой"),
    ]),
    ("Материалы дела", [
        ("anonymize", "Обезличить (152-ФЗ)", "Скрыть ФИО, паспорта, СНИЛС, ИНН, адреса, телефоны, счета"),
        ("compare_ed", "Сравнить редакции", "Было / стало: удалённое и добавленное цветом"),
        ("board", "Карта дела (схема)", "Интеллект-карта дела в редакторе Excalidraw: факты, позиции, доказательства"),
        ("case_search", "Поиск по документам дела", "Найти слово во всех файлах сразу, с номером страницы"),
        ("quote", "Выписка с номером листа", "Выделите фрагмент — он попадёт в заметки дела"),
        ("template", "Документ по шаблону", "Заполнить шаблон Word данными дела"),
    ]),
    ("Калькуляторы", [
        ("calc_deadline", "Процессуальные сроки", "С учётом выходных, праздников и переносов"),
        ("calc_duty", "Госпошлина", "По ст. 333.19 и 333.21 НК РФ"),
        ("calc_interest", "Проценты ст. 395 ГК и неустойка", "По ключевой ставке ЦБ, с частичными оплатами"),
    ]),
    ("Страницы", [
        ("merge", "Объединить PDF", "Добавить PDF-файлы и картинки в конец документа"),
        ("organize", "Упорядочить страницы", "Перетаскивайте миниатюры мышью"),
        ("split", "Разделить PDF", "Разбить документ на несколько файлов"),
        ("rotate", "Повернуть", "Повернуть все или выбранные страницы"),
        ("delete", "Удалить страницы", "Удалить страницы по номерам"),
        ("extract", "Извлечь страницы", "Сохранить выбранные страницы в новый файл"),
        ("pagesize", "Размер страниц", "A4, A5, Letter или свой размер"),
        ("blank", "Пустая страница", "Добавить чистый лист нужного формата"),
        ("reverse", "Обратный порядок", "Развернуть порядок страниц"),
    ]),
    ("Редактирование", [
        ("edit", "Редактировать", "Текст, картинки, фигуры, пометки, ссылки"),
        ("sign", "Подписать", "Нарисовать, напечатать или вставить скан подписи/печати"),
        ("watermark", "Водяной знак", "Текст или картинка поверх страниц"),
        ("numbers", "Номера страниц", "Пронумеровать страницы"),
        ("crop", "Обрезать поля", "Обрезать поля страниц"),
        ("redact", "Скрыть данные", "Найти и безвозвратно закрасить текст"),
        ("highlight", "Найти и выделить", "Подсветить все вхождения слов"),
        ("forms", "PDF-формы", "Заполнить поля формы"),
        ("meta", "Свойства документа", "Название, автор, тема"),
    ]),
    ("Оптимизация", [
        ("compress", "Сжать", "Уменьшить размер файла"),
        ("ocr", "Распознать текст (OCR)", "Сделать скан доступным для поиска и копирования"),
        ("repair", "Восстановить", "Починить повреждённый файл"),
        ("pdfa", "PDF/A", "Архивный формат (нужен Ghostscript)"),
    ]),
    ("Конвертировать в PDF", [
        ("img2pdf", "Картинки в PDF", "JPG, PNG и др."),
        ("word2pdf", "Word в PDF", "Нужен MS Office или LibreOffice"),
        ("xls2pdf", "Excel в PDF", "Нужен MS Office или LibreOffice"),
        ("ppt2pdf", "PowerPoint в PDF", "Нужен MS Office или LibreOffice"),
        ("html2pdf", "Сайт / HTML в PDF", "Через Edge или Chrome"),
    ]),
    ("Конвертировать из PDF", [
        ("pdf2word", "В Word", "Редактируемый DOCX"),
        ("pdf2excel", "В Excel", "Таблицы в XLSX"),
        ("pdf2ppt", "В PowerPoint", "Каждая страница — слайд"),
        ("pdf2jpg", "В картинки", "JPG / PNG или извлечь изображения"),
        ("pdf2txt", "В текст", "Весь текст документа"),
        ("pdf2md", "В Markdown", "Для заметок и нейросетей"),
    ]),
    ("Защита и сравнение", [
        ("protect", "Поставить пароль", "Зашифровать PDF (AES-256)"),
        ("unlock", "Снять пароль", "Сохранить без пароля"),
        ("compare", "Сравнить два PDF", "Найти отличия между версиями"),
    ]),
]
EXPANDED = {"Для суда и почты", "Материалы дела", "Страницы"}
LEGAL_TOOLS = ["package", "f107", "sheetnum", "certify", "preflight", "anonymize", "compare_ed",
               "case_search", "quote", "template"]
# инструменты со справкой «?»
HELP_KEYS = set(LEGAL_TOOLS) | {"board", "calc_deadline", "calc_duty", "calc_interest", "ocr", "compress", "pdfa",
                                "redact", "split", "protect", "compare", "pagesize", "forms"}


EXTERNAL_EXT = {".doc", ".docx", ".rtf", ".odt", ".xls", ".xlsx", ".ppt", ".pptx", ".txt", ".excalidraw"}


class CaseNavigator(QWidget):
    """Все дела и их документы в разделе «Документ»: открыть, переключиться, закрыть."""

    def __init__(self, main):
        super().__init__()
        self.main = main
        self.setObjectName("navigator")
        self.setFixedWidth(300)
        v = QVBoxLayout(self)
        v.setContentsMargins(14, 14, 8, 10)
        v.setSpacing(8)
        head = QHBoxLayout()
        t = QLabel("Мои дела")
        t.setObjectName("navtitle")
        head.addWidget(t)
        head.addStretch(1)
        b_col = QToolButton()
        b_col.setText("Свернуть все")
        b_col.setObjectName("link")
        b_col.clicked.connect(self.collapse_all)
        head.addWidget(b_col)
        v.addLayout(head)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Найти дело или документ")
        self.search.textChanged.connect(self.apply_filter)
        v.addWidget(self.search)
        self.tree = QTreeWidget()
        self.tree.setObjectName("navtree")
        self.tree.setHeaderHidden(True)
        self.tree.setIndentation(14)
        self.tree.setTextElideMode(Qt.ElideMiddle)
        self.tree.setFocusPolicy(Qt.NoFocus)
        self.tree.itemClicked.connect(self.on_click)
        self.tree.itemDoubleClicked.connect(self.on_double)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self.menu)
        v.addWidget(self.tree, 1)
        hint = QLabel("Щелчок — открыть или перейти. Правки в других документах сохраняются, пока программа открыта.")
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        v.addWidget(hint)
        self._expanded = set()

    # ----------------------------------------------------------------- построение
    def refresh(self):
        self._remember_expanded()
        self.tree.clear()
        m = self.main
        open_paths = {}
        for i, ws in enumerate(m.all_ws()):
            if ws["path"]:
                open_paths[os.path.normcase(ws["path"])] = (i, ws)
        try:
            cases = U.db().cases()
        except Exception:
            cases = []
        cur_cid = m.ws_case()
        # открытые документы без дела
        loose = [(i, ws) for i, ws in enumerate(m.all_ws())
                 if (ws["doc"].page_count or ws["modified"]) and not ws.get("case_id")]
        if loose:
            top = self._case_item("Открытые без дела", None, len(loose))
            for i, ws in loose:
                name = Path(ws["path"]).name if ws["path"] else "Новый документ"
                self._doc_item(top, name, ws["path"], i, ws)
            top.setExpanded(True)
        for c in cases:
            docs = U.db().docs(c["id"])
            top = self._case_item(c["title"], c["id"], len(docs), c.get("number", ""))
            known = {os.path.normcase(d["path"]) for d in docs}
            unsaved_new = [(i, ws) for i, ws in enumerate(m.all_ws()) if ws.get("case_id") == c["id"]
                           and (not ws["path"] or os.path.normcase(ws["path"]) not in known)]
            for d in docs:
                hit = open_paths.get(os.path.normcase(d["path"]))
                self._doc_item(top, Path(d["path"]).name, d["path"], hit[0] if hit else None, hit[1] if hit else None)
            for i, ws in unsaved_new:
                self._doc_item(top, Path(ws["path"]).name if ws["path"] else "Новый документ", ws["path"], i, ws)
            if c["id"] == cur_cid or c["id"] in self._expanded:
                top.setExpanded(True)
        if not cases and not loose:
            it = QTreeWidgetItem(["Дел пока нет. Создайте дело в разделе «Дела»."])
            it.setFlags(Qt.ItemIsEnabled)
            self.tree.addTopLevelItem(it)
        self.apply_filter(self.search.text())

    def _case_item(self, title, cid, n, number=""):
        it = QTreeWidgetItem([title])
        it.setData(0, Qt.UserRole, ("case", cid))
        f = QFont(SERIF)
        f.setPointSizeF(11)
        it.setFont(0, f)
        it.setToolTip(0, title + (f"\n№ {number}" if number else "") + f"\nДокументов: {n}")
        if cid == self.main.ws_case() and cid is not None:
            it.setForeground(0, QColor(T["accent"]))
        self.tree.addTopLevelItem(it)
        return it

    def _doc_item(self, parent, name, path, ws_index, ws):
        cur = ws_index is not None and ws_index == self.main.cur_ws
        mark = ("●  " if ws_index is not None else "") + name + ("  •" if ws and ws["modified"] else "")
        it = QTreeWidgetItem([mark])
        it.setData(0, Qt.UserRole, ("doc", path, ws_index))
        tip = path or "ещё не сохранён"
        if ws_index is not None:
            tip += "\nОткрыт" + (", есть несохранённые изменения" if ws and ws["modified"] else "")
        if path and not os.path.exists(path):
            tip += "\nФайл не найден — возможно, перемещён"
            it.setForeground(0, QColor(T["disabled"]))
        it.setToolTip(0, tip)
        if ws_index is not None:
            it.setForeground(0, QColor(T["accent"]))
        if cur:
            f = it.font(0)
            f.setBold(True)
            it.setFont(0, f)
        parent.addChild(it)

    def _remember_expanded(self):
        for i in range(self.tree.topLevelItemCount()):
            it = self.tree.topLevelItem(i)
            d = it.data(0, Qt.UserRole)
            if d and d[0] == "case" and d[1] is not None:
                (self._expanded.add if it.isExpanded() else self._expanded.discard)(d[1])

    def collapse_all(self):
        self._expanded.clear()
        self.tree.collapseAll()

    def apply_filter(self, text):
        t = text.lower().strip()
        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            case_hit = t in top.text(0).lower() or t in (top.toolTip(0) or "").lower()
            vis = 0
            for j in range(top.childCount()):
                ch = top.child(j)
                show = not t or case_hit or t in ch.text(0).lower()
                ch.setHidden(not show)
                vis += show
            top.setHidden(bool(t) and not case_hit and vis == 0)
            if t and vis:
                top.setExpanded(True)

    # ----------------------------------------------------------------- действия
    def on_click(self, it, _c=0):
        d = it.data(0, Qt.UserRole)
        if not d:
            return
        if d[0] == "case":
            it.setExpanded(not it.isExpanded())
            return
        _k, path, ws_index = d
        cid = it.parent().data(0, Qt.UserRole)[1] if it.parent() else None
        self.main.open_from_nav(path, ws_index, cid)

    def on_double(self, it, _c=0):
        d = it.data(0, Qt.UserRole)
        if d and d[0] == "case" and d[1]:
            self.main.show_cases()
            self.main.cases_page.select_case(d[1])

    def menu(self, pos):
        it = self.tree.itemAt(pos)
        if not it:
            return
        d = it.data(0, Qt.UserRole)
        if not d:
            return
        m = QMenu(self)
        if d[0] == "case" and d[1]:
            cid = d[1]
            m.addAction("Открыть карточку дела", lambda: self.on_double(it))
            m.addAction("Добавить файлы в дело…", lambda: self.main.add_files_to_case(cid))
            m.addAction("Документ по шаблону…", lambda: U.tool_template(self.main, cid))
            m.addAction("Карта дела", lambda: self.main.tool_board(cid))
            m.addAction("Привязать открытый документ", lambda: self.main.link_current_to_case(cid))
        elif d[0] == "doc":
            _k, path, ws_index = d
            cid = it.parent().data(0, Qt.UserRole)[1] if it.parent() else None
            m.addAction("Открыть", lambda: self.on_click(it))
            if ws_index is not None:
                m.addAction("Закрыть документ", lambda: self.main.close_ws(ws_index))
            if path:
                m.addAction("Показать в папке", lambda: self.main.show_in_folder(path))
            if cid and path:
                m.addSeparator()
                m.addAction("Отвязать от дела", lambda: self.main.unlink_from_case(cid, path))
        m.exec(self.tree.viewport().mapToGlobal(pos))


class MainWindow(QMainWindow):
    updateChecked = Signal(object, str, bool)      # сведения о версии | ошибка | тихая проверка
    updateProgress = Signal(int, int)
    updateDownloaded = Signal(str, str)            # путь к архиву | ошибка
    clockChecked = Signal(object, bool)            # расхождение часов в секундах или None | тихая проверка
    for _k in LEGAL_TOOLS:
        locals()["tool_" + _k] = (lambda k: lambda self: getattr(U, "tool_" + k)(self))(_k)
    del _k

    def __init__(self):
        super().__init__()
        self.doc = fitz.open()
        self.path = None
        self.modified = False
        self.undo_stack = []
        self.redo_stack = []
        self.thumbs = []
        self.thumb_w = 150
        self.busy = False
        self.thumb_timer = QTimer(self)
        self.thumb_timer.setInterval(1)
        self.thumb_timer.timeout.connect(self.load_some_thumbs)
        self.setWindowIcon(QIcon(resource("app.ico")))
        self.resize(1400, 900)
        self.setAcceptDrops(True)
        self.cases_page = None
        self.last_case = None
        self.ws = [self._blank_ws()]      # открытые документы (рабочие области)
        self.cur_ws = 0
        U.bind(globals())
        # Окно собирается вдвое быстрее, если стили программы применить один раз в конце: иначе Qt заново
        # пересчитывает оформление при добавлении каждого из сотен элементов.
        app = QApplication.instance()
        qss = app.styleSheet() if app else ""
        if qss:
            app.setStyleSheet("")
        try:
            self._build()
        finally:
            if qss:
                app.setStyleSheet(qss)
        self.update_title()
        self.reminders = U.Reminders(self)
        polish_ui(self)
        sec = int(settings().value("section", 0) or 0)
        if sec in (1, 2):
            QTimer.singleShot(0, lambda: self.show_section(sec))
        self.updateChecked.connect(self._on_update_checked)
        self.updateProgress.connect(self._on_update_progress)
        self.updateDownloaded.connect(self._on_update_downloaded)
        self._update_info = None
        self._update_dlg = None
        self._update_cancel = False
        if self.auto_update_enabled():
            QTimer.singleShot(3000, lambda: self.check_updates(silent=True))
        QTimer.singleShot(8000, self.daily_backup)
        QTimer.singleShot(12000, self.cleanup_in_background)
        QTimer.singleShot(20000, self.phone_sync_all)
        self.tutor = None
        QTimer.singleShot(2500, lambda: tutorial.offer(self))
        self.extwatch = extwatch.ExtWatch(self)
        self.extwatch.changed.connect(self.on_external_changed)
        self.case_sync_timer = QTimer(self)
        self.case_sync_timer.setInterval(3 * 60 * 1000)      # сведения о деле — в его папку
        self.case_sync_timer.timeout.connect(self.sync_current_case)
        self.case_sync_timer.start()
        self.clockChecked.connect(self._on_clock_checked)
        self._clock_warned = False
        QTimer.singleShot(5000, lambda: self.check_clock(silent=True))
        self.clock_timer = QTimer(self)
        self.clock_timer.setInterval(6 * 3600 * 1000)
        self.clock_timer.timeout.connect(lambda: self.check_clock(silent=True))
        self.clock_timer.start()

    # ------------------------------------------------------------------ UI
    def _build(self):
        tb = QToolBar("Главная")
        tb.setMovable(False)
        tb.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        tb.setIconSize(QSize(18, 18))
        self.addToolBar(tb)
        self.toolbar = tb
        st = self.style()

        def act(text, slot, shortcut=None, icon=None, tip=None):
            a = QAction(text, self)
            if icon is not None and icon in (QStyle.SP_ArrowBack, QStyle.SP_ArrowForward):
                a.setIcon(st.standardIcon(icon))
            if shortcut:
                a.setShortcut(shortcut)
            a.setToolTip((tip or text) + (f"  ({QKeySequence(shortcut).toString()})" if shortcut else ""))
            a.triggered.connect(slot)
            return a

        self.a_open = act("Открыть", self.open_dialog, QKeySequence.Open, QStyle.SP_DialogOpenButton)
        self.a_add = act("Добавить", self.add_dialog, "Ctrl+Shift+O", QStyle.SP_FileDialogNewFolder,
                         "Добавить PDF/картинки в конец")
        self.a_save = act("Сохранить", self.save, QKeySequence.Save, QStyle.SP_DialogSaveButton)
        self.a_saveas = act("Сохранить как…", self.save_as, QKeySequence.SaveAs)
        self.a_undo = act("Отменить", self.undo, QKeySequence.Undo, QStyle.SP_ArrowBack)
        self.a_redo = act("Повторить", self.redo, QKeySequence.Redo, QStyle.SP_ArrowForward)
        self.theme_icons()
        self.a_rl = act("↺", lambda: self.rotate_selected(-90), "Ctrl+L", tip="Повернуть выбранные страницы влево")
        self.a_rr = act("↻", lambda: self.rotate_selected(90), "Ctrl+R", tip="Повернуть выбранные страницы вправо")
        self.a_del = act("Удалить", self.delete_selected, QKeySequence.Delete, QStyle.SP_TrashIcon,
                         "Удалить выбранные страницы")
        self.a_dup = act("Дублировать", self.duplicate_selected, "Ctrl+D")
        self.a_blank = act("Пустая страница", self.insert_blank)
        self.a_extract = act("Извлечь", self.extract_selected, "Ctrl+E", tip="Сохранить выбранные страницы в новый файл")
        self.a_edit = act("✎ Править", lambda: self.open_editor(), "Ctrl+Return",
                          tip="Редактировать страницу: текст, подпись, печать, маркер, скрыть данные")
        self.a_selall = act("Выделить всё", lambda: self.pages.selectAll(), QKeySequence.SelectAll)
        self.a_nav = act("Левая панель", self.toggle_nav, "Ctrl+B", tip="Показать или скрыть левую панель с делами")
        self.a_nav.setCheckable(True)
        self.a_nav.setChecked(str(settings().value("sidebar_collapsed", "0")) != "1")
        tb.addAction(self.a_nav)
        self.doc_title = QLabel("Новый документ")
        self.doc_title.setObjectName("doctitle")
        self.case_btn = QToolButton()
        self.case_btn.setObjectName("casebtn")
        self.case_btn.setPopupMode(QToolButton.InstantPopup)
        self.case_btn.setToolTip("Привязать открытый документ к делу")
        self.case_menu = QMenu(self)
        self.case_menu.aboutToShow.connect(self.fill_case_menu)
        self.case_btn.setMenu(self.case_menu)
        sep_w = QWidget()
        sep_w.setFixedWidth(10)
        tb.addWidget(sep_w)
        for a in (self.a_open, self.a_add, self.a_save):
            tb.addAction(a)
        tb.widgetForAction(self.a_save).setObjectName("tbprimary")
        mb = self.menuBar()
        mf = mb.addMenu("Файл")
        for a in (self.a_open, self.a_add, self.a_save, self.a_saveas):
            mf.addAction(a)
        mf.addSeparator()
        mf.addAction("Новый (пустой) документ", self.new_doc)
        mf.addAction("Закрыть документ", lambda: self.close_ws(), "Ctrl+W")
        mf.addSeparator()
        mf.addAction("📂 Открыть дело из папки…", lambda: U.open_case_from_folder(self))
        mf.addAction("🛟 Резервные копии…", lambda: U.BackupsDialog(self).exec())
        mf.addAction("📱 Дела на телефоне (Яндекс Диск)…", self.phone_setup)
        mf.addSeparator()
        mf.addAction("Выход", self.close)
        me = mb.addMenu("Правка")
        for a in (self.a_undo, self.a_redo, self.a_selall):
            me.addAction(a)
        me.addSeparator()
        for a in (self.a_rl, self.a_rr, self.a_del, self.a_dup, self.a_blank, self.a_extract, self.a_edit):
            me.addAction(a)
        me.addSeparator()
        me.addAction("🗑 Корзина…", self.show_trash)
        a_find = me.addAction("🔍 Поиск по всему…", lambda: palette.show(self))
        a_find.setShortcut("Ctrl+K")
        self.addAction(a_find)
        mv = mb.addMenu("Вид")
        mtheme = mv.addMenu("Тема оформления")
        grp = QActionGroup(self)
        cur = theme_choice()
        for key, label in THEME_NAMES.items():
            if key in ("coffee", "graphite"):
                mtheme.addSeparator()
            a = mtheme.addAction(label)
            if key in THEMES:                                  # цветной кружок — акцент темы
                a.setIcon(glyph_icon("●", THEMES[key]["accent"], 14))
            a.setCheckable(True)
            a.setChecked(key == cur)
            grp.addAction(a)
            a.triggered.connect(lambda _=False, k=key: self.set_theme(k))
        mv.addSeparator()
        for i, (name, key) in enumerate((("Обзор дела", "overview"), ("Документы", "docs"),
                                         ("Создать документ", "prepare"), ("Сроки", "events"),
                                         ("Деньги", "money"), ("Сведения", "info"))):
            a = mv.addAction(name, lambda key=key: self.open_case_tab(key))
            a.setShortcut(f"Ctrl+{i + 1}")
        mv.addAction(self.a_nav)
        a_anim = mv.addAction("Анимации")
        a_anim.setCheckable(True)
        a_anim.setChecked(anim.ENABLED)
        a_anim.toggled.connect(lambda on: (settings().setValue("animations", "1" if on else "0"),
                                           setattr(anim, "ENABLED", on)))
        mv.addSeparator()
        ah = mv.addAction("Главная", self.show_home)
        ah.setShortcut("Ctrl+H")
        a0 = mv.addAction("Без дела — просто PDF", lambda: self.enter_loose())
        a0.setShortcut("Ctrl+0")
        mt = mb.addMenu("Инструменты")
        for cat, items in TOOLS[3:]:
            sub = mt.addMenu(cat)
            for key, label, _tip in items:
                sub.addAction(label, getattr(self, "tool_" + key))
        ml = mb.addMenu("Юристу")
        ml.addAction("Дела и сроки", self.show_cases)
        ml.addAction("Шаблоны документов…", lambda: U.tool_template(self))
        ml.addAction("Карта дела (Excalidraw)", self.tool_board)
        ml.addAction("Мои реквизиты…", lambda: U.tool_profile(self))
        ml.addSeparator()
        for cat, items in TOOLS[:3]:
            for key, label, _tip in items:
                ml.addAction(label, getattr(self, "tool_" + key))
            ml.addSeparator()
        mh = mb.addMenu("Справка")
        a_help = mh.addAction("Руководство пользователя", lambda: self.show_section(3))
        mh.addAction("🎓 Обучение (пошагово, со стрелками)", lambda: tutorial.start(self))
        a_help.setShortcut("F1")
        self.addAction(a_help)
        mh.addSeparator()
        mh.addAction("Как пользоваться", self.tool_organize)
        mh.addAction("Проверить обновления…", lambda: self.check_updates(silent=False))
        a_auto = mh.addAction("Проверять обновления при запуске")
        a_auto.setCheckable(True)
        a_auto.setChecked(self.auto_update_enabled())
        a_auto.toggled.connect(lambda on: settings().setValue("auto_update", "1" if on else "0"))
        mh.addAction("Установить обновление из архива…", lambda: self.install_update())
        mh.addAction("Проверить часы компьютера…", lambda: self.check_clock(silent=False))
        mh.addAction("Вернуть предыдущую версию программы…", self.rollback_program)
        mh.addAction("Создать ярлык на рабочем столе", self.make_desktop_shortcut)
        mh.addAction("Журнал ошибок", self.show_error_log)
        mh.addAction("✉️  Связаться с разработчиком…", self.contact_dev)
        mh.addSeparator()
        mh.addAction("О программе", lambda: QMessageBox.about(
            self, APP_NAME, f"<b>{APP_NAME}</b> версия {APP_VERSION}<br>Рабочее место юриста и настольный редактор PDF.<br><br>"
            "Работает без интернета, файлы никуда не отправляются. В интернет программа обращается "
            "только чтобы проверить обновления на GitHub.<br>"
            "Основано на PyMuPDF (MuPDF), Qt (PySide6), pdf2docx, openpyxl, python-pptx.<br><br>"
            f"Журнал ошибок: {log_path()}"))
        tb.addSeparator()
        for a in (self.a_undo, self.a_redo):
            tb.addAction(a)
            tb.widgetForAction(a).setToolButtonStyle(Qt.ToolButtonIconOnly)
        # второй ряд — действия со страницами и «Вид» (в один ряд всё не помещается рядом со списком документов)
        tb2 = QToolBar("Страницы")
        tb2.setObjectName("pagebar")
        tb2.setMovable(False)
        tb2.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        tb2.setIconSize(QSize(16, 16))
        self.toolbar2 = tb2
        self.doc_title_act = tb2.addWidget(self.doc_title)        # «Без дела»: название и «Привязать к делу»
        self.case_btn_act = tb2.addWidget(self.case_btn)
        for a in (self.a_rl, self.a_rr, self.a_del, self.a_edit):
            tb2.addAction(a)
        for a in (self.a_selall, self.a_dup, self.a_extract):
            self.addAction(a)
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self._tb_spacer = tb.addWidget(spacer)
        spacer2 = QWidget()
        spacer2.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self._tb2_spacer = tb2.addWidget(spacer2)
        pass
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(60, 320)
        self.slider.setValue(self.thumb_w)
        self.slider.setFixedWidth(70)
        self.slider.setToolTip("Размер миниатюр")
        self.slider.valueChanged.connect(self.set_thumb_size)
        self.slider.sliderReleased.connect(lambda: settings().setValue("thumb_w", self.slider.value()))
        self.slider_act = tb2.addWidget(self.slider)
        self.slider_act.setVisible(False)             # размер миниатюр — в «Вид ▾»: место нужнее кнопкам

        # левая панель инструментов
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setIndentation(12)
        self.tree.setObjectName("tools")
        self.tree.setColumnCount(2)
        self.tree.setRootIsDecorated(True)
        self.tree.setFocusPolicy(Qt.NoFocus)
        hdr = self.tree.header()
        hdr.setStretchLastSection(False)
        hdr.setSectionResizeMode(0, QHeaderView.Stretch)
        hdr.setSectionResizeMode(1, QHeaderView.Fixed)
        hdr.resizeSection(1, 26)
        self.tree.setRootIsDecorated(False)
        for cat, items in TOOLS:
            top = QTreeWidgetItem([cat])
            top.setFlags(Qt.ItemIsEnabled)
            top.setData(0, Qt.UserRole + 1, "header")
            f = QFont(SERIF)
            f.setPointSizeF(11.5)
            top.setFont(0, f)
            top.setForeground(0, QColor(T["side_muted"]))
            top.setSizeHint(0, QSize(0, 30))
            self.tree.addTopLevelItem(top)
            for key, label, tip in items:
                it = QTreeWidgetItem([label])
                it.setData(0, Qt.UserRole, key)
                it.setToolTip(0, tip)
                it.setSizeHint(0, QSize(0, 30))
                top.addChild(it)
                if key in HELP_KEYS:
                    self.tree.setItemWidget(it, 1, U.HelpButton(key))
            top.setExpanded(cat in EXPANDED)
            self._chevron(top)
        self.tree.itemExpanded.connect(self._chevron)
        self.tree.itemCollapsed.connect(self._chevron)
        self.tree.itemClicked.connect(self.on_tool)
        self.tree.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.tree.setUniformRowHeights(True)

        self.pages = PageList()
        self.pages.orderChanged.connect(self.on_reorder)
        self.pages.filesDropped.connect(lambda paths, idx: self.open_paths(paths, insert_at=idx))
        self.pages.installEventFilter(self)
        self.pages.viewport().installEventFilter(self)
        self.pages.itemDoubleClicked.connect(self._page_double)
        self.pages.setContextMenuPolicy(Qt.CustomContextMenu)
        self.pages.customContextMenuRequested.connect(self.context_menu)
        self.pages.itemSelectionChanged.connect(self.update_status)

        # ================= «Всё вокруг дела» =================
        self.mode_cid = None           # дело, открытое сейчас (None — «Без дела»)
        self._entering = False
        # боковая панель: название, «Без дела», список дел, справка
        side = QWidget()
        side.setObjectName("sidebar")
        side.setMinimumWidth(0)
        side.setMaximumWidth(300)
        side.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
        side.resize(300, side.height())
        self.side = side
        sv = QVBoxLayout(side)
        sv.setContentsMargins(12, 16, 12, 10)
        sv.setSpacing(0)
        brand = QLabel(APP_NAME)
        brand.setObjectName("brand")
        sub = QLabel("документы, дела и сроки")
        sub.setObjectName("brandsub")
        bh = QHBoxLayout()
        bh.setContentsMargins(0, 0, 0, 0)
        bcol = QVBoxLayout()
        bcol.setSpacing(0)
        bcol.addWidget(brand)
        bcol.addWidget(sub)
        bh.addWidget(self._build_app_menu_button(), 0, Qt.AlignTop)
        bh.addSpacing(6)
        bh.addLayout(bcol, 1)
        b_fold = QToolButton()
        b_fold.setText("«")
        b_fold.setObjectName("sidefold")
        b_fold.setCursor(Qt.PointingHandCursor)
        b_fold.setToolTip("Свернуть левую панель — больше места для работы (Ctrl+B)")
        b_fold.clicked.connect(lambda: self.set_sidebar(False))
        bh.addWidget(b_fold, 0, Qt.AlignTop)
        sv.addLayout(bh)
        sv.addSpacing(10)
        gs = QPushButton("🔍   Найти что угодно…        Ctrl+K")
        gs.setObjectName("globalsearch")
        gs.setCursor(Qt.PointingHandCursor)
        gs.setToolTip("Поиск по всему: дела, документы, сроки, шаблоны, инструменты и справка")
        gs.clicked.connect(lambda: palette.show(self))
        self.b_global_search = gs
        sv.addWidget(gs)
        sv.addSpacing(8)

        self.cases_page = U.CasesPage(self)
        self.cases_page.openFile.connect(lambda p, pg: self.open_external(p, pg, self.cases_page.cid))
        self.calc_page = U.CalcPage()
        self.help_page = H.HelpPage(sys.modules[__name__])
        self.help_page.on_back = self.leave_help
        self.help_page.on_contact = self.contact_dev
        self.help_page.on_tutorial = lambda: tutorial.start(self)
        for w in (self.cases_page, self.calc_page):
            w.setObjectName("page")
        self.navigator = CaseNavigator(self)          # старая панель: не показывается
        self.navigator.hide()

        self.b_home = QPushButton("🏠   Главная")
        self.b_home.setObjectName("loosebtn")
        self.b_home.setCheckable(True)
        self.b_home.setCursor(Qt.PointingHandCursor)
        self.b_home.setToolTip("Сводка: что сегодня и на неделе, горящие сроки, недавние дела (Ctrl+H)")
        self.b_home.clicked.connect(self.show_home)
        sv.addWidget(self.b_home)
        sv.addSpacing(4)
        self.b_loose = QPushButton("📂   Без дела — просто PDF")
        self.b_loose.setObjectName("loosebtn")
        self.b_loose.setCheckable(True)
        self.b_loose.setCursor(Qt.PointingHandCursor)
        self.b_loose.setToolTip("Открыть и отредактировать PDF, не связанный с делом (Ctrl+0)")
        self.b_loose.clicked.connect(self.enter_loose)
        sv.addWidget(self.b_loose)
        sv.addSpacing(6)
        left = self.cases_page.left
        left.setParent(None)
        left.setMinimumWidth(0)
        left.layout().setContentsMargins(0, 6, 0, 6)
        for lst in (self.cases_page.list, self.cases_page.upcoming):
            lst.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            lst.setWordWrap(True)
            lst.setTextElideMode(Qt.ElideRight)
        sv.addWidget(left, 1)
        self.cases_page.list.currentItemChanged.connect(self._on_case_selected)
        # щелчок по уже выбранному делу (например, из справки) тоже возвращает к делу
        self.cases_page.list.itemClicked.connect(self._on_case_selected)
        b_help = QPushButton("?   Справка — как пользоваться")
        self.b_help_link = b_help
        b_help.setObjectName("sidelink")
        b_help.setCursor(Qt.PointingHandCursor)
        b_help.clicked.connect(lambda: self.show_section(3))
        b_trash = QPushButton("🗑   Корзина")
        self.b_trash = b_trash
        b_trash.setObjectName("sidelink")
        b_trash.setCursor(Qt.PointingHandCursor)
        b_trash.setToolTip("Удалённые дела, документы и сроки — их можно вернуть в течение 30 дней")
        b_trash.clicked.connect(self.show_trash)
        sv.addWidget(b_trash)
        sv.addWidget(b_help)
        QTimer.singleShot(0, lambda: U.refresh_trash_button(self))

        # область документа: панель инструментов + страницы
        self.removeToolBar(self.toolbar)
        self.toolbar.removeAction(self.a_nav)
        self.docarea = QWidget()
        dv = QVBoxLayout(self.docarea)
        dv.setContentsMargins(0, 0, 0, 0)
        dv.setSpacing(0)
        dv.addWidget(self.toolbar)
        dv.addWidget(self.toolbar2)
        self.page_split = QSplitter()
        self.page_split.setChildrenCollapsible(False)
        self.page_split.addWidget(self.pages)
        self.preview = PagePreview(self)
        self.preview.setMinimumWidth(280)
        self.page_split.addWidget(self.preview)
        self.page_split.setStretchFactor(0, 1)
        self.page_split.setStretchFactor(1, 1)
        dv.addWidget(self.page_split, 1)
        self.toolbar.show()
        self.toolbar2.show()
        tw = int(settings().value("thumb_w", 0) or 0)
        if tw:
            self.thumb_w = tw
            self.slider.blockSignals(True)
            self.slider.setValue(tw)
            self.slider.blockSignals(False)
            self.apply_thumb_geometry()
        self._add_tools_button()
        self._add_view_button()
        self._sync_preview()
        self.pages.itemSelectionChanged.connect(self._preview_current)

        self._restructure_case_tabs()

        # «Без дела»: открытые документы + расчёты
        self.loose_page = QWidget()
        self.loose_page.setObjectName("page")
        lv = QVBoxLayout(self.loose_page)
        lv.setContentsMargins(22, 16, 22, 10)
        lt = QLabel("Без дела")
        lt.setObjectName("title")
        lv.addWidget(lt)
        lh = QLabel("Разовая работа с PDF и расчёты. Чтобы документ попал в дело — кнопка «Привязать к делу» "
                    "над страницами.")
        lh.setObjectName("hint")
        lv.addWidget(lh)
        self.loose_tabs = QTabWidget()
        self.loose_tabs.setObjectName("segmented")
        self.loose_tabs.setDocumentMode(True)
        ld = QWidget()
        ldh = QHBoxLayout(ld)
        ldh.setContentsMargins(0, 8, 0, 0)
        lleft = QWidget()
        lleft.setFixedWidth(260)
        llv = QVBoxLayout(lleft)
        llv.setContentsMargins(0, 0, 10, 0)
        llv.addWidget(QLabel("Открытые документы"))
        self.loose_list = QListWidget()
        self.loose_list.setObjectName("overlist")
        self.loose_list.itemClicked.connect(lambda it: self.switch_ws(it.data(Qt.UserRole)))
        self.loose_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.loose_list.customContextMenuRequested.connect(self._loose_menu)
        llv.addWidget(self.loose_list, 1)
        lr = QHBoxLayout()
        bc = QPushButton("✕ Закрыть")
        bc.setObjectName("compact")
        bc.setToolTip("Закрыть выбранный документ. Правый щелчок по документу — удалить его файл в Корзину")
        bc.clicked.connect(lambda: self.close_loose())
        lr.addWidget(bc)
        bo = QPushButton("Открыть файл…")
        bo.setObjectName("primary")
        bo.clicked.connect(self.open_dialog)
        lr.addWidget(bo, 1)
        llv.addLayout(lr)
        ldh.addWidget(lleft)
        self.loose_doc_slot = self._slot()
        ldh.addWidget(self.loose_doc_slot, 1)
        self.loose_calc_slot = self._slot()
        self.loose_tabs.addTab(ld, "Документы")
        self.loose_tabs.addTab(self.loose_calc_slot, "Расчёты")
        self.loose_tabs.currentChanged.connect(lambda i: self._mount_parts())
        lv.addWidget(self.loose_tabs, 1)

        self.stack = QStackedWidget()
        self.home_page = U.HomePage(self)
        for w in (self.cases_page, self.loose_page, self.help_page, self.home_page):
            self.stack.addWidget(w)
        self.stack.currentChanged.connect(lambda *_: anim.slide_in(self.stack.currentWidget(), dy=16, ms=260))

        self.banner = QPushButton()
        self.banner.setObjectName("banner")
        self.banner.setCursor(Qt.PointingHandCursor)
        self.banner.clicked.connect(self._banner_click)
        self.banner.hide()
        self._banner_text, self._banner_cid = "", None
        self.stack.currentChanged.connect(lambda *_: self._sync_banner())

        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.setSpacing(0)
        rv.addWidget(self._build_update_bar())
        rv.addWidget(self.banner)
        rv.addWidget(self.stack, 1)
        central = QWidget()
        ch = QHBoxLayout(central)
        ch.setContentsMargins(0, 0, 0, 0)
        ch.setSpacing(0)
        ch.addWidget(side)
        ch.addWidget(self._build_rail())
        ch.addWidget(right, 1)
        self.setCentralWidget(central)
        self.addAction(self.a_nav)
        self.set_sidebar(str(settings().value("sidebar_collapsed", "0")) != "1", animate=False)
        QTimer.singleShot(60, self._initial_mode)
        self.status_lbl = QLabel()
        self.statusBar().addPermanentWidget(self.status_lbl)
        self.timer_btn = TW.TimerButton()
        self.statusBar().addPermanentWidget(self.timer_btn)
        self.apply_thumb_geometry()

    # ------------------------------------------------------------- helpers
    def update_title(self):
        w = self.ws[self.cur_ws] if getattr(self, "ws", None) else {}
        special = w.get("main") or w.get("name")
        name = Path(self.path).name if self.path else (
            (self.base_name() + ".pdf") if special else ("Новый документ" if self.doc.page_count else ""))
        star = " *" if self.modified else ""
        self.setWindowTitle(f"{name}{star} — {APP_NAME}" if name else APP_NAME)
        if hasattr(self, "doc_title"):
            if w.get("main"):
                t = "📚 PDF дела"
            elif w.get("kit"):
                t = "📦 " + (w.get("name") or "Комплект")
            else:
                t = Path(self.path).stem if self.path else "Новый документ"
            t += "  •" if self.modified else ""
            self.doc_title.setText(t if len(t) < 26 else t[:23] + "…")
            self.doc_title.setToolTip(self.path or "")
            cid = self.ws_case()
            c = U.db().case(cid) if cid else None
            title = c["title"] if c else ""
            self.case_btn.setText(("Дело: " + (title if len(title) < 32 else title[:29] + "…")) if c
                                  else "Привязать к делу")
            self.case_btn.setProperty("linked", bool(c))
            in_case = bool(getattr(self, "mode_cid", None))
            self.case_btn_act.setVisible(not in_case)      # в деле документ и так в деле
            self.doc_title_act.setVisible(True)
            self.doc_title.setToolTip(self.path or ("Будет сохранён в папку дела: " + self.case_pdf(w["case_id"])
                                                    if w.get("main") and w.get("case_id") else "ещё не сохранён"))
            self.case_btn.style().unpolish(self.case_btn)
            self.case_btn.style().polish(self.case_btn)
            self.ws[self.cur_ws]["modified"] = self.modified
            if hasattr(self, "navigator") and self.navigator.isVisible():
                QTimer.singleShot(0, self.navigator.refresh)
        self.update_status()

    def update_status(self):
        n = self.doc.page_count
        sel = len(self.pages.selectedItems())
        size = ""
        idx = self.selected() if sel else ([0] if n else [])
        if idx:
            try:
                labels = {C.page_size_label(self.doc[i]) for i in idx[:200]}
                size = "   ·   " + (labels.pop() if len(labels) == 1 else "разные размеры")
            except Exception:
                size = ""
        self.status_lbl.setText(f"Страниц: {n}" + (f"   ·   выбрано: {sel}" if sel else "") + size + "  ")

    def msg(self, text, ms=6000):
        self.statusBar().showMessage(text, ms)

    def error(self, title, exc):
        log_error(title, exc)
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle(APP_NAME)
        box.setText(f"{title}\n\n{exc}")
        box.setDetailedText("".join(traceback.format_exception(type(exc), exc, exc.__traceback__)))
        box.exec()

    # ------------------------------------------------------------- тема
    def set_theme(self, choice):
        settings().setValue("theme", choice)
        apply_theme(QApplication.instance(), choice)
        self.refresh_theme()

    def theme_icons(self):
        self.a_undo.setIcon(glyph_icon("↶", T["text"]))
        self.a_redo.setIcon(glyph_icon("↷", T["text"]))

    def refresh_theme(self):
        """Перерисовать миниатюры (подписи номеров рисуются цветом темы)."""
        self.theme_icons()
        self.tint_title_bar()
        if hasattr(self, "help_page"):
            self.help_page.refresh_theme()
        for i in range(self.tree.topLevelItemCount()):
            self.tree.topLevelItem(i).setForeground(0, QColor(T["side_muted"]))
        try:
            self.cases_page.board_tab.set_theme(T.get("name", "light"))
        except Exception:
            pass
        try:
            self.refresh_all(keep_selection=self.selected())
        except Exception:
            self.pages.viewport().update()

    # ------------------------------------------------------------- обновление и журнал
    def install_update(self, p=None, ask=True):
        if not p:
            p, _ = QFileDialog.getOpenFileName(self, f"Архив с обновлением {APP_NAME}",
                                               os.path.join(os.path.expanduser("~"), "Downloads"), "ZIP (*.zip)")
        if not p:
            return
        import zipfile, time
        try:
            with zipfile.ZipFile(p) as z:
                names = [n for n in z.namelist() if n.replace("\\", "/").endswith("update.bat")]
                if not names:
                    raise ValueError(f"В архиве нет файла update.bat — это не архив обновления {APP_NAME}.")
                dest = os.path.join(tempfile.gettempdir(), f"LegalHelper_update_{int(time.time())}")
                z.extractall(dest)
        except Exception as e:
            return self.error("Не удалось распаковать обновление", e)
        bat = os.path.join(dest, min(names, key=len))
        if ask and QMessageBox.question(
                self, APP_NAME, "Программа закроется, в отдельном окне пройдёт сборка и установка новой версии "
                                "(первый раз — до 10–15 минут, дальше быстрее).\nПосле этого программа откроется "
                                "сама.\n\nПродолжить?") != QMessageBox.Yes:
            return
        if not self.maybe_save():
            return
        self._shutdown_data()
        try:                                     # страховка: копия данных и номер версии для отката
            BK.make_backup(data_dir(), "update", APP_VERSION)
            with open(os.path.join(data_dir(), "previous_version.txt"), "w", encoding="utf-8") as f:
                f.write(APP_VERSION)
        except Exception as e:
            log_error("Резервная копия перед обновлением", e)
        try:
            if C.IS_WIN:
                subprocess.Popen(["cmd", "/c", "start", f"Обновление {APP_NAME}", "cmd", "/c", bat],
                                 cwd=os.path.dirname(bat), creationflags=0x00000008)   # DETACHED_PROCESS
            else:
                subprocess.Popen(["sh", bat], cwd=os.path.dirname(bat))
        except Exception as e:
            return self.error("Не удалось запустить обновление", e)
        self.modified = False
        QApplication.quit()

    # --- точное время
    def check_clock(self, silent=True):
        import threading
        threading.Thread(target=lambda: self.clockChecked.emit(TC.clock_offset(), silent), daemon=True).start()

    def _on_clock_checked(self, offset, silent):
        global CLOCK_OFFSET
        if offset is None:
            if not silent:
                QMessageBox.information(self, APP_NAME, "Не удалось узнать точное время — нет подключения к интернету.\n"
                                                        f"Часовой пояс компьютера: {TC.utc_offset_text()}.")
            return
        bad = abs(offset) > TC.WARN_SECONDS
        CLOCK_OFFSET = offset if bad else 0.0       # напоминания срабатывают по точному времени
        U.M.CLOCK_OFFSET = CLOCK_OFFSET             # legal_ui видит снимок globals() — обновляем и его
        if not bad:
            self._clock_warned = False
            if not silent:
                QMessageBox.information(self, APP_NAME, f"Часы компьютера идут точно (расхождение {abs(offset):.0f} с).\n"
                                                        f"Часовой пояс: {TC.utc_offset_text()}.")
            return
        if silent and self._clock_warned:
            return
        self._clock_warned = True
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle(APP_NAME)
        box.setText(f"<b>Часы компьютера {TC.describe(offset)}.</b>")
        box.setInformativeText(
            "Сроки, заседания и напоминания считаются по времени — из-за неверных часов можно пропустить "
            "событие. Напоминания программа уже поправила по точному времени, но лучше исправить часы: "
            "«Параметры Windows → Время и язык → Синхронизировать».\n\n"
            f"Часовой пояс компьютера: {TC.utc_offset_text()} (для Москвы должно быть UTC+3).")
        fix = box.addButton("Открыть настройки времени", QMessageBox.AcceptRole)
        box.addButton("Понятно", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is fix:
            try:
                os.startfile("ms-settings:dateandtime")
            except Exception:
                pass

    # --- обновления с GitHub
    def auto_update_enabled(self):
        return str(settings().value("auto_update", "1")) != "0"

    def _build_update_bar(self):
        """Плашка «Доступна новая версия» над рабочей областью (скрыта, пока обновлений нет)."""
        bar = QFrame()
        bar.setObjectName("updatebar")
        h = QHBoxLayout(bar)
        h.setContentsMargins(16, 6, 8, 6)
        h.setSpacing(8)
        self.update_lbl = QLabel()
        self.update_lbl.setObjectName("updatetext")
        self.update_lbl.setWordWrap(True)
        h.addWidget(self.update_lbl, 1)
        notes = QPushButton("Что нового")
        notes.clicked.connect(self.show_update_notes)
        install = QPushButton("Установить сейчас")
        install.setObjectName("updateinstall")
        install.clicked.connect(lambda: self.download_update())
        later = QPushButton("Позже")
        later.setToolTip("Скрыть. Напомню при следующем запуске программы.")
        later.clicked.connect(bar.hide)
        for b in (notes, install, later):
            b.setCursor(Qt.PointingHandCursor)
            h.addWidget(b)
        bar.hide()
        self.update_bar = bar
        return bar

    def check_updates(self, silent=True):
        """Проверить версию на GitHub в фоне; результат придёт в _on_update_checked."""
        import threading

        def work():
            try:
                info = UPD.fetch_info()
                if UPD.is_newer(info["version"], APP_VERSION):
                    info["changes"] = UPD.fetch_changelog(APP_VERSION)
                    if self._setup_updates():           # установленная программа: обновляемся готовым установщиком
                        info["setup"] = UPD.setup_available(info["version"])
                        info["pending"] = not info["setup"]
                self.updateChecked.emit(info, "", silent)
            except Exception as e:
                self.updateChecked.emit(None, str(e), silent)
        if not silent:
            self.statusBar().showMessage("Проверяю обновления…", 5000)
        threading.Thread(target=work, daemon=True).start()

    def _on_update_checked(self, info, err, silent):
        if err or not info:
            if not silent:
                QMessageBox.warning(self, APP_NAME, "Не удалось проверить обновления. Проверьте подключение "
                                                    f"к интернету и попробуйте позже.\n\n{err}")
            return
        if not UPD.is_newer(info["version"], APP_VERSION):
            if not silent:
                QMessageBox.information(self, APP_NAME, f"У вас последняя версия — {APP_VERSION}.")
            return
        if info.get("pending"):                     # версия вышла, а установщик GitHub ещё собирает
            if not silent:
                QMessageBox.information(self, APP_NAME, f"Вышла версия {info['version']}, её установщик сейчас "
                                        "готовится на сервере (10–15 минут). Проверьте ещё раз чуть позже — или "
                                        "программа сама предложит обновиться при следующем запуске.")
            QTimer.singleShot(20 * 60 * 1000, lambda: self.check_updates(silent=True))
            return
        self._update_info = info
        self.update_lbl.setText(f"Доступна новая версия {APP_NAME} {info['version']} (у вас {APP_VERSION}).")
        anim.slide_down(self.update_bar)
        if not silent:
            self.show_update_notes()

    def show_update_notes(self):
        info = self._update_info
        if not info:
            return
        dlg = WhatsNewDialog(self, info)
        if dlg.exec() == QDialog.Accepted:
            self.download_update()

    @staticmethod
    def _setup_updates():
        """Обновлять готовым установщиком — у собранной программы под Windows (у запуска из исходников —
        по-старому, архивом и update.bat)."""
        return C.IS_WIN and bool(getattr(sys, "frozen", False))

    def download_update(self, ask=True):
        info = self._update_info
        if not info or self._update_dlg:
            return
        setup = bool(info.get("setup"))
        text = (f"Установить версию {info['version']}?\n\nПрограмма скачает обновление (около 230 МБ), закроется, "
                "установит новую версию — появится обычное окно установки с полоской — и откроется снова "
                "(обычно 1–3 минуты). Дела, шаблоны и настройки сохранятся.") if setup else (
                f"Установить версию {info['version']}?\n\nПрограмма скачает обновление, закроется, в отдельном окне "
                "соберёт и установит новую версию (обычно 2–4 минуты, в первый раз дольше) и откроется снова. "
                "Дела, шаблоны и настройки сохранятся.")
        if ask and QMessageBox.question(self, APP_NAME, text) != QMessageBox.Yes:
            return
        if not self.maybe_save():
            return
        import threading, time
        dest = os.path.join(tempfile.gettempdir(), f"LegalHelper_{info['version']}_{int(time.time())}"
                            + (".exe" if setup else ".zip"))
        dlg = QProgressDialog("Соединяюсь с GitHub…", "Отмена", 0, 0, self)
        dlg.setWindowTitle(APP_NAME)
        dlg.setWindowModality(Qt.WindowModal)
        dlg.setMinimumDuration(0)
        dlg.setAutoClose(False)
        dlg.setAutoReset(False)
        dlg.canceled.connect(lambda: setattr(self, "_update_cancel", True))
        self._update_dlg = dlg
        self._update_cancel = False
        dlg.show()

        def work():
            try:
                prog = lambda got, total: self.updateProgress.emit(got, total)
                if setup:
                    UPD.download_setup(info["version"], dest, progress=prog, cancelled=lambda: self._update_cancel)
                else:
                    UPD.download(info["zip"], dest, progress=prog, cancelled=lambda: self._update_cancel)
                self.updateDownloaded.emit(dest, "")
            except Exception as e:
                self.updateDownloaded.emit("", str(e))
        threading.Thread(target=work, daemon=True).start()

    def _on_update_progress(self, got, total):
        dlg = self._update_dlg
        if not dlg:
            return
        mb = got / 1048576
        if total:
            dlg.setMaximum(100)
            dlg.setValue(min(99, int(got * 100 / total)))
            dlg.setLabelText(f"Скачиваю обновление… {mb:.1f} из {total / 1048576:.1f} МБ")
        else:
            dlg.setLabelText(f"Скачиваю обновление… {mb:.1f} МБ")

    def _on_update_downloaded(self, path, err):
        dlg, self._update_dlg = self._update_dlg, None
        cancelled = self._update_cancel
        if dlg:
            dlg.canceled.disconnect()          # закрытие окна тоже шлёт canceled
            dlg.close()
            dlg.deleteLater()
        if cancelled:
            return
        if err or not path:
            log_error("Не удалось скачать обновление", tb=err)
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Warning)
            box.setWindowTitle(APP_NAME)
            box.setText("<b>Не удалось скачать обновление.</b>")
            box.setInformativeText(
                "Похоже, GitHub сейчас отвечает медленно или соединение прерывается. Можно повторить или скачать "
                "архив в браузере: сохраните его, затем «☰ → Справка → Установить обновление из архива…».")
            box.setDetailedText(err or "")
            again = box.addButton("Повторить", QMessageBox.AcceptRole)
            web = box.addButton("Скачать в браузере", QMessageBox.ActionRole)
            box.addButton("Позже", QMessageBox.RejectRole)
            box.exec()
            if box.clickedButton() is again:
                QTimer.singleShot(0, lambda: self.download_update(ask=False))
            elif box.clickedButton() is web:
                info = self._update_info or {}
                QDesktopServices.openUrl(QUrl(UPD.setup_url(info["version"]) if info.get("setup")
                                              else UPD.ZIP_URLS[0]))
            return
        if path.lower().endswith(".exe"):
            self.run_setup(path)
        else:
            self.install_update(path, ask=False)

    def run_setup(self, path):
        """Поставить скачанный установщик: программа закрывается, установщик работает с обычной полоской
        (без вопросов и без командной строки) и сам открывает программу снова."""
        self._shutdown_data()
        try:                                     # страховка: копия данных и номер версии для отката
            BK.make_backup(data_dir(), "update", APP_VERSION)
            with open(os.path.join(data_dir(), "previous_version.txt"), "w", encoding="utf-8") as f:
                f.write(APP_VERSION)
        except Exception as e:
            log_error("Резервная копия перед обновлением", e)
        self._keep_previous()
        log = os.path.join(tempfile.gettempdir(), "LegalHelper_setup_log.txt")
        try:
            subprocess.Popen([path, "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS",
                              "/NOCANCEL", "/SP-", f"/LOG={log}"], creationflags=0x00000008)   # DETACHED_PROCESS
        except Exception as e:
            return self.error("Не удалось запустить установщик обновления", e)
        self.modified = False
        QApplication.quit()

    def _keep_previous(self):
        """Копия нынешней программы для «Вернуть предыдущую версию» (раньше её делал update.bat)."""
        import shutil
        prev = os.path.join(os.environ.get("LOCALAPPDATA", ""), "PDFMaster-build", "previous")
        QApplication.setOverrideCursor(Qt.WaitCursor)
        self.msg("Сохраняю копию нынешней версии на случай отката…")
        QApplication.processEvents()
        try:
            shutil.rmtree(prev, ignore_errors=True)
            shutil.copytree(os.path.dirname(sys.executable), prev,
                            ignore=shutil.ignore_patterns("unins*.*"))
        except Exception as e:
            log_error("Копия программы перед обновлением", e)
        finally:
            QApplication.restoreOverrideCursor()

    def show_error_log(self):
        p = log_path()
        if not os.path.exists(p) or os.path.getsize(p) == 0:
            QMessageBox.information(self, APP_NAME, "Ошибок пока не было — журнал пуст.")
            return
        box = QMessageBox(self)
        box.setWindowTitle(APP_NAME)
        box.setText("Если что-то работает неправильно, пришлите этот файл (или его конец) — "
                    "по нему можно найти и исправить ошибку.\n\n" + p)
        b_open = box.addButton("Показать файл в папке", QMessageBox.ActionRole)
        b_copy = box.addButton("Скопировать последние ошибки", QMessageBox.ActionRole)
        box.addButton("Закрыть", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is b_open:
            if C.IS_WIN:
                subprocess.Popen(["explorer", "/select,", p])
            else:
                QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(p)))
        elif box.clickedButton() is b_copy:
            with open(p, encoding="utf-8", errors="replace") as f:
                QApplication.clipboard().setText(f.read()[-15000:])
            self.msg("Последние ошибки скопированы — вставьте их в чат (Ctrl+V)")

    def need_doc(self):
        if self.doc.page_count == 0:
            QMessageBox.information(self, APP_NAME, "Сначала откройте PDF-файл (кнопка «Открыть» или перетащите файл в окно).")
            return False
        return True

    def _src(self):
        """Исходный файл открытого документа (например, Word, из которого получены страницы)."""
        try:
            return self.ws[self.cur_ws].get("src")
        except Exception:
            return None

    def base_name(self):
        w = self.ws[self.cur_ws] if self.ws else {}
        if w.get("main") and w.get("case_id") and not self.path:
            return Path(self.case_pdf(w["case_id"])).stem
        if w.get("name") and not self.path:
            return w["name"]
        src = self._src()
        return Path(self.path).stem if self.path else (Path(src).stem if src else "документ")

    def default_dir(self):
        if self.path:
            return str(Path(self.path).parent)
        src = self._src()
        if src and os.path.isdir(os.path.dirname(src)):
            return os.path.dirname(src)
        cid = self.ws[self.cur_ws].get("case_id") if self.ws else None
        if cid:
            try:
                return CF.ensure_folder(U.db(), cid)
            except Exception:
                pass
        docs = Path.home() / "Documents"
        return str(docs if docs.exists() else Path.home())

    def toast(self, text, ms=2600):
        """Заметное короткое сообщение поверх рабочей области («✓ Сохранено»)."""
        host = self.docarea if self.docarea.isVisible() else self
        old = getattr(self, "_toast", None)
        if old is not None:                       # новая подсказка заменяет прежнюю, а не ложится поверх
            try:
                old.deleteLater()
            except RuntimeError:
                pass
        self._toast = anim.Toast(host, text, T["text"], T["panel"], T["accent"], ms)

    def show_trash(self):
        U.TrashDialog(self).exec()

    def toast_undo(self, text, on_undo, ms=10000):
        """Плашка внизу окна: «Удалено. [Отменить]» — вместо вопросов «Вы уверены?» перед удалением."""
        old = getattr(self, "_undo_bar", None)
        if old is not None:
            try:
                old.deleteLater()
            except RuntimeError:
                pass
        bar = QFrame(self)
        self._undo_bar = bar
        bar.setObjectName("undobar")
        bar.setStyleSheet(f"QFrame#undobar {{ background: {T['text']}; border-radius: 12px; }}"
                          f"QLabel {{ color: {T['panel']}; font-weight: 600; background: transparent; }}"
                          f"QPushButton {{ color: {T['accent']}; background: {T['panel']}; border: none; "
                          "border-radius: 8px; padding: 5px 14px; font-weight: 700; }")
        h = QHBoxLayout(bar)
        h.setContentsMargins(16, 8, 8, 8)
        h.setSpacing(14)
        lab = QLabel(text)
        lab.setWordWrap(True)
        lab.setMinimumWidth(min(lab.fontMetrics().horizontalAdvance(text) + 12, 440))
        h.addWidget(lab, 1)
        b = QPushButton("Отменить")
        b.setCursor(Qt.PointingHandCursor)
        h.addWidget(b)
        done = []

        def undo():
            if done:
                return
            done.append(1)
            bar.hide()
            bar.deleteLater()
            try:
                on_undo()
            except Exception as e:
                self.error("Не удалось отменить", e)
        b.clicked.connect(undo)
        bar.setMaximumWidth(min(620, self.width() - 40))
        bar.adjustSize()
        bar.move((self.width() - bar.width()) // 2, self.height() - bar.height() - 44)
        bar.show()
        bar.raise_()
        anim.slide_in(bar, dx=0, dy=18, ms=240)
        QTimer.singleShot(ms, lambda: (not done) and _safe_delete(bar))
        return bar

    def ask_save_path(self, title, suffix, flt, name_suffix=""):
        default = os.path.join(self.default_dir(), f"{self.base_name()}{name_suffix}{suffix}")
        p, _ = QFileDialog.getSaveFileName(self, title, default, flt)
        if p and not p.lower().endswith(suffix):
            p += suffix
        return p

    def run(self, title, func, *a, **kw):
        """Выполнить долгую операцию с окном прогресса."""
        self.busy = True
        self.thumb_timer.stop()
        QApplication.setOverrideCursor(Qt.WaitCursor)
        prog = Progress(self, title)
        try:
            return func(*a, progress=prog, **kw)
        except C.Cancelled:
            self.msg("Операция отменена")
            return FAILED
        except Exception as e:
            QApplication.restoreOverrideCursor()
            prog.close()
            self.error("Ошибка: " + title.rstrip("…."), e)
            QApplication.setOverrideCursor(Qt.WaitCursor)
            return FAILED
        finally:
            prog.close()
            QApplication.restoreOverrideCursor()
            self.busy = False
            if any(t is None for t in self.thumbs):
                self.thumb_timer.start()

    def done(self, text, path=None, open_file=True):
        box = QMessageBox(self)
        box.setWindowTitle(APP_NAME)
        box.setIcon(QMessageBox.Information)
        box.setText(text)
        b_open = box.addButton("Открыть", QMessageBox.AcceptRole) if path and open_file and os.path.isfile(path) else None
        b_dir = box.addButton("Показать в папке", QMessageBox.ActionRole) if path else None
        box.addButton("OK", QMessageBox.RejectRole)
        box.exec()
        if b_open is not None and box.clickedButton() is b_open:
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))
        elif b_dir is not None and box.clickedButton() is b_dir:
            reveal_in_folder(path)

    def selected(self):
        rows = {self.pages.row(it) for it in self.pages.selectedItems()}
        for h, (_name, n) in getattr(self, "_heads", {}).items():   # свёрнутый файл = все его страницы
            if h in rows:
                rows.update(range(h, h + n))
        return sorted(r for r in rows if r < self.doc.page_count)

    def selected_or_all(self):
        return self.selected() or list(range(self.doc.page_count))

    def selected_text(self):
        """Выбранные страницы в виде текста '1-3, 5' для подстановки в диалоги."""
        sel = self.selected()
        if not sel or len(sel) == self.doc.page_count:
            return ""
        parts, start, prev = [], sel[0], sel[0]
        for s in sel[1:] + [None]:
            if s is not None and s == prev + 1:
                prev = s
                continue
            parts.append(f"{start + 1}" if start == prev else f"{start + 1}-{prev + 1}")
            if s is not None:
                start = prev = s
        return ", ".join(parts)

    def pages_arg(self, text):
        return C.parse_pages(text, self.doc.page_count)

    # ------------------------------------------------------------- undo
    def push_undo(self):
        data = self.doc.tobytes() if self.doc.page_count else None
        self.undo_stack.append(data)
        del self.undo_stack[:-25]
        spill_old(self.undo_stack)
        self.redo_stack.clear()
        self.modified = True

    def _restore(self, data):
        data = undo_data(data)
        self.doc = fitz.open("pdf", data) if data else fitz.open()

    def undo(self):
        if not self.undo_stack:
            self.msg("Нечего отменять")
            return False
        self.redo_stack.append(self.doc.tobytes() if self.doc.page_count else None)
        spill_old(self.redo_stack)
        self._restore(self.undo_stack.pop())
        self.modified = True
        self.refresh_all()
        self.msg("Действие отменено")
        return True

    def redo(self):
        if not self.redo_stack:
            return
        self.undo_stack.append(self.doc.tobytes() if self.doc.page_count else None)
        spill_old(self.undo_stack)
        self._restore(self.redo_stack.pop())
        self.refresh_all()

    def after_change(self, pages=None, keep_selection=None, thumbs=None):
        self.modified = True
        if pages is None:
            self.refresh_all(keep_selection, thumbs=thumbs)
        else:
            self.invalidate(pages)
        self.update_title()

    # ------------------------------------------------------------- thumbnails
    def cell_size(self):
        return QSize(self.thumb_w + 16, int(self.thumb_w * 1.42) + 34)

    def apply_thumb_geometry(self):
        s = self.cell_size()
        self.pages.setIconSize(s)
        self.pages.setGridSize(QSize(s.width() + 12, s.height() + 12))

    def set_thumb_size(self, v):
        self.thumb_w = v
        self.apply_thumb_geometry()
        self.refresh_all(self.selected())

    def render_thumb(self, i):
        page = self.doc[i]
        r = page.rect
        dpr = self.devicePixelRatioF()
        tw, th = self.thumb_w * dpr, self.thumb_w * 1.42 * dpr
        z = min(tw / r.width, th / r.height)
        pix = page.get_pixmap(matrix=fitz.Matrix(z, z), alpha=False)
        return to_qimage(pix)

    def compose_icon(self, i):
        icon = QIcon()
        icon.addPixmap(self._thumb_pixmap(i, False), QIcon.Normal)
        icon.addPixmap(self._thumb_pixmap(i, True), QIcon.Selected)
        return icon

    def _shadow_pm(self, s, dpr, x, y, w, h):
        """Тень под листом одинакова у всех страниц одного размера — рисуем её один раз и берём из запаса.
        Раньше тень рисовалась заново для каждой страницы, и в большом деле это заметно тормозило."""
        sc = T.get("shadow", (0, 0, 0, 40))
        key = (s.width(), s.height(), round(x, 1), round(y, 1), round(w, 1), round(h, 1), dpr, tuple(sc))
        cache = self.__dict__.setdefault("_shadow_cache", {})
        pm = cache.get(key)
        if pm is None:
            if len(cache) > 64:
                cache.clear()
            pm = QPixmap(int(s.width() * dpr), int(s.height() * dpr))
            pm.setDevicePixelRatio(dpr)
            pm.fill(Qt.transparent)
            q = QPainter(pm)
            q.setRenderHint(QPainter.Antialiasing)
            q.setPen(Qt.NoPen)
            for k, al in ((6, 0.18), (3, 0.35), (1, 0.6)):
                q.setBrush(QColor(sc[0], sc[1], sc[2], int(sc[3] * al)))
                q.drawRoundedRect(QRectF(x - k / 2, y + k / 2 + 1, w + k, h + k / 2), 2, 2)
            q.end()
            cache[key] = pm
        return pm

    def _thumb_pixmap(self, i, selected):
        s = self.cell_size()
        dpr = self.devicePixelRatioF()
        pm = QPixmap(int(s.width() * dpr), int(s.height() * dpr))
        pm.setDevicePixelRatio(dpr)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        img = self.thumbs[i] if i < len(self.thumbs) else None
        area_h = s.height() - 30
        if img is not None:
            w, h = img.width() / dpr, img.height() / dpr
        else:
            r = self.doc[i].rect
            z = min(self.thumb_w / r.width, self.thumb_w * 1.42 / r.height)
            w, h = r.width * z, r.height * z
        x, y = (s.width() - w) / 2, (area_h - h) / 2 + 6
        p.drawPixmap(0, 0, self._shadow_pm(s, dpr, x, y, w, h))   # мягкая тень листа (готовая, из запаса)
        p.setPen(Qt.NoPen)
        head = getattr(self, "_heads", {}).get(i)
        if head:                                                  # свёрнутый файл — стопка листов
            p.setPen(QPen(QColor(T["thumb_border"]), 1))
            p.setBrush(QColor("#ffffff"))
            for k in (8, 4):
                p.drawRect(QRectF(x + k, y - k, w, h))
            p.setPen(Qt.NoPen)
        if img is not None:
            p.drawImage(QRectF(x, y, w, h), img)
        else:                                   # страница ещё рисуется — заготовка с серыми «строчками»
            p.setBrush(QColor("#ffffff"))
            p.drawRect(QRectF(x, y, w, h))
            p.setBrush(QColor(0, 0, 0, 18))
            lx, ly, lw = x + w * 0.12, y + h * 0.1, w * 0.76
            p.drawRoundedRect(QRectF(lx + lw * 0.2, ly, lw * 0.6, h * 0.035), 2, 2)
            ly += h * 0.09
            for k in range(9):
                frac = 0.62 if k in (3, 8) else 1.0
                p.drawRoundedRect(QRectF(lx, ly, lw * frac, h * 0.022), 1.5, 1.5)
                ly += h * 0.055
        acc = QColor(T["accent"])
        if selected:
            p.setPen(QPen(acc, 2.2))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(QRectF(x - 4, y - 4, w + 8, h + 8), 4, 4)
        f = QFont()
        f.setPointSize(9)
        f.setBold(selected)
        p.setFont(f)
        label = str(i + 1)
        if head:
            label = p.fontMetrics().elidedText(f"{head[0]} · {head[1]} стр.", Qt.ElideMiddle, int(s.width() - 6))
        bw = min(s.width() - 2, max(24, p.fontMetrics().horizontalAdvance(label) + 14))
        br = QRectF((s.width() - bw) / 2, s.height() - 24, bw, 19)
        if selected:                                              # номер-«оттиск»
            p.setPen(Qt.NoPen)
            p.setBrush(acc)
            p.drawRoundedRect(br, 9.5, 9.5)
            p.setPen(QColor("#ffffff"))
        else:
            p.setPen(QColor(T["muted"]))
        p.drawText(br, Qt.AlignCenter, label)
        p.end()
        return pm

    def refresh_all(self, keep_selection=None, thumbs=None):
        """Перестроить список страниц. thumbs — уже готовые миниатюры в новом порядке (None — нарисовать):
        так после вставки или удаления заново рисуются только новые страницы, а не всё дело."""
        n = self.doc.page_count
        self.thumbs = list(thumbs) if thumbs is not None and len(thumbs) == n else [None] * n
        self._compute_groups()
        lst = self.pages
        lst.blockSignals(True)
        while lst.count() > n:
            lst.takeItem(lst.count() - 1)
        while lst.count() < n:
            it = QListWidgetItem()
            it.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsDragEnabled)
            lst.addItem(it)
        lst.clearSelection()
        for i in range(n):
            it = lst.item(i)
            it.setData(Qt.UserRole, i)
            it.setSizeHint(self.cell_size())
            src = self._pg[i][1] if i < len(self._pg) and self._pg[i][1] else ""
            it.setToolTip(f"Страница {i + 1}" + (f" · из файла «{src}»" if src else "") +
                          " — двойной щелчок для редактирования")
            it.setIcon(self.compose_icon(i))
        for i in range(n):
            lst.setRowHidden(i, i in self._hidden)
            if i in self._heads:
                name, cnt = self._heads[i]
                lst.item(i).setToolTip(f"{name} — {cnt} стр. Двойной щелчок — развернуть")
        for i in keep_selection or []:
            if 0 <= i < n and i not in self._hidden:
                lst.item(i).setSelected(True)
        lst.blockSignals(False)
        self._sync_preview()
        self._thumb_pos = 0
        if n:
            self.thumb_timer.start()
        self.update_title()
        lst.viewport().update()

    def invalidate(self, pages):
        for i in pages:
            if 0 <= i < len(self.thumbs):
                self.thumbs[i] = None
        self._thumb_pos = 0
        self.thumb_timer.start()

    def _visible_missing(self):
        """Страницы без миниатюры, которые сейчас видны на экране, — их рисуем первыми."""
        lst, vr = self.pages, self.pages.viewport().rect()
        out = []
        for i, t in enumerate(self.thumbs):
            if t is None and i < lst.count() and not lst.isRowHidden(i) and \
                    lst.visualItemRect(lst.item(i)).intersects(vr):
                out.append(i)
        return out

    def load_some_thumbs(self):
        """Дорисовать миниатюры понемногу (≈25 мс за раз), чтобы окно не подвисало: сначала видимые страницы."""
        if self.busy:
            return
        n = len(self.thumbs)
        clock = QElapsedTimer()
        clock.start()
        queue = self._visible_missing()
        i = getattr(self, "_thumb_pos", 0)
        while clock.elapsed() < 25:
            if queue:
                k = queue.pop(0)
            else:
                while i < n and self.thumbs[i] is not None:
                    i += 1
                if i >= n:
                    break
                k = i
            if self.thumbs[k] is None:
                try:
                    self.thumbs[k] = self.render_thumb(k)
                except Exception:
                    self.thumbs[k] = QImage()
                if k < self.pages.count():
                    self.pages.item(k).setIcon(self.compose_icon(k))
        self._thumb_pos = i
        if all(t is not None for t in self.thumbs):
            self.thumb_timer.stop()

    # ------------------------------------------------------------- files
    def password_prompt(self, name):
        pw, ok = QInputDialog.getText(self, "Пароль", f"Файл «{name}» защищён паролем.\nВведите пароль:",
                                      QLineEdit.Password)
        return pw if ok else None

    def load_file(self, p):
        """Файл любого поддерживаемого типа → fitz.Document (или None)."""
        ext = Path(p).suffix.lower()
        slow = (ext in C.OFFICE_EXT or ext in C.HTML_EXT) and not C.cached_pdf(p)
        if slow:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            self.msg(f"Готовлю {Path(p).name}…", 0)
            QApplication.processEvents()
        try:
            if slow:                                  # Word — в фоне, окно при этом не зависает
                self._convert_in_background(p)
            while True:
                try:
                    d = C.open_as_pdf(p, self.password_prompt)
                    self._check_word_pages(p, d)
                    return d
                except Exception as e:
                    if slow:
                        raise
                    raise RuntimeError(f"Не удалось открыть «{Path(p).name}»: {e}")
        except Exception as e:
            if slow:
                QApplication.restoreOverrideCursor()
                slow = False
            if getattr(self, "_quiet_load", False):   # вызывающий сам объяснит, что делать (см. add_created_doc)
                log_error(f"Файл «{Path(p).name}» не открыт", e)
            else:
                self.error(f"Файл «{Path(p).name}» не открыт", e)
            return None
        finally:
            if slow:
                QApplication.restoreOverrideCursor()
            self.statusBar().clearMessage()

    def _check_word_pages(self, p, d):
        """Сторож: в PDF не должно оказаться меньше страниц, чем насчитал сам Word. Иначе — громко сказать."""
        want = C.word_page_count(p)
        if d is None or not want or d.page_count >= want:
            return
        log_error(f"Word → PDF: в «{Path(p).name}» Word насчитал {want} стр., в PDF вышло {d.page_count}")
        QMessageBox.warning(
            self, APP_NAME,
            f"Внимание: в Word документ «{Path(p).name}» занимает {want} стр., а при переводе в PDF получилось "
            f"{d.page_count}.\n\nПроверьте последние страницы этого документа в PDF дела. Если чего-то не хватает — "
            "откройте документ в Word (правый щелчок → «Открыть в своей программе»), сохраните его там ещё раз, "
            "и программа обновит страницы.")

    def _convert_in_background(self, p):
        """Превратить Word/Excel/… в PDF в отдельном потоке и подождать, не замораживая окно.
        Результат попадает в запас (C.converted_pdf), дальше load_file открывает его мгновенно."""
        import threading
        box = {}

        def work():
            try:
                C.converted_pdf(p)
            except Exception as e:
                box["err"] = e
        th = threading.Thread(target=work, daemon=True)
        th.start()
        dlg = QProgressDialog(f"Готовлю «{Path(p).name}»…\nWord превращает документ в PDF — это несколько секунд. "
                              "В следующий раз этот файл откроется сразу.", None, 0, 0, self)
        dlg.setWindowTitle(APP_NAME)
        dlg.setWindowModality(Qt.WindowModal)
        dlg.setMinimumDuration(400)
        dlg.setCancelButton(None)
        while th.is_alive():
            QApplication.processEvents(QEventLoop.AllEvents, 40)
            th.join(0.02)
        dlg.close()
        dlg.deleteLater()
        if "err" in box:
            raise box["err"]

    def prewarm_conversions(self, paths):
        """Заранее и тихо сделать PDF из Word-файлов дела — чтобы потом перетаскивание было мгновенным."""
        todo = [p for p in paths if p and os.path.isfile(p) and Path(p).suffix.lower() in C.OFFICE_EXT
                and not C.cached_pdf(p)]
        if not todo or getattr(self, "_prewarm_busy", False):
            return
        import threading
        self._prewarm_busy = True

        def work():
            try:
                for p in todo[:30]:
                    try:
                        C.converted_pdf(p)
                    except Exception:
                        pass                      # не вышло — сделается при открытии, с понятной ошибкой
            finally:
                self._prewarm_busy = False
        threading.Thread(target=work, daemon=True).start()

    def maybe_save(self):
        if not self.modified or self.doc.page_count == 0:
            return True
        w = self.ws[self.cur_ws]
        if w.get("main") and w.get("case_id"):
            c = U.db().case(w["case_id"]) or {}
            q = f"Сохранить изменения в PDF дела «{c.get('title', '')}»?\n\nФайл: {self.case_pdf(w['case_id'])}"
        elif w.get("kit"):
            q = "Сохранить собранный комплект в файл? (Его можно в любой момент собрать заново.)"
        else:
            q = "Сохранить изменения в текущем документе?"
        r = QMessageBox.question(self, APP_NAME, q,
                                 QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel)
        if r == QMessageBox.Save:
            return self.save()
        return r == QMessageBox.Discard

    def new_doc(self):
        if self.doc.page_count or self.modified:
            self.new_ws()

    def open_dialog(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Открыть", self.default_dir(), OPEN_FILTER)
        if paths:
            self.open_paths(paths, replace=True)

    def add_dialog(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Добавить файлы", self.default_dir(), OPEN_FILTER)
        if paths:
            self.open_paths(paths)

    def open_paths(self, paths, replace=False, insert_at=None, separate=False):
        """Открыть файлы. В деле (если не separate) всё добавляется в «PDF дела» — один файл на дело."""
        paths = [p for p in paths if p and os.path.isfile(p)]
        if not paths:
            return
        case_cid = getattr(self, "mode_cid", None) if not separate else None
        if case_cid and (replace or not self.ws[self.cur_ws].get("case_id") == case_cid):
            i = self._main_ws(case_cid)
            if i != self.cur_ws:
                self._store_ws()
                self._load_ws(i)
            if len(paths) == 1 and self._same(paths[0], self.case_pdf(case_cid)):
                return
            replace = False
        in_main = bool(self.ws[self.cur_ws].get("main"))
        if replace:
            if len(paths) == 1:
                j = self.find_ws(paths[0])
                if j is not None:
                    self.switch_ws(j)
                    return
            if self.doc.page_count or self.modified:
                self.new_ws(case_id=getattr(self, "mode_cid", None))
        loaded = []
        for p in paths:
            d = self.load_file(p)
            if d is not None and d.page_count:
                loaded.append((p, d))
        if not loaded:
            return
        if replace or (self.doc.page_count == 0 and not in_main):
            if replace:
                self.undo_stack.clear()
                self.redo_stack.clear()
            first_path, first = loaded[0]
            self.doc = first
            self.path = first_path if (len(loaded) == 1 and first_path.lower().endswith(".pdf")) else None
            self.ws[self.cur_ws]["src"] = first_path
            self.modified = len(loaded) > 1 or not first_path.lower().endswith(".pdf")
            if first.page_count and self._page_group(0)[0] is None:
                self._tag_pages(0, first.page_count, Path(first_path).name, first_path)
            rest = loaded[1:]
        else:
            self.push_undo()
            rest = loaded
        pos = insert_at if insert_at is not None and 0 <= insert_at < self.doc.page_count else None
        keep = list(self.thumbs) if len(self.thumbs) == self.doc.page_count else None   # готовые миниатюры
        new_sel = []
        for p, d in rest:
            start = pos if pos is not None else self.doc.page_count
            if keep is not None:
                keep[start:start] = [None] * d.page_count
            if pos is None:
                self.doc.insert_pdf(d)
            else:
                self.doc.insert_pdf(d, start_at=pos)
                pos += d.page_count
            self._tag_pages(start, d.page_count, Path(p).name, p)
            new_sel += list(range(start, start + d.page_count))
            self.modified = True
        cid = self.ws[self.cur_ws].get("case_id")
        if replace and self.path and cid:
            try:
                if U.db().add_doc(cid, self.path):
                    self.msg("Документ добавлен в дело")
                self.cases_page.refresh_docs_if(cid)
            except Exception:
                pass
        if in_main and cid:                      # добавленные файлы — в список документов дела (сами файлы на месте)
            tmp = os.path.normcase(tempfile.gettempdir())
            try:
                for p, _d in loaded:
                    if not os.path.normcase(os.path.abspath(p)).startswith(tmp):
                        U.db().add_doc(cid, p)
                U.sync_case_file(cid)
            except Exception as ex:
                log_error("Документ в список дела", ex)
        self.refresh_all(new_sel, thumbs=keep if rest is loaded else None)
        if new_sel:
            it = self.pages.item(new_sel[0])
            if it and not it.isHidden():
                self.pages.scrollToItem(it, QAbstractItemView.PositionAtTop)
        if in_main and cid:
            self.cases_page.refresh_docs_if(cid)
            self.toast(f"＋  В PDF дела: {', '.join(Path(p).name for p, _ in loaded)[:80]}")
        self.refresh_loose_list()
        self.update_title()
        self.msg(f"Открыто файлов: {len(loaded)}, страниц в документе: {self.doc.page_count}")

    # --- «PDF дела»: все документы дела одним файлом в папке дела
    @staticmethod
    def _same(a, b):
        return bool(a and b) and os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))

    def case_pdf(self, cid):
        """Путь к PDF дела: «<папка дела>/<название дела>.pdf» (имя запоминается при первом сохранении)."""
        db = U.db()
        c = db.case(cid) or {}
        folder = CF.ensure_folder(db, cid)
        return os.path.join(folder, c.get("pdf") or (CF.clean_name(c.get("title")) + ".pdf"))

    def _main_ws(self, cid):
        """Номер открытого документа «PDF дела» (открывается с диска или создаётся пустым)."""
        for i, w in enumerate(self.ws):
            if w.get("case_id") == cid and w.get("main"):
                return i
        b = self._blank_ws()
        b.update(case_id=cid, main=True)
        try:
            p = self.case_pdf(cid)
            if os.path.exists(p):
                b["doc"] = fitz.open("pdf", Path(p).read_bytes())      # из памяти — файл не блокируется
                b["path"] = p
        except Exception as ex:
            log_error("Открытие PDF дела", ex)
        for i, w in enumerate(self.ws):                  # пустой лист этого дела — заменить, а не копить
            if w.get("case_id") == cid and not w["doc"].page_count and not w["modified"] and not w.get("kit"):
                self.ws[i] = b
                if i == self.cur_ws:
                    self._load_ws(i)
                return i
        self.ws.append(b)
        return len(self.ws) - 1

    def show_main_ws(self, cid):
        i = self._main_ws(cid)
        if i != self.cur_ws:
            self._store_ws()
            self._load_ws(i)
        return i

    def case_pdf_sources(self, cid):
        """Какие файлы (полные пути, normcase) уже вставлены в PDF дела."""
        w = next((w for w in self.ws if w.get("case_id") == cid and w.get("main")), None)
        if w is None:
            return set()
        d = self.doc if self.ws.index(w) == self.cur_ws else w["doc"]
        out = set()
        for k in range(d.page_count):
            src = _pdf_key(d, k, "LHSrc")
            if src:
                out.add(os.path.normcase(src))
        return out

    def show_in_case(self, cid, path, page=0):
        """К страницам файла в PDF дела; если его там ещё нет — добавить в конец."""
        self.show_main_ws(cid)
        key = os.path.normcase(os.path.abspath(path))
        for k in range(self.doc.page_count):
            src = _pdf_key(self.doc, k, "LHSrc")
            if src and os.path.normcase(src) == key:
                g = _pdf_key(self.doc, k, "LHGroup")
                last = k
                while last + 1 < self.doc.page_count and _pdf_key(self.doc, last + 1, "LHGroup") == g:
                    last += 1
                self.goto_page(min(k + max(0, page), last))
                return
        start = self.doc.page_count
        self.open_paths([path])
        if page and self.doc.page_count > start:
            self.goto_page(min(start + page, self.doc.page_count - 1))

    def add_created_doc(self, cid, path, open_word=False):
        """Документ, созданный по шаблону: в деле — в конец PDF дела (он уже в списке документов),
        без дела — открыть в «Без дела». При желании — сразу в Word (правки подтянутся сами)."""
        if cid:
            self.enter_case(cid)
            self.open_case_tab("docs")
            self.show_main_ws(cid)
            start = self.doc.page_count
            self._quiet_load = True
            try:
                self.open_paths([path])
            finally:
                self._quiet_load = False
            added = self.doc.page_count > start
            self.cases_page.refresh_docs_if(cid)
            if added:
                self.goto_page(start)
                self.toast(f"＋  В PDF дела: {Path(path).name}")
        else:
            self.enter_loose()
            self._quiet_load = True
            try:
                self.open_paths([path], replace=True)
            finally:
                self._quiet_load = False
            added = self.doc.page_count > 0 and self._same(self._src() or "", path)
        if not added:                            # нет Word/LibreOffice — документ всё равно создан и лежит в папке
            QMessageBox.information(self, APP_NAME, f"Документ «{Path(path).name}» создан"
                                    + (" в папке дела и добавлен в список документов." if cid else ".")
                                    + "\n\nВ PDF его добавить не удалось: для этого нужен Microsoft Word или бесплатный "
                                      "LibreOffice. Открываю его в Word.")
            open_word = True
        if open_word:
            self.open_in_app(path)
        self.msg(f"Документ создан: {path}", 8000)

    def build_case_pdf(self, cid):
        """Добавить в PDF дела все документы из списка, которых в нём ещё нет."""
        have = self.case_pdf_sources(cid)
        paths = [d["path"] for d in U.db().docs(cid) if d["path"] and os.path.exists(d["path"])
                 and os.path.normcase(os.path.abspath(d["path"])) not in have
                 and not self._same(d["path"], self.case_pdf(cid))]
        self.enter_case(cid)
        self.open_case_tab("docs")
        self.show_main_ws(cid)
        if not paths:
            self.toast("Все документы уже в PDF дела")
            return
        self.open_paths(paths)

    def remove_from_case_pdf(self, cid, path, undo=True):
        """Убрать страницы файла из PDF дела (с возможностью отменить)."""
        self.show_main_ws(cid)
        key = os.path.normcase(os.path.abspath(path))
        pages = [k for k in range(self.doc.page_count)
                 if os.path.normcase(_pdf_key(self.doc, k, "LHSrc") or "") == key]
        if not pages:
            return 0
        if undo:
            self.push_undo()
        gone = set(pages)
        keep = [t for i, t in enumerate(self.thumbs) if i not in gone] if len(self.thumbs) == self.doc.page_count else None
        self.doc.delete_pages(pages)
        self.refresh_all(thumbs=keep)
        self.update_title()
        return len(pages)

    def open_kit(self, path, name, cid):
        """Собранный комплект — отдельным документом (временным: сохраняется только по «Сохранить»)."""
        for i, w in enumerate(self.ws):
            if w.get("kit") and w.get("case_id") == cid:
                self._store_ws()
                self.ws[i]["modified"] = False
                if i == self.cur_ws:
                    self.modified = False
                self.close_ws(i)
                break
        self._store_ws()
        b = self._blank_ws()
        b.update(case_id=cid, kit=True, name=name, doc=fitz.open("pdf", Path(path).read_bytes()))
        self.ws.append(b)
        self._load_ws(len(self.ws) - 1)

    def save(self):
        if not self.need_doc():
            return False
        w = self.ws[self.cur_ws]
        if not self.path and w.get("main") and w.get("case_id"):
            return self.save_to(self.case_pdf(w["case_id"]))     # PDF дела — сразу в папку дела, без вопросов
        if not self.path:
            return self.save_as()
        return self.save_to(self.path)

    def save_as(self):
        if not self.need_doc():
            return False
        p = self.ask_save_path("Сохранить PDF", ".pdf", PDF_FILTER)
        return self.save_to(p) if p else False

    def save_to(self, p):
        try:
            C.save_pdf(self.doc, p)
        except Exception as e:
            self.error("Не удалось сохранить файл (возможно, он открыт в другой программе)", e)
            return False
        self.extwatch.refresh(p)
        self.path = p
        self.modified = False
        w = self.ws[self.cur_ws]
        cid = w.get("case_id")
        if w.get("main") and cid:
            if self._same(p, self.case_pdf(cid)):
                U.db().update_case(cid, pdf=os.path.basename(p))
                QTimer.singleShot(300, lambda c=cid: self.phone_sync(c))     # и на телефон (если настроено)
            else:                                          # «Сохранить как» под другим именем — это уже копия
                w["main"] = False
            self.cases_page.refresh_docs_if(cid)
        elif w.get("kit"):
            w["kit"] = False                               # сохранённый комплект — обычный документ дела
        if cid and not w.get("main"):
            try:
                U.db().add_doc(cid, p)
                self.cases_page.refresh_docs_if(cid)
            except Exception:
                pass
        self.update_title()
        self.msg(f"Сохранено: {p}")
        self.toast(f"✓  Сохранено: {Path(p).name}")
        return True

    def closeEvent(self, e):
        if self.save_all_ws():
            self._shutdown_data()
            U.M.settings().setValue("section", self.stack.currentIndex())
            e.accept()
        else:
            e.ignore()

    def _shutdown_data(self):
        """Сохранить всё по делам на диск: при выходе, перед обновлением и восстановлением."""
        try:
            self.cases_page.flush()
            self.overview.notes_timer.isActive() and self.overview.save_notes()
            self.overview.brief_timer.isActive() and self.overview.save_brief()
            self.cases_page.board_tab.shutdown()
        except Exception as ex:
            log_error("Сохранение дел при выходе", ex)
        U.sync_case_file(self.mode_cid or self.last_case)
        self.phone_sync(self.mode_cid or self.last_case)

    # --- сохранность данных
    def daily_backup(self):
        import threading

        def work():
            try:
                if BK.needs_daily():
                    BK.make_backup(data_dir(), "auto", APP_VERSION)
            except Exception as ex:
                log_error("Ежедневная резервная копия", ex)
        threading.Thread(target=work, daemon=True).start()

    def cleanup_in_background(self):
        import threading

        def work():
            cleanup_undo_files()
            try:
                cleanup_junk()
            except Exception as ex:
                log_error("Очистка временных файлов", ex)
        threading.Thread(target=work, daemon=True).start()

    def forget_open_file(self, path):
        """Закрыть документ этого файла, если он открыт (без вопроса о сохранении — файл удаляется)."""
        i = self.find_ws(path)
        while i is not None:
            if i == self.cur_ws:
                self.modified = False
            self.ws[i]["modified"] = False
            self.close_ws(i)
            i = self.find_ws(path)
        self.refresh_loose_list()

    def delete_file_completely(self, path):
        """Закрыть файл в программе и удалить его в Корзину. True — удалён."""
        try:
            self.forget_open_file(path)
            send_to_trash(path)
            return True
        except Exception as ex:
            QMessageBox.warning(self, "Удаление", f"Не удалось удалить файл:\n{path}\n\n{ex}\n\n"
                                "Возможно, он открыт в другой программе (Word, просмотрщик PDF).")
            return False

    def close_loose(self, it=None, delete=False):
        """«Без дела»: закрыть документ (и при желании удалить его файл)."""
        it = it or self.loose_list.currentItem()
        i = it.data(Qt.UserRole) if it else None
        if i is None or not (0 <= i < len(self.ws)):
            return
        path = self.ws[i]["path"]
        if delete and path:
            if QMessageBox.question(self, "Удалить файл",
                                    f"Удалить файл «{Path(path).name}» в Корзину?\n\nЕго можно будет вернуть "
                                    "из Корзины Windows.") != QMessageBox.Yes:
                return
            if self.delete_file_completely(path):
                self.toast(f"🗑  Удалён в Корзину: {Path(path).name}")
        else:
            self.close_ws(i)
        self.refresh_loose_list()

    def _loose_menu(self, pos):
        it = self.loose_list.itemAt(pos)
        if not it or it.data(Qt.UserRole) is None:
            return
        m = QMenu(self)
        m.addAction("Закрыть", lambda: self.close_loose(it))
        a = m.addAction("🗑  Закрыть и удалить файл в Корзину", lambda: self.close_loose(it, delete=True))
        a.setEnabled(bool(self.ws[it.data(Qt.UserRole)]["path"]))
        m.exec(self.loose_list.viewport().mapToGlobal(pos))

    def sync_current_case(self):
        U.sync_case_file(self.mode_cid)
        self.phone_sync(self.mode_cid)

    # --- дела на телефоне (Яндекс Диск, см. phone_export.py)
    def phone_base(self):
        st = settings()
        base = st.value("phone/base", "") or ""
        return base if str(st.value("phone/on", "0")) == "1" and base and os.path.isdir(base) else None

    def _phone_selected(self):
        return set(filter(None, str(settings().value("phone/cases", "") or "").split(",")))

    def phone_sync(self, cid, force=False):
        """Обновить файл дела на Яндекс Диске (если настроено и что-то поменялось). Возвращает путь или None."""
        base = self.phone_base()
        if not cid or not base:
            return None
        try:
            db = U.db()
            c = db.case(cid)
            if not c:
                return None
            if c.get("archived"):
                PHX.remove_case_file(db, cid, base, settings())
                return None
            if settings().value("phone/mode", "all") == "manual" and not force and \
                    (c.get("uid") or str(cid)) not in self._phone_selected():
                return None
            return PHX.export_case(db, cid, base, self.case_pdf(cid), settings(), force=force)
        except Exception as ex:
            log_error("Дела на телефоне (Яндекс Диск)", ex)
            return None

    def phone_sync_all(self):
        """При запуске — по одному делу, чтобы не задерживать окно."""
        if not self.phone_base():
            return
        try:
            ids = [c["id"] for c in U.db().cases()]
        except Exception:
            return

        def step():
            if ids:
                self.phone_sync(ids.pop(0))
                QTimer.singleShot(400, step)
        step()

    def phone_setup(self):
        if U.PhoneSetupDialog(self).exec():
            self.phone_sync_all()
            return True
        return False

    def phone_button(self, cid):
        """«📱 На телефон» в деле: при первом разе — помощник настройки, потом — отправить сейчас."""
        if not self.phone_base():
            if not self.phone_setup() or not self.phone_base():
                return
        c = U.db().case(cid) or {}
        sel = self._phone_selected()
        sel.add(c.get("uid") or str(cid))
        settings().setValue("phone/cases", ",".join(sorted(sel)))
        if self.modified and self.ws[self.cur_ws].get("main") and self.ws[self.cur_ws].get("case_id") == cid:
            if QMessageBox.question(self, APP_NAME, "В PDF дела есть несохранённые изменения. Сохранить, чтобы они "
                                    "тоже попали на телефон?") == QMessageBox.Yes:
                self.save()
        self.overview.brief_timer.isActive() and self.overview.save_brief()
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            p = self.phone_sync(cid, force=True)
        finally:
            QApplication.restoreOverrideCursor()
        if p:
            self.toast(f"📱  На телефоне: {Path(p).name}")
            box = QMessageBox(self)
            box.setWindowTitle("Дело на телефоне")
            box.setIcon(QMessageBox.Information)
            box.setText(f"<b>Готово!</b> Дело отправлено в Яндекс Диск:<br>«LegalHelper — дела» → {html.escape(Path(p).name)}")
            box.setInformativeText("Через минуту-две оно появится на телефоне в приложении «Яндекс Диск», в папке "
                                   "«LegalHelper — дела». Дальше файл будет обновляться сам после каждого "
                                   "сохранения дела.")
            b_how = box.addButton("Как открыть на телефоне?", QMessageBox.HelpRole)
            b_dir = box.addButton("Показать папку", QMessageBox.ActionRole)
            box.addButton("OK", QMessageBox.AcceptRole)
            box.exec()
            if box.clickedButton() is b_dir:
                self.show_in_folder(p)
            elif box.clickedButton() is b_how:
                d = U.PhoneSetupDialog(self)
                d.pages.setCurrentIndex(2)
                d.update_nav()
                d.exec()
        else:
            QMessageBox.warning(self, APP_NAME, "Не получилось отправить дело на телефон. Проверьте, что программа "
                                "«Яндекс Диск» установлена и вы в неё вошли («☰ → Файл → 📱 Дела на телефоне»). "
                                "Подробности — «☰ → Справка → Журнал ошибок».")

    def restore_backup(self, path):
        if not self.save_all_ws():
            return
        self._shutdown_data()
        try:
            U.db().close()
            U._db = None
            BK.restore(path, data_dir(), APP_VERSION)
        except Exception as ex:
            self.error("Не удалось восстановить из резервной копии", ex)
            return
        restart_app()

    def contact_dev(self):
        """Почта и Telegram разработчика; письмо — сразу с версией программы и последними ошибками."""
        dlg = QDialog(self)
        dlg.setWindowTitle("Связаться с разработчиком")
        dlg.setMinimumWidth(460)
        v = QVBoxLayout(dlg)
        v.setContentsMargins(22, 18, 22, 16)
        v.setSpacing(10)
        t = QLabel("Связаться с разработчиком")
        t.setObjectName("title")
        v.addWidget(t)
        info = QLabel("Нашли ошибку, есть идея или вопрос — напишите. Если что-то сломалось, приложите снимок экрана "
                      "и опишите, что делали.")
        info.setWordWrap(True)
        v.addWidget(info)

        def row(icon, text, open_url, copy_text):
            h = QHBoxLayout()
            lab = QLabel(f"{icon}  <b>{text}</b>")
            lab.setTextInteractionFlags(Qt.TextSelectableByMouse)
            h.addWidget(lab, 1)
            b = QPushButton("Скопировать")
            b.clicked.connect(lambda: (QApplication.clipboard().setText(copy_text),
                                       self.msg(f"Скопировано: {copy_text}")))
            h.addWidget(b)
            o = QPushButton("Написать")
            o.setObjectName("primary")
            o.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(open_url)))
            h.addWidget(o)
            v.addLayout(h)
        from urllib.parse import quote
        body = quote(f"\n\n—\n{APP_NAME} {APP_VERSION}, {sys.platform}")
        row("✉️", DEV_EMAIL, f"mailto:{DEV_EMAIL}?subject={quote(APP_NAME + ' ' + APP_VERSION)}&body={body}", DEV_EMAIL)
        row("✈️", f"Telegram @{DEV_TELEGRAM}", f"https://t.me/{DEV_TELEGRAM}", f"@{DEV_TELEGRAM}")
        hint = QLabel("Журнал ошибок для письма: «☰ → Справка → Журнал ошибок → Скопировать последние ошибки».")
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        v.addWidget(hint)
        close = QPushButton("Закрыть")
        close.clicked.connect(dlg.accept)
        v.addWidget(close, 0, Qt.AlignRight)
        dlg.exec()

    def make_desktop_shortcut(self):
        """Ярлык LegalHelper на рабочем столе (если пропал)."""
        if not C.IS_WIN or not getattr(sys, "frozen", False):
            QMessageBox.information(self, APP_NAME, "Ярлык создаётся только в установленной программе для Windows.")
            return
        exe = sys.executable
        ps = ("$ws=New-Object -ComObject WScript.Shell; "
              "$s=$ws.CreateShortcut((Join-Path ([Environment]::GetFolderPath('Desktop')) 'LegalHelper.lnk')); "
              f"$s.TargetPath='{exe}'; $s.WorkingDirectory='{os.path.dirname(exe)}'; $s.IconLocation='{exe},0'; $s.Save()")
        try:
            subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True, creationflags=0x08000000,
                           timeout=30)
            subprocess.run(["ie4uinit.exe", "-show"], creationflags=0x08000000, timeout=30)
        except Exception as e:
            return self.error("Не удалось создать ярлык", e)
        QMessageBox.information(self, APP_NAME, "Ярлык «LegalHelper» создан на рабочем столе.")

    def rollback_program(self):
        """Вернуть программу, которая стояла до последнего обновления (копию сохраняет обновление)."""
        work = os.path.join(os.environ.get("LOCALAPPDATA", ""), "PDFMaster-build")
        prev = os.path.join(work, "previous")
        exe = next((n for n in ("LegalHelper.exe", "PDFMaster.exe") if os.path.exists(os.path.join(prev, n))), None)
        if not getattr(sys, "frozen", False) or not C.IS_WIN or not exe:
            QMessageBox.information(self, APP_NAME, "Предыдущая версия не сохранена — она появится после следующего "
                                                    "обновления программы.")
            return
        try:
            with open(os.path.join(data_dir(), "previous_version.txt"), encoding="utf-8") as f:
                pv = f.read().strip()
        except OSError:
            pv = "предыдущую"
        if QMessageBox.question(self, APP_NAME, f"Вернуть версию {pv} вместо {APP_VERSION}?\n\nДела и настройки "
                                "не меняются. Программа закроется и через несколько секунд откроется предыдущая "
                                "версия. Уведомление о новой версии можно будет пропустить кнопкой «Позже»."
                                ) != QMessageBox.Yes or not self.save_all_ws():
            return
        self._shutdown_data()
        target = os.path.dirname(sys.executable)
        cmd = os.path.join(work, "rollback.cmd")
        with open(cmd, "w", encoding="utf-8") as f:
            f.write("@echo off\r\nchcp 65001 >nul\r\ntitle LegalHelper - возврат предыдущей версии\r\n"
                    "echo Возвращаю предыдущую версию программы...\r\n"
                    "timeout /t 3 /nobreak >nul\r\n"
                    "taskkill /IM LegalHelper.exe /F >nul 2>&1\r\ntaskkill /IM PDFMaster.exe /F >nul 2>&1\r\n"
                    f'robocopy "{prev}" "{target}" /MIR /XF unins*.* /R:3 /W:2 /NFL /NDL /NJH /NJS /NP >nul\r\n'
                    "if errorlevel 8 powershell -NoProfile -Command \"Start-Process -FilePath robocopy -ArgumentList "
                    f"('\\\"{prev}\\\" \\\"{target}\\\" /MIR /XF unins*.* /R:3 /W:2') -Verb RunAs -Wait -WindowStyle Hidden\"\r\n"
                    f'start "" "{os.path.join(target, exe)}"\r\n')
        subprocess.Popen(["cmd", "/c", "start", "Возврат версии", "cmd", "/c", cmd], cwd=work,
                         creationflags=0x00000008)
        self.modified = False
        QApplication.quit()

    # --- файлы можно бросить в любое место окна
    @staticmethod
    def _drop_paths(md):
        return [u.toLocalFile() for u in md.urls() if u.isLocalFile() and os.path.isfile(u.toLocalFile())] \
            if md.hasUrls() else []

    def _drop_hint(self):
        if self.stack.currentWidget() is self.cases_page and self.mode_cid:
            c = U.db().case(self.mode_cid) or {}
            return f"Отпустите — файлы добавятся в дело «{c.get('title', '')}» и в его PDF"
        return "Отпустите — файлы откроются в «Без дела — просто PDF»"

    def show_drop_overlay(self, on):
        ov = getattr(self, "_drop_ov", None)
        if ov is None:
            ov = QLabel(self)
            ov.setObjectName("dropoverlay")
            ov.setAlignment(Qt.AlignCenter)
            ov.setWordWrap(True)
            ov.setAttribute(Qt.WA_TransparentForMouseEvents)    # не мешает бросить файл на то, что под ней
            self._drop_ov = ov
        if not on:
            ov.hide()
            return
        ov.setStyleSheet(f"QLabel#dropoverlay {{ background: rgba(0,122,255,0.10); border: 3px dashed {T['accent']};"
                         f" border-radius: 18px; color: {T['accent']}; font-size: 17pt; font-weight: 700; }}")
        ov.setText("⬇\n" + self._drop_hint())
        ov.setGeometry(self.centralWidget().geometry().adjusted(8, 8, -8, -8))
        ov.show()
        ov.raise_()

    def drop_files(self, paths):
        """Файлы брошены на окно (не на страницы): в деле — в дело, иначе — в «Без дела»."""
        if not paths:
            return
        if self.stack.currentWidget() is self.cases_page and self.mode_cid:
            self.open_case_tab("docs")
            self.show_main_ws(self.mode_cid)
            self.open_paths(paths)
        else:
            self.enter_loose()
            self.loose_tabs.setCurrentIndex(0)
            self.open_paths(paths, replace=True)

    def dragEnterEvent(self, e):
        if self._drop_paths(e.mimeData()):
            e.acceptProposedAction()
            self.show_drop_overlay(True)

    def dragMoveEvent(self, e):
        if self._drop_paths(e.mimeData()):
            e.acceptProposedAction()

    def dragLeaveEvent(self, e):
        self._drop_left()

    def _drop_left(self):
        # переход между частями окна тоже даёт «уход» — прячем, только если курсор правда вышел из окна
        QTimer.singleShot(80, lambda: self.frameGeometry().contains(QCursor.pos()) or self.show_drop_overlay(False))

    def dropEvent(self, e):
        self.show_drop_overlay(False)
        paths = self._drop_paths(e.mimeData())
        if paths:
            e.acceptProposedAction()
            QTimer.singleShot(0, lambda: self.drop_files(paths))

    def eventFilter(self, obj, ev):
        """Подсказка «Отпустите — …» и над страницами (они сами принимают файлы и событие до окна не доходит).
        Фильтр стоит только на области страниц, а не на всём приложении: так он не мешает встроенному браузеру."""
        t = ev.type()
        if t == QEvent.DragEnter and self._drop_paths(ev.mimeData()) and ev.source() is None:
            self.show_drop_overlay(True)
        elif t == QEvent.DragLeave:
            self._drop_left()
        elif t == QEvent.Drop:
            QTimer.singleShot(0, lambda: self.show_drop_overlay(False))
        return super().eventFilter(obj, ev)

    # ------------------------------------------------------------- page ops
    def on_reorder(self):
        order = [self.pages.item(i).data(Qt.UserRole) for i in range(self.pages.count())]
        heads, hidden = getattr(self, "_heads", {}), getattr(self, "_hidden", set())
        if heads:                                   # свёрнутый файл переезжает целиком
            full = []
            for k in order:
                if k in hidden:
                    continue
                full.extend(range(k, k + heads[k][1]) if k in heads else [k])
            order = full
        if order == list(range(len(order))) or len(order) != self.doc.page_count:
            return
        sel = self.selected()
        self.push_undo()
        self.doc.select(order)
        self.thumbs = [self.thumbs[i] for i in order]
        thumbs = self.thumbs
        self.refresh_all(sel)
        self.thumbs = thumbs  # миниатюры не перерисовываем — только номера
        for i in range(self.doc.page_count):
            self.pages.item(i).setIcon(self.compose_icon(i))
        self.thumb_timer.start()

    def rotate_selected(self, angle, pages=None):
        if not self.need_doc():
            return
        pages = pages if pages is not None else self.selected_or_all()
        self.push_undo()
        for i in pages:
            pg = self.doc[i]
            pg.set_rotation((pg.rotation + angle) % 360)
        self.after_change(pages)
        self.msg(f"Повёрнуто страниц: {len(pages)}")

    def delete_pages(self, pages):
        if not pages:
            return
        if len(pages) >= self.doc.page_count:
            QMessageBox.warning(self, APP_NAME, "Нельзя удалить все страницы документа.")
            return
        self.push_undo()
        gone = set(pages)
        keep = [t for i, t in enumerate(self.thumbs) if i not in gone] if len(self.thumbs) == self.doc.page_count else None
        self.doc.delete_pages(pages)
        self.after_change(keep_selection=[min(pages[0], self.doc.page_count - 1)], thumbs=keep)
        self.msg(f"Удалено страниц: {len(pages)}")

    def delete_selected(self):
        if self.need_doc():
            sel = self.selected()
            if not sel:
                self.msg("Выделите страницы для удаления")
                return
            self.delete_pages(sel)

    def duplicate_selected(self):
        sel = self.selected()
        if not sel:
            self.msg("Выделите страницы для дублирования")
            return
        self.push_undo()
        for i in reversed(sel):
            self.doc.fullcopy_page(i, i + 1 if i + 1 < self.doc.page_count else -1)
        self.after_change()

    def insert_blank(self):
        if not self.need_doc():
            return
        sel = self.selected()
        after = sel[-1] if sel else self.doc.page_count - 1
        r = self.doc[after].rect
        self.push_undo()
        self.doc.new_page(pno=after + 1, width=r.width, height=r.height)
        self.after_change(keep_selection=[after + 1])

    def move_pages(self, where):
        sel = self.selected()
        if not sel:
            return
        rest = [i for i in range(self.doc.page_count) if i not in sel]
        order = sel + rest if where == "start" else rest + sel
        self.push_undo()
        self.doc.select(order)
        n = len(sel)
        self.after_change(keep_selection=list(range(n)) if where == "start"
                          else list(range(self.doc.page_count - n, self.doc.page_count)))

    def reverse_pages(self):
        if self.need_doc():
            self.push_undo()
            self.doc.select(list(reversed(range(self.doc.page_count))))
            self.after_change()

    def extract_selected(self, pages=None):
        if not self.need_doc():
            return
        pages = pages if pages is not None else self.selected()
        if not pages:
            self.msg("Выделите страницы, которые нужно извлечь")
            return
        p = self.ask_save_path("Сохранить выбранные страницы", ".pdf", PDF_FILTER, "_выборка")
        if not p:
            return
        try:
            new = C.subset_doc(self.doc, pages)
            new.save(p, garbage=3, deflate=True)
        except Exception as e:
            self.error("Не удалось сохранить", e)
            return
        self.done(f"Сохранено страниц: {len(pages)}\n{p}", p)

    def open_editor(self, index=None, mode="text", ask_word=True):
        if not self.need_doc():
            return
        if index is None:
            sel = self.selected()
            index = sel[0] if sel else 0
        src = _pdf_key(self.doc, index, "LHSrc") if 0 <= index < self.doc.page_count else None
        if ask_word and mode == "text" and WE.can_edit(src) and not getattr(self, "tutor", None):
            box = QMessageBox(self)                     # страница из Word — удобнее править сам документ
            box.setWindowTitle("Правка")
            box.setText(f"Эта страница — из документа Word «{Path(src).name}».")
            box.setInformativeText("Удобнее править сам документ: текст, абзацы, таблицы — а страницы в PDF дела "
                                   "обновятся сами. Править страницу как картинку PDF — для подписи, печати, пометок.")
            b_word = box.addButton("✏️ Править документ Word", QMessageBox.AcceptRole)
            b_pdf = box.addButton("Править страницу PDF", QMessageBox.ActionRole)
            box.addButton("Отмена", QMessageBox.RejectRole)
            box.setDefaultButton(b_word)
            box.exec()
            if box.clickedButton() is b_word:
                return self.edit_word(src)
            if box.clickedButton() is not b_pdf:
                return
        ed = PageEditor(self, index, mode)
        self._editor = ed
        try:
            ed.exec()
        finally:
            self._editor = None
        if ed.changed:
            self.after_change(keep_selection=[ed.index])

    def _page_double(self, it):
        i = self.pages.row(it)
        if i in getattr(self, "_heads", {}):
            self.toggle_group(i, False)
        else:
            self.open_editor(i)

    def context_menu(self, pos):
        if not self.doc.page_count:
            return
        it = self.pages.itemAt(pos)
        if it and not it.isSelected():
            self.pages.clearSelection()
            it.setSelected(True)
        m = QMenu(self)
        row = self.pages.row(it) if it else -1
        run = self._run_of(row) if row >= 0 else None
        if run and run[0] and run[3] > run[2]:
            if run[0] in self._collapsed():
                m.addAction(f"▸ Развернуть «{run[1]}»", lambda: self.toggle_group(row, False))
            else:
                m.addAction(f"▾ Свернуть «{run[1]}» ({run[3] - run[2] + 1} стр.)", lambda: self.toggle_group(row, True))
            m.addSeparator()
        src = _pdf_key(self.doc, row, "LHSrc") if row >= 0 else None
        if WE.can_edit(src):
            m.addAction(f"✏️ Править документ Word «{Path(src).name}»", lambda s=src: self.edit_word(s))
        m.addAction("✎ Редактировать страницу", lambda: self.open_editor(ask_word=False))
        m.addAction("Подписать", lambda: self.open_editor(mode="sign"))
        m.addSeparator()
        m.addAction("↺ Повернуть влево", lambda: self.rotate_selected(-90))
        m.addAction("↻ Повернуть вправо", lambda: self.rotate_selected(90))
        m.addAction("Повернуть на 180°", lambda: self.rotate_selected(180))
        m.addSeparator()
        m.addAction("Переместить в начало", lambda: self.move_pages("start"))
        m.addAction("Переместить в конец", lambda: self.move_pages("end"))
        m.addAction("Дублировать", self.duplicate_selected)
        m.addAction("Вставить пустую страницу после", self.insert_blank)
        m.addAction("Пустая страница другого формата…", self.tool_blank)
        m.addAction("Изменить размер страниц (A4, A5…)…", self.tool_pagesize)
        m.addAction("Вставить файл после…", self.insert_file_after)
        m.addSeparator()
        m.addAction("Сохранить выделенные как PDF…", lambda: self.save_open_as_pdf("Сохранить выделенные как PDF"))
        m.addAction("Извлечь в новый PDF…", self.extract_selected)
        m.addAction("Сохранить как картинки…", lambda: self.tool_pdf2jpg(self.selected_text()))
        m.addSeparator()
        m.addAction("Удалить", self.delete_selected)
        m.exec(self.pages.viewport().mapToGlobal(pos))

    def insert_file_after(self):
        sel = self.selected()
        paths, _ = QFileDialog.getOpenFileNames(self, "Вставить файлы", self.default_dir(), OPEN_FILTER)
        if paths:
            self.open_paths(paths, insert_at=(sel[-1] + 1) if sel else None)

    # ------------------------------------------------------------- tools
    def _chevron(self, item):
        if item.data(0, Qt.UserRole + 1) != "header":
            return
        name = item.text(0).replace("  ›", "").strip()
        item.setText(0, name + ("" if item.isExpanded() else "  ›"))

    # ------------------------------------------------------------- разделы и юр. функции
    # ------------------------------------------------------------- раскладка «всё вокруг дела»
    def _slot(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        return w

    def _mount(self, widget, slot):
        if widget.parentWidget() is not slot:
            slot.layout().addWidget(widget)
            widget.show()

    def _mount_parts(self):
        """Редактор PDF и калькуляторы — там, где сейчас пользователь (в деле или «Без дела»)."""
        QTimer.singleShot(0, lambda: self.status_lbl.setVisible(self.docarea.isVisible()))
        for a in (self.a_open, self.a_add):          # в деле документы добавляются одной кнопкой слева
            a.setVisible(not self.mode_cid)
        if self.mode_cid:
            self._mount(self.docarea, self.case_doc_slot)
            self._mount(self.calc_page, self.case_calc_slot)
        else:
            self._mount(self.docarea, self.loose_doc_slot)
            self._mount(self.calc_page, self.loose_calc_slot)

    THUMB_SIZES = (("Мини-значки", 64), ("Маленькие", 100), ("Средние", 150), ("Крупные", 210))

    def _add_view_button(self):
        b = QToolButton()
        self.view_btn = b
        b.setText("Вид ▾")
        b.setObjectName("toolsbtn")
        b.setPopupMode(QToolButton.InstantPopup)
        b.setToolTip("Размер миниатюр, крупный просмотр страницы, свернуть/развернуть файлы")
        m = QMenu(b)
        grp = QActionGroup(self)
        for label, w in self.THUMB_SIZES:
            a = m.addAction(label)
            a.setCheckable(True)
            a.setChecked(abs(self.thumb_w - w) < 5)
            grp.addAction(a)
            a.triggered.connect(lambda _=False, w=w: self.set_thumb_size_saved(w))
        m.addSeparator()
        self.a_preview = m.addAction("Просмотр страницы крупно")
        self.a_preview.setCheckable(True)
        self.a_preview.setChecked(str(settings().value("preview_on", "0")) == "1")
        self.a_preview.setShortcut("F3")
        self.a_preview.toggled.connect(self.set_preview)
        self.addAction(self.a_preview)
        m.addSeparator()
        m.addAction("Свернуть все файлы", lambda: self.collapse_all(True))
        m.addAction("Развернуть все файлы", lambda: self.collapse_all(False))
        b.setMenu(m)
        pv = QToolButton()
        pv.setDefaultAction(self.a_preview)
        pv.setObjectName("toolsbtn")
        pv.setToolTip("Показать выбранную страницу крупно рядом с миниатюрами (F3)")
        self.preview_btn = pv
        pv.setText("🔍")                               # во втором ряду тесно — только значок, пояснение в подсказке
        pv.setToolTip("Крупно: показать выбранную страницу крупно справа, чтобы прочитать (F3)")
        self.toolbar2.addWidget(pv)
        self.toolbar.addWidget(b)                      # «Вид» — в первый ряд: во втором на узком экране тесно

    def set_thumb_size_saved(self, w):
        settings().setValue("thumb_w", w)
        self.slider.blockSignals(True)
        self.slider.setValue(w)
        self.slider.blockSignals(False)
        self.set_thumb_size(w)

    def set_preview(self, on):
        settings().setValue("preview_on", "1" if on else "0")
        if self.a_preview.isChecked() != on:
            self.a_preview.setChecked(on)
        self._sync_preview()

    def _sync_preview(self):
        """Окно просмотра видно, если включено и есть открытый документ."""
        if not hasattr(self, "a_preview"):
            return
        on = self.a_preview.isChecked() and self.doc.page_count > 0
        if self.preview.isHidden() == on:
            self.preview.setVisible(on)
        self._preview_current()

    def _preview_current(self):
        if not self.preview.isVisible():
            return
        sel = self.selected()
        cur = self.pages.currentRow()
        self.preview.show_page(cur if cur in sel else (sel[0] if sel else (0 if self.doc.page_count else None)))

    # --- файлы в рабочей области: страницы помнят, из какого файла пришли (пометка в самой странице PDF)
    def _tag_pages(self, start, n, name, src=None):
        tag_pages(self.doc, start, n, name, src)

    def _page_group(self, i):
        x = self.doc[i].xref
        t, g = self.doc.xref_get_key(x, "LHGroup")
        if t != "string":
            return None, None
        return g, self.doc.xref_get_key(x, "LHName")[1]

    def _collapsed(self):
        return self.ws[self.cur_ws].setdefault("collapsed", set())

    def _compute_groups(self):
        """Непрерывные куски страниц из одного файла: [(gid, имя, первая, последняя)]."""
        runs, n = [], self.doc.page_count
        self._pg = [self._page_group(i) for i in range(n)]
        i = 0
        while i < n:
            g, name = self._pg[i]
            j = i
            while g and j + 1 < n and self._pg[j + 1][0] == g:
                j += 1
            runs.append((g, name, i, j))
            i = j + 1
        self._runs = runs
        coll = self._collapsed()
        self._heads = {a: (name, b - a + 1) for g, name, a, b in runs if g and g in coll and b > a}
        self._hidden = {k for g, name, a, b in runs if g and g in coll and b > a for k in range(a + 1, b + 1)}

    def _run_of(self, i):
        return next((r for r in getattr(self, "_runs", []) if r[2] <= i <= r[3]), None)

    def toggle_group(self, i, collapse=None):
        r = self._run_of(i)
        if not r or not r[0] or r[3] == r[2]:
            return
        coll = self._collapsed()
        on = (r[0] not in coll) if collapse is None else collapse
        (coll.add if on else coll.discard)(r[0])
        self.refresh_all([r[2]])

    def collapse_all(self, on):
        coll = self._collapsed()
        self._compute_groups()
        for g, _n, a, b in self._runs:
            if g and b > a:
                (coll.add if on else coll.discard)(g)
        self.refresh_all()

    def _add_tools_button(self):
        b = QToolButton()
        b.setText("Инструменты ▾")
        b.setObjectName("toolsbtn")
        b.setPopupMode(QToolButton.InstantPopup)
        b.setToolTip("Все инструменты PDF: страницы, правка, сжатие, распознавание, конвертация, защита")
        m = QMenu(b)
        for cat, items in TOOLS:
            if cat in ("Для суда и почты", "Материалы дела", "Калькуляторы"):
                continue
            sub = m.addMenu(cat)
            for key, label, tip in items:
                a = sub.addAction(label, lambda k=key: self.run_tool(k))
                a.setToolTip(tip)
        b.setMenu(m)
        self.toolbar.insertWidget(self._tb_spacer, b)

    def run_tool(self, key):
        fn = getattr(self, "tool_" + key, None)
        if fn:
            fn()

    def show_kit(self):
        """Вкладка «Документы» → «Комплект для подачи»."""
        self.open_case_tab("docs")
        self.docs_seg.setCurrentIndex(1)

    def goto_page(self, page):
        """Выделить страницу и прокрутить к ней в рабочей области."""
        if 0 <= page < self.doc.page_count:
            if page in getattr(self, "_hidden", ()):          # страница в свёрнутом файле — развернуть его
                self.toggle_group(page, collapse=False)
            self.pages.clearSelection()
            it = self.pages.item(page)
            if it:
                it.setSelected(True)
                self.pages.setCurrentItem(it)
                self.pages.scrollToItem(it, QAbstractItemView.PositionAtTop)

    def run_doc_tool(self, key):
        if not self.doc.page_count:
            self.open_case_tab("docs")
            QMessageBox.information(self, APP_NAME, "Сначала откройте документ: щёлкните его в списке слева "
                                                    "или добавьте файл кнопкой «+ Добавить».")
            return
        self.open_case_tab("docs")
        self.run_tool(key)

    def _restructure_case_tabs(self):
        cp = self.cases_page
        tabs = cp.tabs
        by_name = {tabs.tabText(i): tabs.widget(i) for i in range(tabs.count())}
        cp._restoring = True                       # перестройка вкладок — не «переход» пользователя
        while tabs.count():
            tabs.removeTab(0)
        self.overview = U.OverviewTab(self)
        docs = QSplitter()
        docs.setChildrenCollapsible(False)
        # слева: «Документы» дела или «Комплект для подачи»; справа — рабочая область
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 8, 14, 0)            # отступ от рабочей области справа
        lv.setSpacing(6)
        seg = QTabBar()
        seg.setObjectName("docseg")
        seg.setDrawBase(False)
        seg.setExpanding(True)
        seg.addTab("📄  Документы")
        seg.addTab("📦  Комплект для подачи")
        lv.addWidget(seg)
        self.docs_mode = QStackedWidget()
        self.docs_mode.addWidget(cp.docs_widget)
        self.docs_mode.addWidget(cp.sub_tab)
        self.docs_mode.setCurrentIndex(0)          # видна только одна панель — переключатель сам показывает нужную
        seg.currentChanged.connect(self.docs_mode.setCurrentIndex)
        seg.currentChanged.connect(lambda *_: anim.slide_in(self.docs_mode.currentWidget(), dx=14, dy=0, ms=220))
        self.docs_seg = seg
        lv.addWidget(self.docs_mode, 1)
        dl = left
        dl.setMinimumWidth(360)
        docs.addWidget(dl)
        self.case_doc_slot = self._slot()
        docs.addWidget(self.case_doc_slot)
        docs.setStretchFactor(1, 1)
        docs.setSizes([370, 910])
        cp.l_docs.setColumnHidden(3, True)
        cp.l_docs.setColumnWidth(2, 128)
        prepare = U.PrepareTab(self, None)
        self.case_calc_slot = self._slot()
        # «Деньги»: учёт времени и оплат + калькуляторы (пошлина, проценты, сроки) — переключателем сверху
        money = QWidget()
        mv = QVBoxLayout(money)
        mv.setContentsMargins(0, 8, 0, 0)
        mv.setSpacing(6)
        mseg = QTabBar()
        mseg.setObjectName("docseg")
        mseg.setDrawBase(False)
        mseg.addTab("⏱  Время и оплата")
        mseg.addTab("🧮  Калькуляторы")
        mseg.setUsesScrollButtons(False)
        mseg.setTabToolTip(1, "Госпошлина, проценты ст. 395 ГК и неустойка, процессуальные сроки")
        mrow = QHBoxLayout()
        mrow.addWidget(mseg)
        mrow.addStretch(1)
        mv.addLayout(mrow)
        self.money_stack = QStackedWidget()
        self.money_stack.addWidget(by_name.get("Время и оплата"))
        self.money_stack.addWidget(self.case_calc_slot)
        mseg.currentChanged.connect(self.money_stack.setCurrentIndex)
        mseg.currentChanged.connect(lambda *_: anim.slide_in(self.money_stack.currentWidget(), dx=14, dy=0, ms=220))
        self.money_seg = mseg
        mv.addWidget(self.money_stack, 1)
        # понятные названия; редкое — в «Ещё ▾»
        order = [("overview", "Обзор", self.overview), ("docs", "Документы", docs),
                 ("prepare", "Создать документ", prepare), ("events", "Сроки", cp.events_tab),
                 ("money", "Деньги", money), ("info", "Сведения", by_name.get("Сведения")),
                 ("board", "Карта дела", cp.board_tab), ("laws", "Нормы права", cp.laws_tab),
                 ("quotes", "Выписки", by_name.get("Выписки"))]
        self.case_tab_keys = {}
        for key, title, w in order:
            self.case_tab_keys[key] = tabs.addTab(w, title)
        self.case_tab_keys["calc"] = self.case_tab_keys["money"]
        tips = {"overview": "Главное по делу: ближайшие сроки, заметки к заседанию, последние документы",
                "docs": "Документы дела и «PDF дела» — все документы одним файлом",
                "prepare": "Документ по шаблону, пакет в суд, опись — и все инструменты для PDF",
                "events": "Заседания, процессуальные сроки и задачи — с напоминаниями",
                "money": "Учёт времени и оплат, калькуляторы госпошлины, процентов и сроков",
                "info": "Суд, номер дела, стороны, инстанции, папка дела"}
        for key, tip in tips.items():
            tabs.setTabToolTip(self.case_tab_keys[key], tip)
        self.hidden_tabs = [self.case_tab_keys[k] for k in ("board", "laws", "quotes")]
        for i in self.hidden_tabs:
            tabs.setTabVisible(i, False)
        more = QToolButton()
        more.setObjectName("moretabs")
        more.setText("Ещё ▾")
        more.setPopupMode(QToolButton.InstantPopup)
        mm = QMenu(more)
        for key, title in (("board", "🗺️ Карта дела"), ("laws", "📚 Нормы права"), ("quotes", "✂️ Выписки")):
            mm.addAction(title, lambda k=key: self.open_case_tab(k))
        mm.addSeparator()
        mm.addAction("📁 Открыть папку дела", lambda: U.open_case_folder(self.mode_cid))
        mm.addAction("📦 Собрать все файлы в папку дела", lambda: U.collect_case_files(self, self.mode_cid))
        mm.addSeparator()
        mm.addAction("🗑 Удалить дело (в корзину)", lambda: cp.delete_case(self.mode_cid))
        more.setMenu(mm)
        tabs.setCornerWidget(more, Qt.TopRightCorner)
        cp._restoring = False
        tabs.currentChanged.connect(self._on_case_tab)
        tabs.currentChanged.connect(lambda *_: anim.slide_in(tabs.currentWidget(), dx=14, dy=0, ms=220))

    def _on_case_tab(self, i):
        tabs = self.cases_page.tabs
        for j in self.hidden_tabs:
            tabs.setTabVisible(j, j == i)
        if i == self.case_tab_keys["overview"] and self.mode_cid:
            self.overview.set_case(self.mode_cid)
        self._mount_parts()

    def open_case_tab(self, key):
        if not self.mode_cid:
            cid = self.cases_page.cid or self.last_case or self._first_case()
            if not cid:
                if key in ("docs", "calc"):
                    self.enter_loose()
                    self.loose_tabs.setCurrentIndex(0 if key == "docs" else 1)
                else:
                    QMessageBox.information(self, APP_NAME, "Сначала создайте дело: кнопка «+ Новое дело» слева.")
                return
            self.enter_case(cid)
        self.stack.setCurrentWidget(self.cases_page)
        self.cases_page.tabs.setCurrentIndex(self.case_tab_keys[key])
        if key in ("calc", "money"):
            self.money_seg.setCurrentIndex(1 if key == "calc" else 0)

    def _first_case(self):
        try:
            cs = U.db().cases()
            return cs[0]["id"] if cs else None
        except Exception:
            return None

    def _initial_mode(self):
        cur = self.ws[self.cur_ws]
        if cur["doc"].page_count:                # открыли программу файлом — сразу к нему
            self.show_section(0)
        else:
            self.show_home()

    def show_home(self):
        """Главная — сводка по всей работе."""
        if self.mode_cid:
            U.sync_case_file(self.mode_cid)
        self.mode_cid = None
        self.b_loose.setChecked(False)
        self.b_home.setChecked(True)
        self.cases_page.list.blockSignals(True)
        self.cases_page.list.setCurrentItem(None)
        self.cases_page.list.clearSelection()
        self.cases_page.list.blockSignals(False)
        self.stack.setCurrentWidget(self.home_page)
        self.home_page.refresh()                 # уже на экране — числа в карточках «отсчитываются»

    def _on_case_selected(self, it, _prev=None):
        if self._entering:
            return
        cid = it.data(Qt.UserRole) if it else None
        if cid:
            self.enter_case(cid)

    def enter_case(self, cid):
        if self._entering:
            return
        if self.mode_cid and self.mode_cid != cid:
            U.sync_case_file(self.mode_cid)
        self._entering = True
        try:
            self.mode_cid = cid
            self.last_case = cid
            self.b_loose.setChecked(False)
            self.b_home.setChecked(False)
            if self.cases_page.cid != cid:
                self.cases_page.select_case(cid)
            self.stack.setCurrentWidget(self.cases_page)
            changed = self.overview.cid != cid
            self._ensure_ws(cid)
            self._mount_parts()
            self.overview.set_case(cid)
            if changed:                                    # другое дело — мягко проявить содержимое
                anim.slide_in(self.cases_page.tabs.currentWidget(), dx=14, dy=0, ms=220)
        finally:
            self._entering = False

    def enter_loose(self):
        if self._entering:
            return
        self._entering = True
        try:
            self.mode_cid = None
            self.b_loose.setChecked(True)
            self.b_home.setChecked(False)
            self.cases_page.list.setCurrentItem(None)
            self.cases_page.list.clearSelection()
            self.stack.setCurrentWidget(self.loose_page)
            self._ensure_ws(None)
            self._mount_parts()
            self.refresh_loose_list()
        finally:
            self._entering = False

    def refresh_loose_list(self):
        if not hasattr(self, "loose_list"):
            return
        self.loose_list.clear()
        self._store_ws()
        for i, w in enumerate(self.ws):
            if w.get("case_id") or not (w["doc"].page_count or w["modified"]):
                continue
            name = Path(w["path"]).name if w["path"] else "Новый документ"
            it = QListWidgetItem(("📄  " + name) + ("  •" if w["modified"] else ""))
            it.setData(Qt.UserRole, i)
            it.setToolTip(w["path"] or "ещё не сохранён")
            if i == self.cur_ws:
                f = it.font()
                f.setBold(True)
                it.setFont(f)
            self.loose_list.addItem(it)
        if not self.loose_list.count():
            it = QListWidgetItem("Пока ничего не открыто")
            it.setFlags(Qt.NoItemFlags)
            self.loose_list.addItem(it)

    def _ensure_ws(self, cid):
        """Показать документ этого дела (в деле — его «PDF дела») или лист «Без дела»."""
        if self.ws[self.cur_ws].get("case_id") == cid:
            return
        if cid:
            self.show_main_ws(cid)
            return
        cand = [i for i, w in enumerate(self.ws) if w.get("case_id") == cid]
        if cand:
            best = next((i for i in cand if self.ws[i]["doc"].page_count), cand[0])
            self._store_ws()
            self._load_ws(best)
            return
        cur = self.ws[self.cur_ws]
        if not cur["doc"].page_count and not cur["modified"]:
            cur["case_id"] = cid
            self.update_title()
        else:
            self.new_ws(case_id=cid)

    def show_section(self, i):
        """Совместимость со старыми вызовами: 0 — документ, 1 — дела, 2 — расчёты, 3 — справка."""
        if i == 0:
            cid = self.ws_case()
            if cid:
                self.enter_case(cid)
                self.cases_page.tabs.setCurrentIndex(self.case_tab_keys["docs"])
            else:
                self.enter_loose()
                self.loose_tabs.setCurrentIndex(0)
        elif i == 1:
            self.show_cases()
        elif i == 2:
            self.show_calc(0)
        else:
            if self.stack.currentWidget() is not self.help_page:
                self._before_help = self.stack.currentWidget()
            self.b_loose.setChecked(False)
            self.b_home.setChecked(False)
            self.stack.setCurrentWidget(self.help_page)

    def leave_help(self):
        """«← Назад» и Esc в справке: туда, где были до неё."""
        prev = getattr(self, "_before_help", None)
        if prev is self.loose_page:
            self.enter_loose()
        elif prev is getattr(self, "home_page", None) and prev is not None:
            self.show_home()
        elif self.mode_cid or self.last_case or self._first_case():
            self.show_cases()
        else:
            self.enter_loose()

    def show_cases(self):
        cid = self.mode_cid or self.cases_page.cid or self.last_case or self._first_case()
        if cid:
            self.enter_case(cid)
        else:
            self.stack.setCurrentWidget(self.cases_page)

    def show_calc(self, tab=0):
        if self.mode_cid:
            self.open_case_tab("calc")
        else:
            self.enter_loose()
            self.loose_tabs.setCurrentIndex(1)
        self.calc_page.tabs.setCurrentIndex(tab)

    def tool_board(self, cid=None):
        """Открыть карту дела (Excalidraw) для текущего/выбранного дела."""
        cid = cid or self.ws_case() or (self.cases_page.cid if self.cases_page else None) or self.last_case
        if not cid:
            cid = U.pick_case(self, "Карта какого дела?")
        if not cid:
            return
        self.show_cases()
        self.cases_page.select_case(cid)
        self.cases_page.tabs.setCurrentWidget(self.cases_page.board_tab)

    def tool_calc_deadline(self):
        self.show_calc(0)

    def tool_calc_duty(self):
        self.show_calc(1)

    def tool_calc_interest(self):
        self.show_calc(2)

    def set_banner(self, text, cid=None):
        """Красная полоса о срочном (сегодня, завтра, просрочено). На «Главной» не показывается —
        там то же самое есть в карточке «Горящие и просроченные»."""
        self._banner_text, self._banner_cid = text, cid
        self._sync_banner()

    def _sync_banner(self):
        text = self._banner_text if self.stack.currentWidget() is not self.home_page else ""
        was = self.banner.isVisible()
        self.banner.setText(text)
        if text and not was and self.isVisible():
            anim.slide_down(self.banner)
        else:
            self.banner.setVisible(bool(text))

    def _banner_click(self):
        if self._banner_cid and U.db().case(self._banner_cid):
            self.enter_case(self._banner_cid)
            self.open_case_tab("overview")
        else:
            self.show_home()

    def refresh_cases(self):
        if self.cases_page:
            self.cases_page.reload()
            try:
                self.cases_page.reload_upcoming()
            except Exception:
                pass
            if self.last_case:
                self.cases_page.select_case(self.last_case)

    def open_external(self, path, page=0, cid=None, separate=False):
        if not os.path.exists(path):
            return QMessageBox.warning(self, APP_NAME, f"Файл не найден:\n{path}")
        ext = os.path.splitext(path)[1].lower()
        target = cid if cid is not None else self.mode_cid
        if target and not separate and ext != ".excalidraw":
            self.enter_case(target)
            self.open_case_tab("docs")
            if self._same(path, self.case_pdf(target)):
                self.show_main_ws(target)
                self.goto_page(page)
            else:
                self.show_in_case(target, path, page)
            return
        if ext in EXTERNAL_EXT:
            self.open_in_app(path)
            return
        if target:
            self.enter_case(target)
        else:
            self.enter_loose()
        self.open_paths([path], replace=True, separate=separate)
        self.show_section(0)
        if cid and self.path:
            try:
                U.db().add_doc(cid, self.path)
            except Exception:
                pass
            if not self.ws[self.cur_ws].get("case_id"):
                self.ws[self.cur_ws]["case_id"] = cid
            self.cases_page.refresh_docs_if(cid)
            self.update_title()
        if 0 <= page < self.doc.page_count:
            self.pages.clearSelection()
            it = self.pages.item(page)
            it.setSelected(True)
            self.pages.scrollToItem(it)

    # --- файлы, открытые в своих программах (Word, Acrobat…): правки подтягиваются сами
    def edit_word(self, path):
        """Встроенный редактор Word. Старые форматы (.doc, .rtf) — в самом Word."""
        if not path or not os.path.exists(path):
            return QMessageBox.warning(self, APP_NAME, f"Файл не найден:\n{path}")
        if not WE.can_edit(path):
            QMessageBox.information(self, APP_NAME, f"«{Path(path).name}» — в формате, который встроенный редактор не "
                                    "открывает (он понимает .docx). Открываю в Word — после сохранения там изменения "
                                    "появятся здесь сами.")
            return self.open_in_app(path)
        eds = self.__dict__.setdefault("_word_eds", {})
        key = os.path.normcase(os.path.abspath(path))
        ed = eds.get(key)
        if ed is not None:
            try:
                ed.showNormal()
                ed.raise_()
                ed.activateWindow()
                return ed
            except RuntimeError:
                eds.pop(key, None)
        try:
            ed = WE.WordEditor(self, path)
        except Exception as e:
            self.error(f"Не удалось открыть «{Path(path).name}» для правки", e)
            return None
        ed.setAttribute(Qt.WA_DeleteOnClose)
        ed.destroyed.connect(lambda *_: eds.pop(key, None))
        eds[key] = ed
        ed.show()
        return ed

    def on_word_saved(self, path):
        """Документ сохранили во встроенном редакторе — обновить его страницы в PDF дела (и сохранить его)."""
        self.extwatch.refresh(path)
        self.on_external_changed(path)
        cid = self.mode_cid
        if cid:
            self.cases_page.refresh_docs_if(cid)

    def open_in_app(self, path):
        if not os.path.exists(path):
            return QMessageBox.warning(self, APP_NAME, f"Файл не найден:\n{path}")
        self.extwatch.watch(path)
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))
        self.msg(f"«{Path(path).name}» открыт в своей программе. Сохраните его там — изменения появятся "
                 "и здесь.", 8000)

    def on_external_changed(self, path):
        """Файл поправили и сохранили в другой программе — обновить его страницы во всех открытых документах."""
        self._store_ws()
        key = os.path.normcase(os.path.abspath(path))
        direct = [i for i, w in enumerate(self.ws) if w["path"] and os.path.normcase(os.path.abspath(w["path"])) == key]
        uses = [i for i, w in enumerate(self.ws) if i not in direct and w["doc"].page_count and
                any((_pdf_key(w["doc"], k, "LHSrc") or "").lower() == key.lower() for k in range(w["doc"].page_count))]
        if not direct and not uses:
            return
        new = self.load_file(path)
        if new is None or not new.page_count:
            return
        name = Path(path).name
        for i in direct:
            w = self.ws[i]
            if w["modified"]:
                self._load_ws(i)
                if QMessageBox.question(self, APP_NAME, f"Файл «{name}» изменён в другой программе.\n\nЗагрузить "
                                        "новую версию? Несохранённые правки в LegalHelper в этом документе пропадут.") \
                        != QMessageBox.Yes:
                    continue
                self._store_ws()
            d = fitz.open("pdf", new.tobytes())
            tag_pages(d, 0, d.page_count, name, path)
            w.update(doc=d, modified=False, undo=[], redo=[], sel=[])
        for i in uses:
            w = self.ws[i]
            w["undo"].append(w["doc"].tobytes())
            del w["undo"][:-25]
            spill_old(w["undo"])
            w["redo"].clear()
            if replace_source_pages(w["doc"], path, new):
                w["modified"] = True
                if w.get("main") and w.get("case_id"):     # PDF дела — сразу на диск, без «Сохранить»
                    self._save_case_ws(i)
        self._load_ws(self.cur_ws)
        self.toast(f"↻  Обновлено и сохранено: {name}")

    def _save_case_ws(self, i):
        """Записать «PDF дела» из открытого документа i (не обязательно текущего) в папку дела."""
        w = self.ws[i]
        cid = w["case_id"]
        target = self.case_pdf(cid)
        try:
            C.save_pdf(w["doc"], target)
        except Exception as e:
            log_error("Автосохранение PDF дела после правки в Word", e)
            return False
        self.extwatch.refresh(target)
        w.update(path=target, modified=False)
        U.db().update_case(cid, pdf=os.path.basename(target))
        QTimer.singleShot(300, lambda c=cid: self.phone_sync(c))
        return True

    # ------------------------------------------------------------- открытые документы
    def _blank_ws(self):
        return dict(doc=fitz.open(), path=None, modified=False, undo=[], redo=[], case_id=None, sel=[])

    def _store_ws(self):
        w = self.ws[self.cur_ws]
        w.update(doc=self.doc, path=self.path, modified=self.modified, undo=self.undo_stack,
                 redo=self.redo_stack, sel=self.selected() if self.doc.page_count else [])

    def _load_ws(self, i):
        self.cur_ws = i
        w = self.ws[i]
        self.pages.empty_text = ("Это «PDF дела» — все документы дела одним файлом.\n\n"
                                 "Перетащите сюда документы из списка слева\n"
                                 "(или двойной щелчок по документу),\n"
                                 "либо «Ещё ▾ → Собрать PDF дела из всех документов».\n\n"
                                 "«Сохранить» запишет его в папку дела.") if w.get("main") else ""
        self.doc, self.path, self.modified = w["doc"], w["path"], w["modified"]
        self.undo_stack, self.redo_stack = w["undo"], w["redo"]
        self.refresh_all(w["sel"])
        self.update_title()
        if w.get("case_id") and hasattr(self, "cases_page"):
            self.cases_page.refresh_docs_if(w["case_id"])
        self.refresh_loose_list()

    def all_ws(self):
        self._store_ws()
        return self.ws

    def ws_case(self):
        return self.ws[self.cur_ws].get("case_id") if self.ws else None

    def find_ws(self, path):
        n = os.path.normcase(os.path.abspath(path))
        for i, w in enumerate(self.ws):
            if w["path"] and os.path.normcase(os.path.abspath(w["path"])) == n:
                return i
        return None

    def new_ws(self, case_id=None):
        self._store_ws()
        self.ws.append(self._blank_ws())
        self.ws[-1]["case_id"] = case_id
        self._load_ws(len(self.ws) - 1)

    def switch_ws(self, i):
        if i is None or i == self.cur_ws or not (0 <= i < len(self.ws)):
            return
        self._store_ws()
        self._load_ws(i)
        self.show_section(0)

    def close_ws(self, i=None):
        i = self.cur_ws if i is None else i
        if i != self.cur_ws:
            self.switch_ws(i)
        if not self.maybe_save():
            return False
        cid = self.ws[i].get("case_id")
        self.ws.pop(i)
        same = [k for k, w in enumerate(self.ws) if w.get("case_id") == cid]
        if not same:
            b = self._blank_ws()
            b["case_id"] = cid
            self.ws.append(b)
            same = [len(self.ws) - 1]
        self._load_ws(same[0])
        return True

    def save_all_ws(self):
        self._store_ws()
        for i in range(len(self.ws)):
            if self.ws[i]["modified"] and self.ws[i]["doc"].page_count:
                self.switch_ws(i)
                if not self.maybe_save():
                    return False
                self._store_ws()
        return True

    def open_from_nav(self, path, ws_index, cid):
        if ws_index is not None:
            self.switch_ws(ws_index)
            return
        if not path:
            return
        self.open_external(path, 0, cid)

    def toggle_nav(self):
        self.set_sidebar(not self.side.isVisible() or self.side.maximumWidth() < 300)

    def _build_app_menu_button(self):
        """Вместо строки меню «Файл · Правка · Вид…» (вид программы из 2000-х) — одна кнопка ☰.
        Пункты те же; их горячие клавиши работают и без видимой строки меню."""
        mb = self.menuBar()
        self.app_menu = QMenu(self)
        for a in mb.actions():
            if a.menu():
                self.app_menu.addMenu(a.menu())

        def walk(menu):
            for a in menu.actions():
                if a.menu():
                    walk(a.menu())
                elif not a.shortcut().isEmpty():
                    self.addAction(a)               # иначе сочетания клавиш погаснут вместе со строкой меню
        walk(self.app_menu)
        mb.hide()
        b = QToolButton()
        b.setText("☰")
        b.setObjectName("appmenu")
        b.setCursor(Qt.PointingHandCursor)
        b.setToolTip("Меню: файл, правка, вид, инструменты, «Юристу», справка")
        b.clicked.connect(lambda: self.show_app_menu(b))
        self.app_menu_btn = b
        return b

    def show_app_menu(self, anchor):
        """Панель-меню: разделы слева, команды крупно справа, поиск, темы — цветными кружками."""
        names = {v: k for k, v in THEME_NAMES.items()}

        def swatch(text):
            key = names.get(text)
            if key == "system":
                return (THEMES["light"]["win"], THEMES["dark"]["win"], THEMES["light"]["accent"])
            th = THEMES.get(key)
            return (th["win"], th["accent"]) if th else None
        app_menu.show(self, anchor, self.app_menu, T, swatch, f"{APP_NAME} {APP_VERSION}")

    def tint_title_bar(self):
        """Windows 11: полоса заголовка окна — цвета программы (как у Obsidian), в тёмной теме — тёмная.
        Окно остаётся «родным»: прилипание к краям экрана, тень и меню кнопки «□» работают как обычно."""
        if not C.IS_WIN:
            return
        try:
            import ctypes
            from ctypes import wintypes
            hwnd = wintypes.HWND(int(self.winId()))
            dwm = ctypes.windll.dwmapi

            def setattr_(attr, value):
                v = ctypes.c_int(value)
                dwm.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(v), ctypes.sizeof(v))

            def colorref(hexcol):
                c = QColor(hexcol)
                return c.red() | (c.green() << 8) | (c.blue() << 16)
            dark = T.get("name") == "dark" or QColor(T["side"]).lightness() < 128
            setattr_(20, 1 if dark else 0)          # DWMWA_USE_IMMERSIVE_DARK_MODE
            setattr_(35, colorref(T["side"]))       # DWMWA_CAPTION_COLOR — как левая панель
            setattr_(36, colorref(T["text"]))       # DWMWA_TEXT_COLOR
            setattr_(34, colorref(T["side"]))       # DWMWA_BORDER_COLOR
        except Exception as e:
            log_error("Цвет заголовка окна", e)

    def showEvent(self, e):
        super().showEvent(e)
        QTimer.singleShot(0, self.tint_title_bar)

    def _build_rail(self):
        """Свёрнутая левая панель: узкая полоска со значками самых нужных действий."""
        rail = QWidget()
        rail.setObjectName("sidebar")
        rail.setFixedWidth(54)
        v = QVBoxLayout(rail)
        v.setContentsMargins(7, 14, 7, 10)
        v.setSpacing(6)

        def btn(text, tip, fn):
            b = QToolButton()
            b.setText(text)
            b.setObjectName("railbtn")
            b.setToolTip(tip)
            b.setCursor(Qt.PointingHandCursor)
            b.setFixedSize(40, 40)
            b.clicked.connect(fn)
            v.addWidget(b, 0, Qt.AlignHCenter)
            return b
        btn("»", "Развернуть левую панель (Ctrl+B)", lambda: self.set_sidebar(True))
        mb = btn("☰", "Меню: файл, правка, вид, инструменты, справка", lambda: self.show_app_menu(mb))
        v.addSpacing(8)
        btn("🔍", "Найти что угодно (Ctrl+K)", lambda: palette.show(self))
        btn("🏠", "Главная", self.show_home)
        btn("📂", "Без дела — просто PDF", self.enter_loose)
        btn("➕", "Новое дело", lambda: self.cases_page.new_case())
        v.addStretch(1)
        btn("🗑", "Корзина", self.show_trash)
        btn("?", "Справка", lambda: self.show_section(3))
        rail.hide()
        self.rail = rail
        return rail

    def set_sidebar(self, show, animate=True):
        """Развернуть или свернуть левую панель (свёрнутая — узкая полоска со значками)."""
        settings().setValue("sidebar_collapsed", "0" if show else "1")
        self.a_nav.setChecked(show)
        side, rail = self.side, self.rail
        old = getattr(self, "_side_anim", None)
        if old is not None:
            old.stop()
        if not anim.ENABLED or not animate or not self.isVisible():
            side.setMaximumWidth(300)
            side.setMinimumWidth(300 if show else 0)
            (rail if show else side).hide()             # сначала спрятать — иначе окно на миг раздастся вширь
            (side if show else rail).show()
            return
        from PySide6.QtCore import QPropertyAnimation, QEasingCurve
        a = QPropertyAnimation(side, b"maximumWidth", self)
        a.setDuration(200)
        a.setEasingCurve(QEasingCurve.OutCubic)
        side.setMinimumWidth(0)
        if show:
            rail.hide()
            side.setMaximumWidth(0)
            side.show()
            a.setStartValue(0)
            a.setEndValue(300)
            a.finished.connect(lambda: side.setMinimumWidth(300))
        else:
            a.setStartValue(side.width())
            a.setEndValue(0)
            a.finished.connect(lambda: (side.hide(), side.setMaximumWidth(300), rail.show()))
        self._side_anim = a
        a.start()

    def fill_case_menu(self):
        m = self.case_menu
        m.clear()
        cur = self.ws_case()
        try:
            cases = U.db().cases()
        except Exception:
            cases = []
        for c in cases:
            a = m.addAction(c["title"] + (f"  ({c['number']})" if c["number"] else ""))
            a.setCheckable(True)
            a.setChecked(c["id"] == cur)
            a.triggered.connect(lambda _=False, cid=c["id"]: self.link_current_to_case(cid))
        if cases:
            m.addSeparator()
        m.addAction("Новое дело…", self.link_to_new_case)
        if cur:
            m.addAction("Открыть карточку дела", lambda: (self.show_cases(), self.cases_page.select_case(cur)))
            m.addAction("Отвязать от дела", lambda: self.unlink_from_case(cur, self.path))

    def link_current_to_case(self, cid):
        if not self.doc.page_count:
            return QMessageBox.information(self, APP_NAME, "Сначала откройте документ: вкладка дела «Документы» или «Без дела — просто PDF».")
        if not self.path or self.modified:
            QMessageBox.information(self, APP_NAME, "Чтобы привязать документ к делу, его нужно сохранить в файл.")
            if not self.save():
                return
        U.db().add_doc(cid, self.path)
        self.ws[self.cur_ws]["case_id"] = cid
        self.last_case = cid
        self.cases_page.refresh_docs_if(cid)
        self.update_title()
        self.show_section(0)
        c = U.db().case(cid)
        self.msg(f"Документ привязан к делу «{c['title'] if c else cid}»")

    def link_to_new_case(self):
        name, ok = QInputDialog.getText(self, "Новое дело", "Название дела (например, «ООО Ромашка — взыскание долга»):")
        if ok and name.strip():
            cid = U.db().add_case(title=name.strip())
            self.cases_page.reload()
            self.link_current_to_case(cid)

    def unlink_from_case(self, cid, path):
        if path:
            U.db().unlink_path(cid, path)
        for w in self.ws:
            if w.get("case_id") == cid and (w["path"] == path or not path):
                w["case_id"] = None
        self.cases_page.refresh_docs_if(cid)
        self.update_title()
        self.navigator.refresh()

    def add_files_to_case(self, cid):
        paths, _ = QFileDialog.getOpenFileNames(self, "Добавить файлы в дело", self.default_dir(), OPEN_FILTER)
        for p in paths:
            U.db().add_doc(cid, p)
        self.cases_page.refresh_docs_if(cid)
        self.navigator.refresh()

    def show_in_folder(self, path):
        if C.IS_WIN:
            subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
        else:
            QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(path)))

    def ask_password(self, name):
        pw, ok = QInputDialog.getText(self, APP_NAME, f"Файл «{name}» защищён паролем.\nВведите пароль:",
                                      QLineEdit.Password)
        return pw if ok else None

    def on_tool(self, item, _col=0):
        key = item.data(0, Qt.UserRole)
        if not key:
            if item.childCount():
                item.setExpanded(not item.isExpanded())
            return
        fn = getattr(self, "tool_" + key, None)
        if key not in ("package", "f107", "case_search", "template", "compare_ed") and not key.startswith("calc_"):
            self.show_section(0)
        if fn:
            fn()
        self.tree.clearSelection()

    def save_open_as_pdf(self, title="Сохранить как PDF"):
        """Открытый документ (всё, что собрано в рабочей области, — Word, картинки, PDF) или только
        выделенные страницы — в отдельный PDF-файл."""
        sel = self.selected()
        only = False
        if sel and len(sel) < self.doc.page_count:
            box = QMessageBox(self)
            box.setWindowTitle(title)
            box.setText(f"<b>{title}</b>")
            box.setInformativeText(f"Выделено страниц: {len(sel)} из {self.doc.page_count}. Что сохранить в PDF?")
            b_sel = box.addButton(f"Выделенные ({len(sel)} стр.)", QMessageBox.AcceptRole)
            b_all = box.addButton(f"Весь документ ({self.doc.page_count} стр.)", QMessageBox.AcceptRole)
            box.addButton("Отмена", QMessageBox.RejectRole)
            box.exec()
            if box.clickedButton() not in (b_sel, b_all):
                return
            only = box.clickedButton() is b_sel
        p = self.ask_save_path(title, ".pdf", PDF_FILTER, " (выбранные страницы)" if only else "")
        if not p:
            return
        try:
            if only:
                out = fitz.open()
                for i in sel:
                    out.insert_pdf(self.doc, from_page=i, to_page=i)
                C.save_pdf(out, p)
            elif not self.path:
                return self.save_to(p)                       # документ ещё без файла — теперь он и есть этот PDF
            else:
                C.save_pdf(self.doc, p)
        except Exception as e:
            return self.error("Не удалось сохранить PDF", e)
        cid = self.ws[self.cur_ws].get("case_id")
        if cid:
            try:
                U.db().add_doc(cid, p)
                self.cases_page.refresh_docs_if(cid)
            except Exception:
                pass
        self.toast(f"✓  PDF сохранён: {Path(p).name}")

    def _convert_open_or_pick(self, title):
        """«… в PDF», когда в рабочей области уже что-то открыто: сохранить это в PDF, а не спрашивать файлы."""
        if not self.doc.page_count:
            return False
        self.save_open_as_pdf(title)
        return True

    def tool_merge(self):
        if self.doc.page_count:
            box = QMessageBox(self)
            box.setWindowTitle("Объединить")
            box.setText("<b>Объединить в один PDF</b>")
            box.setInformativeText("Всё, что лежит в рабочей области, — уже один документ: перетаскивайте файлы "
                                   "прямо в окно страниц, меняйте порядок мышью. Что сделать сейчас?")
            b_add = box.addButton("Добавить файлы в конец…", QMessageBox.AcceptRole)
            b_save = box.addButton("Сохранить всё одним PDF…", QMessageBox.AcceptRole)
            box.addButton("Отмена", QMessageBox.RejectRole)
            box.exec()
            if box.clickedButton() is b_save:
                return self.save_open_as_pdf("Сохранить одним PDF")
            if box.clickedButton() is not b_add:
                return
        paths, _ = QFileDialog.getOpenFileNames(self, "Выберите файлы для объединения", self.default_dir(),
                                                OPEN_FILTER)
        if paths:
            self.open_paths(paths)
            self.msg("Файлы добавлены. Меняйте порядок страниц перетаскиванием и нажмите «Сохранить как».", 10000)

    def tool_organize(self):
        QMessageBox.information(
            self, "Организовать страницы",
            "• Перетаскивайте миниатюры мышью, чтобы изменить порядок.\n"
            "• Ctrl+щелчок и Shift+щелчок — выбрать несколько страниц.\n"
            "• Правая кнопка мыши — меню: повернуть, переместить, дублировать, удалить, извлечь.\n"
            "• Перетащите файл из проводника между страницами, чтобы вставить его туда.\n"
            "• Delete — удалить, Ctrl+Z — отменить, Ctrl+S — сохранить.")

    def tool_split(self):
        if not self.need_doc():
            return
        v = OptionsDialog.ask(self, "Разделить PDF", [
            ("mode", "Способ", "combo", None, ["Каждая страница — отдельный файл",
                                              "По диапазонам (1-3, 4-7, 8-)",
                                              "Каждые N страниц"]),
            ("ranges", "Диапазоны", "text", self.selected_text(), "например: 1-3, 4-10, 11-"),
            ("n", "N страниц", "int", 2, (1, 10000)),
            ("dir", "Папка", "folder", os.path.join(self.default_dir(), self.base_name() + "_части")),
        ], note=f"В документе {self.doc.page_count} стр.")
        if not v:
            return
        mode = ["each", "ranges", "every"][["Каждая", "По", "Каждые"].index(v["mode"].split()[0])]
        res = self.run("Разделение…", C.split_document, self.doc, mode,
                       v["ranges"] if mode == "ranges" else v["n"], v["dir"], self.base_name())
        if res is not FAILED:
            self.done(f"Создано файлов: {len(res)}\nПапка: {v['dir']}", res[0] if res else v["dir"], open_file=False)

    def tool_rotate(self):
        if not self.need_doc():
            return
        v = OptionsDialog.ask(self, "Повернуть страницы", [
            ("angle", "Поворот", "combo", None, ["90° по часовой", "90° против часовой", "180°"]),
            ("pages", "Страницы", "pages", self.selected_text()),
        ])
        if v:
            try:
                pages = self.pages_arg(v["pages"])
            except ValueError as e:
                return self.error("Неверные номера страниц", e)
            angle = {"90° по часовой": 90, "90° против часовой": -90, "180°": 180}[v["angle"]]
            self.rotate_selected(angle, pages)

    def tool_delete(self):
        if not self.need_doc():
            return
        v = OptionsDialog.ask(self, "Удалить страницы", [("pages", "Страницы", "text", self.selected_text(),
                                                          "например: 2, 5-7")], ok_text="Удалить")
        if v and v["pages"].strip():
            try:
                self.delete_pages(self.pages_arg(v["pages"]))
            except ValueError as e:
                self.error("Неверные номера страниц", e)

    def tool_extract(self):
        if not self.need_doc():
            return
        v = OptionsDialog.ask(self, "Извлечь страницы", [("pages", "Страницы", "text", self.selected_text(),
                                                          "например: 1-3, 8")], ok_text="Далее")
        if v and v["pages"].strip():
            try:
                self.extract_selected(self.pages_arg(v["pages"]))
            except ValueError as e:
                self.error("Неверные номера страниц", e)

    def tool_blank(self):
        if not self.need_doc():
            return
        same = "Как у выбранной страницы"
        v = OptionsDialog.ask(self, "Вставить пустую страницу", [
            ("size", "Формат", "combo", same, [same] + list(C.PAPER_SIZES) + [C.CUSTOM_SIZE]),
            ("orient", "Ориентация", "combo", None, C.ORIENTATIONS),
            ("w", "Ширина, мм", "float", 210, (10, 5000)),
            ("h", "Высота, мм", "float", 297, (10, 5000)),
            ("count", "Количество страниц", "int", 1, (1, 500)),
        ], ok_text="Вставить", depends={
            "orient": ("size", lambda t: t != same),
            "w": ("size", lambda t: t == C.CUSTOM_SIZE),
            "h": ("size", lambda t: t == C.CUSTOM_SIZE)})
        if not v:
            return
        sel = self.selected()
        after = sel[-1] if sel else self.doc.page_count - 1
        ref = self.doc[after].rect
        if v["size"] == same:
            w, h = ref.width, ref.height
        else:
            w, h = C.paper_points(v["size"], v["orient"], ref.width, ref.height, (v["w"], v["h"]))
        self.push_undo()
        for k in range(v["count"]):
            self.doc.new_page(pno=after + 1 + k, width=w, height=h)
        self.after_change(keep_selection=list(range(after + 1, after + 1 + v["count"])))

    def tool_pagesize(self):
        if not self.need_doc():
            return
        cur = C.page_size_label(self.doc[(self.selected() or [0])[0]])
        v = OptionsDialog.ask(self, "Размер страниц", [
            ("size", "Формат бумаги", "combo", "A4 (210×297 мм)", list(C.PAPER_SIZES) + [C.CUSTOM_SIZE]),
            ("w", "Ширина, мм", "float", 210, (10, 5000)),
            ("h", "Высота, мм", "float", 297, (10, 5000)),
            ("orient", "Ориентация", "combo", None, C.ORIENTATIONS),
            ("fit", "Содержимое", "combo", None, C.FIT_MODES),
            ("margin", "Поля, мм", "float", 0, (0, 100)),
            ("pages", "Какие страницы", "pages", self.selected_text()),
        ], note=f"Сейчас: {cur}.\n«Автоматически» — альбомные страницы останутся альбомными, книжные — книжными.\n"
                "Текст остаётся векторным и доступным для поиска; пометки и поля форм на изменённых "
                "страницах будут «вшиты» в страницу.",
            ok_text="Применить", depends={
                "w": ("size", lambda t: t == C.CUSTOM_SIZE),
                "h": ("size", lambda t: t == C.CUSTOM_SIZE)})
        if not v:
            return
        try:
            pages = self.pages_arg(v["pages"])
        except ValueError as e:
            return self.error("Неверные номера страниц", e)
        res = self.run("Изменение размера страниц…", C.resize_pages, self.doc, pages, v["size"], v["orient"],
                       v["fit"], v["margin"], (v["w"], v["h"]))
        if res is not FAILED:
            self.push_undo()
            self.doc = res
            self.after_change(pages)
            self.msg(f"Размер изменён: {C.page_size_label(self.doc[(pages or [0])[0]])}")

    def tool_reverse(self):
        self.reverse_pages()

    def tool_compress(self):
        if not self.need_doc():
            return
        before = len(self.doc.tobytes(garbage=1, deflate=True))
        v = OptionsDialog.ask(self, "Сжать PDF", [
            ("level", "Степень сжатия", "combo", "Рекомендуемое (150 dpi)", list(C.COMPRESS_LEVELS)),
        ], note=f"Текущий размер: {before / 1024 / 1024:.2f} МБ.\nСильнее всего сжимаются документы со сканами и фотографиями.",
            ok_text="Сжать и сохранить…")
        if not v:
            return
        p = self.ask_save_path("Сохранить сжатый PDF", ".pdf", PDF_FILTER, "_сжатый")
        if not p:
            return
        size = self.run("Сжатие…", C.compress_document, self.doc, p, v["level"])
        if size is not FAILED:
            pct = 100 - size * 100 / max(1, before)
            self.done(f"Готово!\n\nБыло: {before / 1024 / 1024:.2f} МБ\nСтало: {size / 1024 / 1024:.2f} МБ"
                      f"\nЭкономия: {max(0, pct):.0f}%", p)

    def tool_repair(self):
        p, _ = QFileDialog.getOpenFileName(self, "Повреждённый PDF", self.default_dir(), "PDF (*.pdf);;Все файлы (*)")
        if not p or not self.maybe_save():
            return
        try:
            doc, bad = C.repair_file(p)
        except Exception as e:
            return self.error("Файл восстановить не удалось", e)
        self.doc, self.path, self.modified = doc, None, True
        self.undo_stack.clear()
        self.refresh_all()
        QMessageBox.information(self, APP_NAME, f"Восстановлено страниц: {doc.page_count}"
                                + (f"\nНе удалось прочитать страниц: {bad}" if bad else "")
                                + "\n\nСохраните результат кнопкой «Сохранить как».")

    def tool_ocr(self):
        if not self.need_doc():
            return
        td = C.find_tessdata()
        langs = C.ocr_languages(td)
        if not langs:
            QMessageBox.information(
                self, APP_NAME,
                "Для распознавания нужны языковые файлы Tesseract.\n\n"
                "Положите файлы rus.traineddata и eng.traineddata в папку «tessdata» рядом с программой, "
                "или установите Tesseract-OCR (github.com/UB-Mannheim/tesseract/wiki) с русским языком.")
            return
        default = "+".join(l for l in ("rus", "eng") if l in langs) or langs[0]
        v = OptionsDialog.ask(self, "OCR — распознавание текста", [
            ("lang", "Языки", "ecombo", default, [default] + langs),
            ("pages", "Страницы", "pages", self.selected_text()),
            ("dpi", "Качество, dpi", "combo", "300", ["200", "300", "400"]),
            ("skip", "Пропускать страницы, где уже есть текст", "check", True),
        ], note="Страница станет изображением с невидимым текстовым слоем: текст можно искать, выделять и копировать.")
        if not v:
            return
        try:
            pages = self.pages_arg(v["pages"])
        except ValueError as e:
            return self.error("Неверные номера страниц", e)
        res = self.run("Распознавание текста…", C.ocr_document, self.doc, pages, v["lang"], int(v["dpi"]), td,
                       v["skip"])
        if res is not FAILED:
            self.push_undo()
            self.doc = res
            self.after_change()
            QMessageBox.information(self, APP_NAME, "Текст распознан. Не забудьте сохранить документ.")

    def tool_pdfa(self):
        if not self.need_doc():
            return
        p = self.ask_save_path("Сохранить PDF/A", ".pdf", PDF_FILTER, "_PDFA")
        if p and self.run("Конвертация в PDF/A…", lambda progress=None: C.pdf_to_pdfa(self.doc, p)) is not FAILED:
            self.done(f"Сохранено в формате PDF/A-2b:\n{p}", p)

    # --- в PDF
    def tool_img2pdf(self):
        if self._convert_open_or_pick("Картинки в PDF"):
            return
        paths, _ = QFileDialog.getOpenFileNames(self, "Выберите изображения", self.default_dir(), IMG_FILTER)
        if not paths:
            return
        v = OptionsDialog.ask(self, "Картинки в PDF", [
            ("mode", "Формат страницы", "combo", "A4 (210×297 мм)", C.PAGE_MODES),
            ("w", "Ширина, мм", "float", 210, (10, 5000)),
            ("h", "Высота, мм", "float", 297, (10, 5000)),
            ("orient", "Ориентация", "combo", None, C.ORIENTATIONS),
            ("margin", "Поля, мм", "int", 0, (0, 50)),
            ("where", "Результат", "combo", None, ["Добавить в текущий документ", "Новый документ"]),
        ], note=f"Выбрано изображений: {len(paths)}. Порядок потом можно поменять перетаскиванием.\n"
                 "«Автоматически» — альбомные фото на альбомных листах, вертикальные — на книжных.",
            ok_text="Создать", depends={
                "w": ("mode", lambda t: t == C.CUSTOM_SIZE),
                "h": ("mode", lambda t: t == C.CUSTOM_SIZE),
                "orient": ("mode", lambda t: t != C.IMAGE_SIZE)})
        if not v:
            return
        res = self.run("Создание PDF…", C.images_to_pdf, sorted(paths), v["mode"], v["margin"],
                       orientation=v["orient"], custom_mm=(v["w"], v["h"]))
        if res is FAILED:
            return
        if v["where"].startswith("Новый") or self.doc.page_count == 0:
            if not self.maybe_save():
                return
            self.doc, self.path, self.modified = res, None, True
            self.undo_stack.clear()
        else:
            self.push_undo()
            self.doc.insert_pdf(res)
        self.after_change()

    def _office(self, title, flt):
        paths, _ = QFileDialog.getOpenFileNames(self, title, self.default_dir(), flt)
        if paths:
            self.open_paths(paths, replace=self.doc.page_count == 0)

    def tool_word2pdf(self):
        if self._convert_open_or_pick("Word в PDF"):
            return
        self._office("Документы Word", "Word (*.doc *.docx *.rtf *.odt)")

    def tool_ppt2pdf(self):
        if self._convert_open_or_pick("PowerPoint в PDF"):
            return
        self._office("Презентации", "PowerPoint (*.ppt *.pptx *.pps *.ppsx *.odp)")

    def tool_xls2pdf(self):
        if self._convert_open_or_pick("Excel в PDF"):
            return
        self._office("Таблицы", "Excel (*.xls *.xlsx *.ods *.csv)")

    def tool_html2pdf(self):
        v = OptionsDialog.ask(self, "HTML в PDF", [
            ("url", "Адрес сайта", "text", "", "https://example.com"),
            ("file", "или HTML-файл", "file", "", "HTML (*.html *.htm)"),
        ], ok_text="Конвертировать")
        if not v:
            return
        src = v["file"] or v["url"].strip()
        if not src:
            return
        tmp = os.path.join(tempfile.mkdtemp(prefix="pdfm_"), "page.pdf")
        if self.run("Загрузка страницы…", lambda progress=None: C.html_to_pdf(src, tmp)) is FAILED:
            return
        d = fitz.open("pdf", Path(tmp).read_bytes())
        if self.doc.page_count == 0:
            self.doc, self.path, self.modified = d, None, True
        else:
            self.push_undo()
            self.doc.insert_pdf(d)
        self.after_change()

    # --- из PDF
    def _export(self, title, suffix, flt, func, name_suffix="", done_text="Готово"):
        if not self.need_doc():
            return
        p = self.ask_save_path(title, suffix, flt, name_suffix)
        if not p:
            return
        res = self.run(title + "…", func, self.doc, p)
        if res is not FAILED:
            self.done(f"{done_text}\n{p}" if isinstance(done_text, str) else done_text(res, p), p)

    def tool_pdf2word(self):
        self._export("PDF в Word", ".docx", "Word (*.docx)", C.pdf_to_word,
                     done_text="Документ Word создан. Сложную вёрстку проверьте вручную.")

    def tool_pdf2excel(self):
        self._export("PDF в Excel", ".xlsx", "Excel (*.xlsx)", C.pdf_to_excel,
                     done_text=lambda n, p: (f"Найдено таблиц: {n}\n{p}" if n else
                                             f"Таблицы не найдены — текст выгружен по листам и колонкам.\n{p}"))

    def tool_pdf2ppt(self):
        self._export("PDF в PowerPoint", ".pptx", "PowerPoint (*.pptx)", C.pdf_to_pptx,
                     done_text="Презентация создана (текст страниц — в заметках к слайдам).")

    def tool_pdf2md(self):
        self._export("PDF в Markdown", ".md", "Markdown (*.md)", C.pdf_to_markdown)

    def tool_pdf2txt(self):
        self._export("PDF в текст", ".txt", "Текст (*.txt)", C.pdf_to_text)

    def tool_pdf2jpg(self, pages_text=None):
        if not self.need_doc():
            return
        v = OptionsDialog.ask(self, "PDF в изображения", [
            ("mode", "Режим", "combo", None, ["Страницы в картинки", "Извлечь все изображения из PDF"]),
            ("fmt", "Формат", "combo", None, ["jpg", "png"]),
            ("dpi", "Разрешение, dpi", "combo", "150", ["72", "100", "150", "200", "300", "600"]),
            ("q", "Качество JPG", "int", 90, (10, 100)),
            ("pages", "Страницы", "pages", pages_text if pages_text is not None else self.selected_text()),
            ("dir", "Папка", "folder", os.path.join(self.default_dir(), self.base_name() + "_картинки")),
        ])
        if not v:
            return
        try:
            pages = self.pages_arg(v["pages"])
        except ValueError as e:
            return self.error("Неверные номера страниц", e)
        if v["mode"].startswith("Страницы"):
            res = self.run("Сохранение картинок…", C.pdf_to_images, self.doc, pages, v["dir"], self.base_name(),
                           int(v["dpi"]), v["fmt"], v["q"])
        else:
            res = self.run("Извлечение изображений…", C.extract_images, self.doc, pages, v["dir"], self.base_name())
        if res is not FAILED:
            self.done(f"Сохранено файлов: {len(res)}\nПапка: {v['dir']}", res[0] if res else v["dir"], open_file=False)

    # --- редактирование
    def tool_edit(self):
        self.open_editor()

    def tool_sign(self):
        self.open_editor(mode="sign")

    def tool_watermark(self):
        if not self.need_doc():
            return
        v = OptionsDialog.ask(self, "Водяной знак", [
            ("kind", "Тип", "combo", None, ["Текст", "Изображение (логотип, печать)"]),
            ("text", "Текст", "multiline", "КОПИЯ"),
            ("font", "Шрифт", "font", "Arial жирный"),
            ("size", "Размер шрифта", "int", 60, (6, 400)),
            ("color", "Цвет", "color", (0.8, 0.1, 0.1)),
            ("angle", "Угол наклона, °", "int", 45, (-180, 180)),
            ("tile", "Размножить по всей странице (мозаика)", "check", False),
            ("image", "Изображение", "file", "", IMG_FILTER),
            ("scale", "Ширина картинки, % страницы", "int", 40, (5, 100)),
            ("pos", "Положение картинки", "combo", None, ["По центру", "Вверху слева", "Вверху справа",
                                                          "Внизу слева", "Внизу справа"]),
            ("opacity", "Непрозрачность, %", "int", 30, (5, 100)),
            ("pages", "Страницы", "pages", self.selected_text()),
        ])
        if not v:
            return
        try:
            pages = self.pages_arg(v["pages"])
        except ValueError as e:
            return self.error("Неверные номера страниц", e)
        self.push_undo()
        if v["kind"] == "Текст":
            if not v["text"].strip():
                return
            res = self.run("Водяной знак…", C.add_text_watermark, self.doc, pages, v["text"], v["size"],
                           v["color"], v["opacity"] / 100, v["angle"], v["tile"], v["font"])
        else:
            if not os.path.isfile(v["image"]):
                QMessageBox.warning(self, APP_NAME, "Выберите файл изображения.")
                self.undo_stack.pop()
                return
            png = with_opacity(C.image_bytes(v["image"])[0], v["opacity"] / 100)
            res = self.run("Водяной знак…", C.add_image_stamp, self.doc, pages, png, v["scale"] / 100, v["pos"])
        if res is FAILED:
            self._restore(self.undo_stack.pop())
        self.after_change(pages)

    def tool_numbers(self):
        if not self.need_doc():
            return
        v = OptionsDialog.ask(self, "Номера страниц", [
            ("pos", "Положение", "combo", None, C.NUMBER_POSITIONS),
            ("fmt", "Формат", "ecombo", None, C.NUMBER_FORMATS),
            ("start", "Начать с номера", "int", 1, (0, 100000)),
            ("size", "Размер шрифта", "int", 11, (5, 72)),
            ("font", "Шрифт", "font", "Times New Roman"),
            ("color", "Цвет", "color", (0, 0, 0)),
            ("margin", "Отступ от края, мм", "int", 10, (0, 100)),
            ("pages", "Какие страницы", "pages", ""),
            ("skip", "Не нумеровать первую страницу (титульный лист)", "check", False),
        ], note="{n} — номер страницы, {total} — всего страниц.")
        if not v:
            return
        try:
            pages = self.pages_arg(v["pages"])
        except ValueError as e:
            return self.error("Неверные номера страниц", e)
        start = v["start"]
        if v["skip"] and pages and pages[0] == 0:
            pages = pages[1:]
            start += 1
        self.push_undo()
        res = self.run("Нумерация…", C.add_page_numbers, self.doc, pages, v["fmt"], v["pos"], v["size"],
                       v["margin"], start, v["color"], v["font"])
        if res is FAILED:
            self._restore(self.undo_stack.pop())
        self.after_change(pages)

    def tool_crop(self):
        if not self.need_doc():
            return
        v = OptionsDialog.ask(self, "Обрезка PDF", [
            ("mode", "Способ", "combo", None, ["Автоматически (убрать пустые поля)", "Задать поля вручную",
                                               "Выделить область мышью (в редакторе)"]),
            ("l", "Слева, мм", "float", 10, (0, 500)),
            ("t", "Сверху, мм", "float", 10, (0, 500)),
            ("r", "Справа, мм", "float", 10, (0, 500)),
            ("b", "Снизу, мм", "float", 10, (0, 500)),
            ("pad", "Отступ при автообрезке, мм", "float", 5, (0, 50)),
            ("pages", "Страницы", "pages", self.selected_text()),
        ])
        if not v:
            return
        if v["mode"].startswith("Выделить"):
            return self.open_editor(mode="crop")
        try:
            pages = self.pages_arg(v["pages"])
        except ValueError as e:
            return self.error("Неверные номера страниц", e)
        self.push_undo()
        if v["mode"].startswith("Авто"):
            res = self.run("Обрезка…", C.auto_crop, self.doc, pages, v["pad"])
        else:
            res = self.run("Обрезка…", C.crop_margins, self.doc, pages, v["l"] * C.MM, v["t"] * C.MM,
                           v["r"] * C.MM, v["b"] * C.MM)
        if res is FAILED:
            self._restore(self.undo_stack.pop())
        self.after_change(pages)

    def _find_tool(self, redact):
        if not self.need_doc():
            return
        fields = [("words", "Слова и фразы (каждое с новой строки)", "multiline", "")]
        if redact:
            fields += [("action", "Как скрыть", "combo", None, ["Чёрная плашка", "Белая заливка"]),
                       ("email", "Все e-mail адреса", "check", False),
                       ("phone", "Все телефоны (+7 / 8…)", "check", False),
                       ("cards", "Номера банковских карт", "check", False),
                       ("passport", "Серия и номер паспорта РФ", "check", False)]
        else:
            fields += [("action", "Пометка", "combo", None, ["Выделить маркером", "Подчеркнуть", "Зачеркнуть"]),
                       ("color", "Цвет маркера", "color", (1, 0.9, 0.1))]
        fields.append(("pages", "Страницы", "pages", ""))
        v = OptionsDialog.ask(self, "Скрыть данные" if redact else "Найти и выделить", fields,
                              note=("Найденный текст будет удалён из документа безвозвратно "
                                    "(его нельзя будет скопировать или найти)." if redact else None))
        if not v:
            return
        words = [w.strip() for w in v["words"].splitlines() if w.strip()]
        pats = [k for k in ("email", "phone", "cards", "passport") if v.get(k)]
        if not words and not pats:
            return
        try:
            pages = self.pages_arg(v["pages"])
        except ValueError as e:
            return self.error("Неверные номера страниц", e)
        action = ({"Чёрная плашка": "redact", "Белая заливка": "whiteout"} if redact else
                  {"Выделить маркером": "highlight", "Подчеркнуть": "underline", "Зачеркнуть": "strike"})[v["action"]]
        self.push_undo()
        n = self.run("Поиск…", C.find_and_mark, self.doc, pages, words, action, pats, v.get("color", (1, 1, 0)))
        if n is FAILED:
            self._restore(self.undo_stack.pop())
            return self.after_change()
        if n == 0:
            self._restore(self.undo_stack.pop())
            QMessageBox.information(self, APP_NAME, "Ничего не найдено.\n(Если это скан — сначала выполните OCR.)")
            return
        self.after_change(pages)
        QMessageBox.information(self, APP_NAME, f"Найдено и обработано фрагментов: {n}")

    def tool_redact(self):
        self._find_tool(True)

    def tool_highlight(self):
        self._find_tool(False)

    def tool_forms(self):
        if self.need_doc():
            FormsDialog(self).exec()

    def tool_meta(self):
        if not self.need_doc():
            return
        m = self.doc.metadata or {}
        v = OptionsDialog.ask(self, "Свойства документа", [
            ("title", "Название", "text", m.get("title", "")),
            ("author", "Автор", "text", m.get("author", "")),
            ("subject", "Тема", "text", m.get("subject", "")),
            ("keywords", "Ключевые слова", "text", m.get("keywords", "")),
            ("creator", "Приложение", "text", m.get("creator", "") or APP_NAME),
        ], note=f"Страниц: {self.doc.page_count}. Формат: {m.get('format', 'PDF')}.", ok_text="Сохранить")
        if v:
            self.push_undo()
            m.update(v)
            m["producer"] = f"{APP_NAME} {APP_VERSION}"
            self.doc.set_metadata(m)
            self.after_change([])

    # --- безопасность
    def tool_protect(self):
        if not self.need_doc():
            return
        v = OptionsDialog.ask(self, "Защитить паролем", [
            ("pw", "Пароль на открытие", "password", ""),
            ("pw2", "Повторите пароль", "password", ""),
            ("owner", "Пароль владельца (необяз.)", "password", ""),
            ("print", "Разрешить печать", "check", True),
            ("copy", "Разрешить копирование текста", "check", True),
            ("edit", "Разрешить изменение", "check", False),
        ], note="Шифрование AES-256. Не забудьте пароль — восстановить его невозможно.", ok_text="Далее")
        if not v:
            return
        if not v["pw"] or v["pw"] != v["pw2"]:
            QMessageBox.warning(self, APP_NAME, "Пароли не совпадают или пусты.")
            return
        p = self.ask_save_path("Сохранить защищённый PDF", ".pdf", PDF_FILTER, "_защищён")
        if not p:
            return
        try:
            C.save_encrypted(self.doc, p, v["pw"], v["owner"], v["print"], v["copy"], v["edit"])
        except Exception as e:
            return self.error("Не удалось сохранить", e)
        self.done(f"Защищённый файл сохранён:\n{p}", p)

    def tool_unlock(self):
        QMessageBox.information(self, "Снять пароль",
                                "Откройте защищённый PDF — программа спросит пароль.\n"
                                "После этого сохраните его («Сохранить как») — копия будет без пароля.")
        self.open_dialog()

    def tool_compare(self):
        a_path = None
        if self.doc.page_count:
            a_name = Path(self.path).name if self.path else "текущий документ"
        else:
            a_path, _ = QFileDialog.getOpenFileName(self, "Первый PDF", self.default_dir(), PDF_FILTER)
            if not a_path:
                return
            a_name = Path(a_path).name
        b_path, _ = QFileDialog.getOpenFileName(self, f"С чем сравнить «{a_name}»?", self.default_dir(), PDF_FILTER)
        if not b_path:
            return
        a = self.load_file(a_path) if a_path else self.doc
        b = self.load_file(b_path)
        if a is None or b is None:
            return
        out = os.path.join(tempfile.mkdtemp(prefix="pdfm_cmp_"), "сравнение.html")
        n = self.run("Сравнение…", C.compare_documents, a, b, out, a_name, Path(b_path).name)
        if n is FAILED:
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(out))
        self.msg(f"Страниц с отличиями: {n}. Отчёт открыт в браузере.", 15000)


# =============================================================================
# Оформление в духе iOS / iPadOS: светлая боковая панель, системный синий, сгруппированные белые
# карточки на сером фоне без рамок, сегментированные вкладки, скругления 10–14 px, красный — только для сроков.
THEMES = {
    "light": dict(win="#f2f2f7", panel="#ffffff", base="#ffffff", alt="#f7f7fa", text="#1c1c1e", muted="#8e8e93",
                  border="#e5e5ea", input_border="#d1d1d6", hover="#ececf1", pressed="#dedee4",
                  fill="rgba(118,118,128,0.12)", fill_hover="rgba(118,118,128,0.20)",
                  pages="#f2f2f7", tool_hover="#ececf1", note_bg="rgba(0,122,255,0.08)", note_border="rgba(0,122,255,0.20)",
                  note_text="#1c1c1e", canvas="#e5e5ea", item_hover="rgba(0,0,0,0.04)",
                  disabled="#b0b0b8", thumb_border="#e5e5ea", tooltip="#1c1c1e", tooltip_text="#ffffff",
                  accent="#007aff", accent_soft="rgba(0,122,255,0.12)", wax="#ff3b30", success="#248a3d",
                  banner="rgba(255,59,48,0.10)", banner_text="#d70015", nav="#f7f7fa", danger="#ff3b30",
                  side="#f7f7fa", side_text="#1c1c1e", side_muted="#8e8e93", side_hover="rgba(0,0,0,0.05)",
                  side_line="#e5e5ea", side_active="#007aff", seg_on="#ffffff", shadow=(0, 0, 0, 28)),
    "dark": dict(win="#000000", panel="#1c1c1e", base="#1c1c1e", alt="#232325", text="#f2f2f7", muted="#98989f",
                 border="#2c2c2e", input_border="#3a3a3c", hover="#2c2c2e", pressed="#3a3a3c",
                 fill="rgba(118,118,128,0.24)", fill_hover="rgba(118,118,128,0.34)",
                 pages="#000000", tool_hover="#2c2c2e", note_bg="rgba(10,132,255,0.14)", note_border="rgba(10,132,255,0.30)",
                 note_text="#f2f2f7", canvas="#0c0c0d", item_hover="rgba(255,255,255,0.05)",
                 disabled="#5a5a5f", thumb_border="#2c2c2e", tooltip="#f2f2f7", tooltip_text="#1c1c1e",
                 accent="#0a84ff", accent_soft="rgba(10,132,255,0.20)", wax="#ff453a", success="#30d158",
                 banner="rgba(255,69,58,0.16)", banner_text="#ff6961", nav="#1c1c1e", danger="#ff453a",
                 side="#161618", side_text="#f2f2f7", side_muted="#98989f", side_hover="rgba(255,255,255,0.06)",
                 side_line="#2c2c2e", side_active="#0a84ff", seg_on="#636366", shadow=(0, 0, 0, 90)),
}
THEMES["light"]["mode"] = "light"
THEMES["dark"]["mode"] = "dark"


def _theme(parent, **over):
    """Дизайнерская тема на основе светлой или тёмной: свои фон, панели и акцент."""
    t = dict(THEMES[parent])
    t.update(over)
    return t


def _tint(r, g, b):
    return dict(fill=f"rgba({r},{g},{b},0.11)", fill_hover=f"rgba({r},{g},{b},0.19)",
                accent_soft=f"rgba({r},{g},{b},0.15)", note_bg=f"rgba({r},{g},{b},0.09)",
                note_border=f"rgba({r},{g},{b},0.22)")


THEMES.update({
    "coffee": _theme("light", win="#f3eee8", panel="#fffdfa", base="#fffdfa", alt="#f8f3ec", text="#2b2119",
                     muted="#8b7b6d", border="#e7ddd1", input_border="#d8cab9", hover="#efe6db", pressed="#e5d9ca",
                     pages="#f3eee8", tool_hover="#efe6db", canvas="#e8dfd4", thumb_border="#e7ddd1",
                     accent="#8b5e3c", side="#efe7dd", side_line="#e2d6c7", side_active="#8b5e3c",
                     seg_on="#fffdfa", tooltip="#2b2119", note_text="#2b2119", success="#4f7a28", **_tint(139, 94, 60)),
    "lavender": _theme("light", win="#f5f3fb", alt="#f8f6fd", text="#221c33", muted="#857d99", border="#e6e1f2",
                       input_border="#d4cce8", hover="#eee9f8", pressed="#e3dcf3", pages="#f5f3fb",
                       tool_hover="#eee9f8", canvas="#e7e2f3", thumb_border="#e6e1f2", accent="#7b4fe0",
                       side="#efebf9", side_line="#e2dcf2", side_active="#7b4fe0", tooltip="#221c33",
                       note_text="#221c33", **_tint(123, 79, 224)),
    "mint": _theme("light", win="#eef5f0", alt="#f5faf6", text="#17261d", muted="#6f8577", border="#dde9e1",
                   input_border="#c7d9cd", hover="#e6f0e9", pressed="#d9e8de", pages="#eef5f0", tool_hover="#e6f0e9",
                   canvas="#dfe9e2", thumb_border="#dde9e1", accent="#1f8a4c", side="#e8f2eb", side_line="#d6e6db",
                   side_active="#1f8a4c", tooltip="#17261d", note_text="#17261d", success="#1f8a4c",
                   **_tint(31, 138, 76)),
    "ocean": _theme("light", win="#edf4f7", alt="#f4f9fb", text="#132430", muted="#6a808e", border="#dae6ec",
                    input_border="#c5d6df", hover="#e3edf2", pressed="#d6e5ec", pages="#edf4f7", tool_hover="#e3edf2",
                    canvas="#dce8ee", thumb_border="#dae6ec", accent="#0a7ea4", side="#e6f0f5", side_line="#d3e2ea",
                    side_active="#0a7ea4", tooltip="#132430", note_text="#132430", **_tint(10, 126, 164)),
    "sakura": _theme("light", win="#fbf1f3", alt="#fdf6f8", text="#2e1a20", muted="#937680", border="#f0dfe4",
                     input_border="#e4cbd3", hover="#f6e6eb", pressed="#efd8df", pages="#fbf1f3", tool_hover="#f6e6eb",
                     canvas="#efdde3", thumb_border="#f0dfe4", accent="#c2255c", side="#f8e9ed", side_line="#eed8df",
                     side_active="#c2255c", tooltip="#2e1a20", note_text="#2e1a20", **_tint(194, 37, 92)),
    "graphite": _theme("dark", win="#121212", panel="#1e1e1e", base="#1e1e1e", alt="#262626", side="#181818",
                       border="#2c2c2c", input_border="#3a3a3a", hover="#2a2a2a", pressed="#333333", pages="#121212",
                       tool_hover="#2a2a2a", canvas="#0b0b0b", thumb_border="#2c2c2c", accent="#c7761a",
                       side_active="#c7761a", seg_on="#4a4a4a", side_line="#2c2c2c", **_tint(230, 150, 50)),
    "midnight": _theme("dark", win="#0f0c1a", panel="#1a1628", base="#1a1628", alt="#221d33", side="#15111f",
                       border="#2a2440", input_border="#3a3355", hover="#251f38", pressed="#2f2846", text="#ece8f7",
                       muted="#9a93b3", pages="#0f0c1a", tool_hover="#251f38", canvas="#0a0812", thumb_border="#2a2440",
                       accent="#7c4dff", side_active="#7c4dff", seg_on="#3a3355", side_line="#2a2440",
                       tooltip="#ece8f7", note_text="#ece8f7", side_text="#ece8f7", **_tint(150, 120, 255)),
    "forest": _theme("dark", win="#0d1511", panel="#15201a", base="#15201a", alt="#1b2921", side="#111a15",
                     border="#22332a", input_border="#2f463a", hover="#1d2c24", pressed="#26392f", text="#e6f0ea",
                     muted="#8fa699", pages="#0d1511", tool_hover="#1d2c24", canvas="#08100c", thumb_border="#22332a",
                     accent="#1f9d5b", side_active="#1f9d5b", seg_on="#2f463a", side_line="#22332a",
                     tooltip="#e6f0ea", note_text="#e6f0ea", side_text="#e6f0ea", success="#34c77b",
                     **_tint(80, 200, 140)),
})
THEME_NAMES = {"system": "Как в Windows", "light": "Светлая", "dark": "Тёмная",
               "coffee": "Кофе — коричневая", "lavender": "Лаванда — фиолетовая", "mint": "Мята — зелёная",
               "ocean": "Океан — бирюзовая", "sakura": "Сакура — розовая",
               "graphite": "Графит — тёмная, янтарь", "midnight": "Полночь — тёмно-фиолетовая",
               "forest": "Лес — тёмно-зелёная"}
T = dict(THEMES["light"])            # текущие цвета (меняются при смене темы)
SERIF = "Segoe UI"                    # шрифт заголовков (уточняется при запуске); имя осталось от прежнего дизайна
SERIF_CHOICES = ("SF Pro Display", "Segoe UI Variable Display", "Segoe UI", "Inter", "Helvetica Neue",
                 "Noto Sans", "DejaVu Sans")


def pick_serif():
    global SERIF
    fams = set(QFontDatabase.families())
    for f in SERIF_CHOICES:
        if f in fams:
            SERIF = f
            break
    return SERIF


def ui_asset(name, svg):
    """SVG-значок для стилей (галочка чекбокса, стрелка списка) — пишется в папку данных."""
    d = os.path.join(data_dir(), "ui")
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, name)
    try:
        with open(p, "r", encoding="utf-8") as f:
            if f.read() == svg:
                return p.replace("\\", "/")
    except OSError:
        pass
    with open(p, "w", encoding="utf-8") as f:
        f.write(svg)
    return p.replace("\\", "/")


def make_style(t):
    A = t["accent"]
    S = SERIF
    dark = t.get("mode") == "dark"
    tick = ui_asset("check.svg", '<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 18 18">'
                    '<path d="M4.5 9.5l3 3 6-7" fill="none" stroke="#ffffff" stroke-width="2.2" '
                    'stroke-linecap="round" stroke-linejoin="round"/></svg>')
    arrow = ui_asset("chevron-dark.svg" if dark else "chevron.svg",
                     '<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 12 12">'
                     f'<path d="M3 4.5l3 3 3-3" fill="none" stroke="{t["muted"]}" stroke-width="1.6" '
                     'stroke-linecap="round" stroke-linejoin="round"/></svg>')
    return f"""
* {{ outline: 0; }}
QMainWindow, QDialog {{ background: {t['win']}; }}
QWidget {{ color: {t['text']}; }}
QMenuBar {{ background: {t['side']}; color: {t['text']}; padding: 3px 8px; border-bottom: 1px solid {t['border']}; }}
QMenuBar::item {{ padding: 4px 10px; border-radius: 6px; background: transparent; }}
QMenuBar::item:selected {{ background: {t['fill']}; }}
QMenu {{ background: {t['panel']}; color: {t['text']}; border: 1px solid {t['border']}; border-radius: 12px; padding: 6px; }}
QMenu::item {{ padding: 7px 26px 7px 12px; border-radius: 7px; }}
QMenu::item:selected {{ background: {A}; color: white; }}
QMenu::item:disabled {{ color: {t['disabled']}; }}
QMenu::separator {{ height: 1px; background: {t['border']}; margin: 5px 10px; }}

/* боковая панель — как в iPadOS */
QToolButton#appmenu {{ border: none; border-radius: 8px; padding: 2px 8px; font-size: 15pt; color: {t['text']};
    background: transparent; }}
QToolButton#appmenu:hover, QToolButton#appmenu:pressed {{ background: {t['side_hover']}; }}
QToolButton#appmenu::menu-indicator {{ image: none; width: 0; }}
QToolButton#sidefold {{ border: none; border-radius: 8px; padding: 2px 8px; font-size: 15pt; color: {t['muted']};
    background: transparent; }}
QToolButton#sidefold:hover {{ background: {t['side_hover']}; color: {t['text']}; }}
QToolButton#railbtn {{ border: none; border-radius: 10px; font-size: 14pt; background: transparent; color: {t['text']}; }}
QToolButton#railbtn:hover {{ background: {t['side_hover']}; }}
QWidget#sidebar {{ background: {t['side']}; border-right: 1px solid {t['border']}; }}
QLabel#brand {{ color: {t['text']}; font-family: "{S}"; font-size: 18pt; font-weight: 700; }}
QLabel#brandsub {{ color: {t['muted']}; font-size: 9pt; }}
QToolButton#seg {{ background: transparent; color: {t['text']}; border: none; border-radius: 7px;
    padding: 6px 2px; font-size: 9pt; }}
QToolButton#seg:hover {{ background: {t['fill']}; }}
QToolButton#seg:checked {{ background: {t['seg_on']}; color: {t['text']}; font-weight: 600; }}
QFrame#segtrack {{ background: {t['fill']}; border-radius: 9px; }}
QTreeWidget#tools {{ background: transparent; color: {t['text']}; border: none; padding: 4px 6px 10px 6px; }}
QTreeWidget#tools::item {{ padding: 6px 8px; border-radius: 8px; margin: 0; }}
QTreeWidget#tools::item:hover {{ background: {t['side_hover']}; }}
QTreeWidget#tools::item:selected {{ background: {A}; color: white; }}
QToolButton#help {{ border: none; border-radius: 10px; min-width: 20px; max-width: 20px; min-height: 20px; max-height: 20px;
    color: {A}; background: {t['accent_soft']}; font-size: 9pt; font-weight: 700; padding: 0; }}
QToolButton#help:hover {{ background: {A}; color: white; }}

/* панель документа */
QToolBar {{ background: {t['panel']}; border: none; border-bottom: 1px solid {t['border']}; padding: 6px 10px; spacing: 2px; }}
QToolBar::separator {{ width: 1px; background: {t['border']}; margin: 8px 8px; }}
QToolBar#pagebar {{ padding: 2px 10px; }}
QToolBar#pagebar QToolButton {{ padding: 3px 9px; }}
QToolBar QToolButton {{ padding: 6px 11px; border-radius: 8px; color: {A}; }}
QToolBar QToolButton:hover {{ background: {t['fill']}; }}
QToolBar QToolButton:pressed {{ background: {t['fill_hover']}; }}
QToolBar QToolButton:disabled {{ color: {t['disabled']}; }}
QToolBar QToolButton#tbprimary {{ background: {A}; color: white; font-weight: 600; padding: 6px 16px; border-radius: 9px; }}
QToolBar QLabel {{ color: {t['muted']}; }}
QToolBar QLabel#doctitle {{ color: {t['text']}; font-family: "{S}"; font-size: 13pt; font-weight: 600; padding-right: 14px; }}
QToolBar#pagebar QLabel#doctitle {{ font-size: 11pt; padding-right: 8px; }}

/* уведомления сверху — скруглённые плашки */
QPushButton#globalsearch {{ text-align: left; padding: 8px 12px; border-radius: 10px; background: {t['panel']};
    color: {t['muted']}; border: 1px solid {t['border']}; }}
QPushButton#globalsearch:hover {{ border-color: {t['accent']}; color: {t['text']}; }}
QPushButton#banner {{ background: {t['banner']}; color: {t['banner_text']}; border: none; border-radius: 12px;
    margin: 10px 18px 0 18px; padding: 10px 16px; text-align: left; font-weight: 600; }}
QPushButton#banner:hover {{ background: {t['banner']}; text-decoration: underline; }}
QFrame#updatebar {{ background: {t['accent_soft']}; border: none; border-radius: 12px; margin: 10px 18px 0 18px; }}
QFrame#updatebar QLabel#updatetext {{ color: {t['text']}; font-weight: 600; background: transparent; }}
QFrame#updatebar QPushButton {{ background: {t['panel']}; }}
QFrame#updatebar QPushButton#updateinstall {{ background: {A}; color: white; font-weight: 600; }}
QListWidget#pages {{ background: {t['pages']}; color: {t['text']}; border: none; padding: 18px; }}
QListWidget#pages::item, QListWidget#pages::item:selected, QListWidget#pages::item:hover {{ background: transparent; border: none; }}

/* дела в боковой панели */
QWidget#sidebar QWidget#sidepanel {{ background: transparent; border: none; }}
QWidget#sidebar QLabel {{ color: {t['text']}; }}
QWidget#sidebar QLabel#title {{ font-size: 15pt; font-weight: 700; }}
QWidget#sidebar QLineEdit {{ background: {t['fill']}; border: none; border-radius: 10px; padding: 7px 10px; color: {t['text']}; }}
QWidget#sidebar QLineEdit:focus {{ border: none; padding: 7px 10px; background: {t['fill_hover']}; }}
QWidget#sidebar QListWidget#caselist {{ background: transparent; border: none; }}
QWidget#sidebar QListWidget#caselist::item {{ color: {t['text']}; padding: 9px 10px; border-radius: 10px; border: none; margin: 1px 0; }}
QWidget#sidebar QListWidget#caselist::item:hover {{ background: {t['side_hover']}; }}
QWidget#sidebar QListWidget#caselist::item:selected {{ background: {A}; color: white; }}
QWidget#sidebar QListWidget#upcoming {{ background: transparent; border: none; }}
QWidget#sidebar QListWidget#upcoming::item {{ color: {t['muted']}; border-bottom: 1px solid {t['border']}; padding: 7px 4px; }}
QWidget#sidebar QCheckBox {{ color: {t['muted']}; }}
QPushButton#loosebtn {{ text-align: left; background: {t['panel']}; color: {t['text']}; border: none;
    border-radius: 10px; padding: 10px 12px; }}
QPushButton#loosebtn:hover {{ background: {t['hover']}; }}
QPushButton#loosebtn:checked {{ background: {A}; color: white; font-weight: 600; }}
QPushButton#sidelink {{ text-align: left; border: none; background: transparent; color: {A}; padding: 8px 4px; }}
QPushButton#sidelink:hover {{ text-decoration: underline; }}

/* карточки действий и обзор */
QPushButton#actioncard {{ background: {t['panel']}; border: none; border-radius: 14px; text-align: left; padding: 0; }}
QPushButton#actioncard:hover {{ background: {t['hover']}; }}
QPushButton#actioncard:pressed {{ background: {t['pressed']}; }}
QLabel#cardicon {{ background: {t['accent_soft']}; border-radius: 10px; }}
QLabel#cardtitle {{ font-weight: 600; font-size: 10.5pt; }}
QLabel#carddesc {{ color: {t['muted']}; font-size: 9pt; }}
QLabel#facts {{ background: {t['panel']}; border: none; border-radius: 14px; padding: 14px 18px; }}
QListWidget#overlist {{ background: transparent; border: none; }}
QListWidget#overlist::item {{ padding: 8px 4px; border-bottom: 1px solid {t['border']}; }}
QListWidget#overlist::item:hover {{ background: {t['item_hover']}; }}
QListWidget#overlist::item:selected {{ background: {t['accent_soft']}; color: {t['text']}; }}
QToolButton#primarytool {{ background: {A}; color: white; border: none; border-radius: 9px; padding: 6px 14px; font-weight: 600; }}
QToolButton#primarytool::menu-indicator, QToolButton#moretabs::menu-indicator, QToolButton#toolsbtn::menu-indicator {{ image: none; width: 0; }}
QToolButton#moretabs {{ border: none; border-radius: 8px; color: {A}; padding: 6px 12px; background: transparent; }}
QToolButton#moretabs:hover {{ background: {t['fill']}; }}
QToolButton#toolsbtn {{ padding: 6px 11px; border-radius: 8px; }}

/* навигатор дел */
QWidget#navigator {{ background: {t['panel']}; border-right: 1px solid {t['border']}; }}
QLabel#navtitle {{ font-family: "{S}"; font-size: 14pt; font-weight: 700; }}
QToolButton#link {{ border: none; color: {A}; background: transparent; padding: 2px 4px; }}
QToolButton#link:hover {{ text-decoration: underline; }}
QTreeWidget#navtree {{ background: transparent; border: none; }}
QTreeWidget#navtree::item {{ padding: 6px 4px; border-radius: 8px; }}
QTreeWidget#navtree::item:hover {{ background: {t['hover']}; }}
QTreeWidget#navtree::item:selected {{ background: {t['accent_soft']}; color: {t['text']}; }}
QToolButton#casebtn {{ border: none; border-radius: 13px; padding: 5px 12px; color: {t['muted']}; background: {t['fill']}; }}
QToolButton#casebtn:hover {{ background: {t['fill_hover']}; }}
QToolButton#casebtn[linked="true"] {{ color: {A}; background: {t['accent_soft']}; font-weight: 600; }}
QToolButton#casebtn::menu-indicator {{ image: none; width: 0; }}
QTableWidget#docs {{ background: {t['panel']}; border: none; border-radius: 12px;
    selection-background-color: {t['accent_soft']}; selection-color: {t['text']}; }}
QTableWidget#docs::item {{ border-bottom: 1px solid {t['border']}; padding: 0 6px; }}
QTableWidget#docs::item:selected {{ background: {t['accent_soft']}; color: {t['text']}; }}
QToolButton#iconpick {{ border: none; border-radius: 8px; }}
QToolButton#iconpick:hover {{ background: {t['accent_soft']}; }}
QTextBrowser#helptext {{ background: {t['panel']}; border: none; }}
QListWidget#helptoc {{ background: transparent; border: none; }}
QListWidget#helptoc::item {{ padding: 8px 10px; border-radius: 8px; margin: 1px 0; }}
QListWidget#helptoc::item:hover {{ background: {t['hover']}; }}
QListWidget#helptoc::item:selected {{ background: {A}; color: white; }}
QTreeWidget#helptoc {{ background: transparent; border: none; font-size: 10.5pt; show-decoration-selected: 0; }}
QTreeWidget#helptoc::branch {{ background: transparent; }}
QTreeWidget#helptoc::item {{ padding: 5px 4px; border-radius: 7px; margin: 1px 0; }}
QTreeWidget#helptoc::item:hover {{ background: {t['hover']}; }}
QTreeWidget#helptoc::item:selected {{ background: {A}; color: white; }}

/* кнопки: основная — залитая синяя, остальные — серые с синим текстом, как в iOS */
QPushButton {{ padding: 7px 13px; border: none; border-radius: 9px; background: {t['fill']}; color: {A}; font-weight: 500; }}
QPushButton:hover {{ background: {t['fill_hover']}; }}
QPushButton:pressed {{ background: {t['fill_hover']}; color: {t['text']}; }}
QPushButton:disabled {{ color: {t['disabled']}; background: {t['fill']}; }}
QPushButton:checked {{ background: {A}; color: white; }}
QPushButton[danger="true"] {{ color: {t['danger']}; }}
QPushButton#compact {{ padding: 7px 9px; }}
QPushButton#primary, QDialogButtonBox QPushButton:default {{ background: {A}; color: white; font-weight: 600; }}
QPushButton#primary:hover, QDialogButtonBox QPushButton:default:hover {{ background: {A}; }}
QPushButton#primary:disabled {{ background: {t['fill']}; color: {t['disabled']}; }}
QToolButton {{ color: {t['text']}; }}
QToolButton#mode {{ text-align: left; padding: 7px 10px; border-radius: 8px; border: none; background: transparent; color: {t['text']}; }}
QToolButton#mode:hover {{ background: {t['fill']}; }}
QToolButton#mode:checked {{ background: {A}; color: white; }}
QFrame#card {{ background: {t['panel']}; border: none; border-radius: 14px; }}
QWidget#sidepanel {{ background: {t['win']}; border-right: 1px solid {t['border']}; }}
QLabel#title {{ font-family: "{S}"; font-size: 22pt; font-weight: 700; }}
QLabel#subtitle {{ font-family: "{S}"; font-size: 13.5pt; font-weight: 700; }}
QLabel#bigresult {{ font-family: "{S}"; font-size: 22pt; font-weight: 700; color: {A}; }}
QLabel#note {{ background: {t['note_bg']}; border: none; border-radius: 12px; padding: 11px 14px; color: {t['note_text']}; }}
QLabel#hint {{ color: {t['muted']}; }}
QTextBrowser#result {{ background: {t['panel']}; border: none; border-radius: 14px; padding: 12px; }}
QListWidget#caselist, QListWidget#upcoming {{ background: transparent; border: none; padding: 0; }}
QListWidget#caselist::item {{ padding: 10px 10px; border-radius: 10px; margin: 1px 0; }}
QListWidget#caselist::item:hover {{ background: {t['hover']}; }}
QListWidget#caselist::item:selected {{ background: {A}; color: white; }}
QListWidget#upcoming::item {{ padding: 8px 6px; border-bottom: 1px solid {t['border']}; }}
QListWidget#upcoming::item:selected {{ background: {t['accent_soft']}; color: {t['text']}; }}
QScrollArea#canvasArea {{ background: {t['canvas']}; border: none; }}
QScrollArea {{ background: transparent; border: none; }}
QStatusBar {{ background: {t['panel']}; color: {t['muted']}; border-top: 1px solid {t['border']}; }}
QStatusBar QLabel {{ color: {t['muted']}; }}
QToolButton#timerbtn {{ color: {A}; border: none; border-radius: 8px; padding: 1px 8px; margin: 1px 4px; font-weight: 600; }}
QToolButton#timerbtn:hover {{ background: {t['fill']}; }}
QFrame#timerpanel {{ background: {t['panel']}; border: 1px solid {t['border']}; border-radius: 12px; }}
QLabel#timerbig {{ color: {t['text']}; font-size: 22pt; font-weight: 600; padding: 2px; }}

/* поля ввода */
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit, QTextEdit, QDateEdit, QTimeEdit {{ padding: 6px 10px;
    border: 1px solid {t['input_border']}; border-radius: 9px; background: {t['base']}; color: {t['text']};
    selection-background-color: {A}; selection-color: white; }}
QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QComboBox:disabled, QDateEdit:disabled {{ color: {t['disabled']}; background: {t['alt']}; }}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus, QPlainTextEdit:focus, QTextEdit:focus, QDateEdit:focus, QTimeEdit:focus {{
    border: 2px solid {A}; padding: 5px 9px; }}
QAbstractItemView QSpinBox, QAbstractItemView QDoubleSpinBox, QAbstractItemView QLineEdit, QAbstractItemView QComboBox,
QAbstractItemView QDateEdit, QAbstractItemView QTimeEdit {{ padding: 0 4px; border-radius: 6px; }}
QComboBox::drop-down, QDateEdit::drop-down {{ border: none; width: 24px; }}
QComboBox::down-arrow, QDateEdit::down-arrow {{ image: url("{arrow}"); width: 12px; height: 12px; }}
QComboBox QAbstractItemView {{ background: {t['panel']}; color: {t['text']}; border: 1px solid {t['border']}; border-radius: 10px;
    selection-background-color: {A}; selection-color: white; padding: 4px; outline: 0; }}

/* таблицы и списки — белые скруглённые группы */
QTableWidget, QTableView, QTreeWidget, QTreeView, QListWidget {{ background: {t['base']}; color: {t['text']}; alternate-background-color: {t['alt']};
    gridline-color: {t['border']}; border: none; border-radius: 12px; }}
QTableWidget, QTableView {{ gridline-color: transparent; selection-background-color: {t['accent_soft']}; selection-color: {t['text']}; }}
QTableWidget::item, QTableView::item {{ border-bottom: 1px solid {t['border']}; padding: 0 4px; }}
QTreeWidget::item, QTreeView::item {{ padding: 5px 4px; border-radius: 7px; }}
QTreeWidget::item:hover, QTreeView::item:hover, QListWidget::item:hover {{ background: {t['item_hover']}; }}
QTableWidget::item:selected, QListWidget::item:selected {{ background: {t['accent_soft']}; color: {t['text']}; }}
QTreeWidget::item:selected, QTreeView::item:selected {{ background: {t['accent_soft']}; color: {A}; font-weight: 600; }}
QTreeView::branch {{ background: transparent; }}
QTreeView::branch:selected {{ background: transparent; }}
QTreeWidget, QTreeView {{ selection-background-color: {t['accent_soft']}; selection-color: {t['text']}; }}
QHeaderView {{ background: transparent; border: none; }}
QHeaderView::section {{ background: {t['panel']}; color: {t['muted']}; border: none; border-bottom: 1px solid {t['border']};
    padding: 7px 6px; font-size: 9pt; font-weight: 600; }}
QTableCornerButton::section {{ background: {t['panel']}; border: none; }}

/* вкладки — сегментированный переключатель */
QTabWidget::pane {{ border: none; }}
QTabWidget::tab-bar {{ left: 0; }}
QTabBar {{ background: transparent; }}
QTabBar::tab {{ background: {t['fill']}; color: {t['text']}; padding: 6px 13px; margin: 0; border: none; border-radius: 0; }}
QTabBar::tab:first {{ border-top-left-radius: 9px; border-bottom-left-radius: 9px; }}
QTabBar::tab:last {{ border-top-right-radius: 9px; border-bottom-right-radius: 9px; }}
QTabBar::tab:only-one {{ border-radius: 9px; }}
QTabBar::tab:hover {{ background: {t['fill_hover']}; }}
QTabBar::tab:selected {{ background: {A}; color: white; font-weight: 600; }}
QTabBar#docseg::tab {{ border-radius: 12px; margin: 0 3px; padding: 7px 14px; }}

QCheckBox, QRadioButton, QLabel {{ color: {t['text']}; }}
QCheckBox:disabled, QRadioButton:disabled, QLabel:disabled {{ color: {t['disabled']}; }}
QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{ width: 18px; height: 18px; border-radius: 6px; border: 1.5px solid {t['input_border']}; background: {t['base']}; }}
QCheckBox::indicator:hover {{ border-color: {A}; }}
QCheckBox::indicator:checked {{ background: {A}; border-color: {A}; image: url("{tick}"); }}
QCheckBox::indicator:disabled {{ background: {t['alt']}; border-color: {t['border']}; }}
QRadioButton::indicator {{ width: 16px; height: 16px; border-radius: 9px; border: 1.5px solid {t['input_border']}; background: {t['base']}; }}
QRadioButton::indicator:checked {{ border: 5px solid {A}; background: white; }}
QToolTip {{ background: {t['tooltip']}; color: {t['tooltip_text']}; border: none; border-radius: 8px; padding: 6px 9px; }}
QSplitter::handle {{ background: {t['border']}; }}
QSplitter::handle:horizontal {{ width: 1px; }}
QSplitter::handle:vertical {{ height: 1px; }}
QScrollBar:vertical {{ background: transparent; width: 9px; margin: 3px 2px; }}
QScrollBar::handle:vertical {{ background: {t['fill_hover']}; border-radius: 3px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {t['muted']}; }}
QScrollBar:horizontal {{ background: transparent; height: 9px; margin: 2px 3px; }}
QScrollBar::handle:horizontal {{ background: {t['fill_hover']}; border-radius: 3px; min-width: 30px; }}
QScrollBar::handle:horizontal:hover {{ background: {t['muted']}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{ width: 0; border: none; }}
QSpinBox::up-button, QSpinBox::down-button, QDateEdit::up-button, QDateEdit::down-button {{ width: 16px; border: none; background: transparent; }}
QSlider::groove:horizontal {{ height: 4px; background: {t['fill_hover']}; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {A}; border-radius: 2px; }}
QSlider::handle:horizontal {{ background: white; border: 1px solid {t['input_border']}; width: 18px; height: 18px; margin: -8px 0; border-radius: 10px; }}
QProgressBar {{ background: {t['fill']}; border: none; border-radius: 4px; height: 8px; text-align: center; color: transparent; }}
QProgressBar::chunk {{ background: {A}; border-radius: 4px; }}
QProgressDialog {{ background: {t['win']}; }}
"""




def system_is_dark():
    try:
        hints = QApplication.styleHints()
        if hasattr(hints, "colorScheme"):
            cs = hints.colorScheme()
            if cs == Qt.ColorScheme.Dark:
                return True
            if cs == Qt.ColorScheme.Light:
                return False
    except Exception:
        pass
    if C.IS_WIN:
        try:
            import winreg
            k = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                               r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
            return winreg.QueryValueEx(k, "AppsUseLightTheme")[0] == 0
        except Exception:
            pass
    return False


def settings():
    from PySide6.QtCore import QSettings
    return QSettings(os.path.join(data_dir(), "settings.ini"), QSettings.IniFormat)


def theme_choice():
    v = settings().value("theme", "system")
    return v if v in THEME_NAMES else "system"


def apply_theme(app, choice=None):
    pick_serif()
    """Применить тему: 'system' | 'light' | 'dark'. Палитра задаётся явно, чтобы
    цвета текста и фона всегда подходили друг к другу (раньше в тёмном режиме
    Windows текст становился белым на белом фоне)."""
    choice = choice or theme_choice()
    name = ("dark" if system_is_dark() else "light") if choice == "system" else choice
    t = THEMES.get(name, THEMES["light"])
    T.clear()
    T.update(t, name=t.get("mode", "light"), theme=name)     # name — светлая/тёмная (карта дела, заставка)
    pal = QPalette()
    roles = {
        QPalette.Window: t["win"], QPalette.WindowText: t["text"], QPalette.Base: t["base"],
        QPalette.AlternateBase: t["alt"], QPalette.Text: t["text"], QPalette.Button: t["panel"],
        QPalette.ButtonText: t["text"], QPalette.ToolTipBase: t["tooltip"], QPalette.ToolTipText: t["tooltip_text"],
        QPalette.PlaceholderText: t["muted"], QPalette.Highlight: t["accent"], QPalette.HighlightedText: "#ffffff",
        QPalette.Link: t["accent"], QPalette.BrightText: "#ffffff",
        QPalette.Light: t["hover"], QPalette.Midlight: t["border"], QPalette.Mid: t["input_border"],
        QPalette.Dark: t["pressed"], QPalette.Shadow: "#000000",
    }
    for role, col in roles.items():
        pal.setColor(role, QColor(col))
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        pal.setColor(QPalette.Disabled, role, QColor(t["disabled"]))
    app.setPalette(pal)
    app.setStyleSheet(make_style(t) + modern_ui.stylesheet(t) + dialog_style(t))
    modern_ui.install(t)
    modern_ui.set_theme(t)
    return name


def dialog_style(t):
    """Окна инструментов (OptionsDialog): карточка со значком, подписи над полями, нижняя полоса с кнопками."""
    return f"""
QDialog#tooldlg {{ background: {t['panel']}; }}
QDialog#tooldlg QLabel#dlgtitle {{ font-family: "{SERIF}"; font-size: 15pt; font-weight: 700; }}
QDialog#tooldlg QLabel#dlgsub {{ color: {t['muted']}; font-size: 9.5pt; }}
QDialog#tooldlg QLabel#fieldlabel {{ color: {t['muted']}; font-size: 8.5pt; font-weight: 600; }}
QDialog#tooldlg QLabel#fieldlabel:disabled {{ color: {t['disabled']}; }}
QFrame#dlgfoot {{ background: {t['alt']}; border-top: 1px solid {t['border']}; }}
QTextBrowser#helppop {{ background: transparent; border: none; }}
QFrame#edside {{ background: {t['side']}; border-right: 1px solid {t['border']}; }}
QLabel#edtitle {{ font-family: "{SERIF}"; font-size: 13pt; font-weight: 700; padding: 0 6px; }}
QLabel#edgroup {{ color: {t['muted']}; font-size: 7.5pt; font-weight: 700; letter-spacing: 1px; padding: 8px 8px 3px 8px; }}
QPushButton#edtool {{ text-align: left; border: none; border-radius: 8px; padding: 6px 10px; background: transparent;
    color: {t['text']}; font-size: 9.5pt; }}
QPushButton#edtool:hover {{ background: {t['side_hover']}; }}
QPushButton#edtool:checked {{ background: {t['accent_soft']}; color: {t['accent']}; font-weight: 600; }}
QFrame#edbar {{ background: {t['panel']}; border: 1px solid {t['border']}; border-radius: 12px; }}
QLabel#edhint {{ color: {t['text']}; font-size: 9.5pt; }}
QLabel#edhinticon {{ font-size: 14pt; padding: 0 2px; }}
QLabel#edlabel {{ color: {t['muted']}; font-size: 8.5pt; font-weight: 600; }}
QFrame#edpill {{ background: {t['panel']}; border: 1px solid {t['border']}; border-radius: 11px; }}
QPushButton#edpillbtn {{ background: transparent; border-radius: 8px; padding: 5px 11px; font-size: 11pt; color: {t['text']}; }}
QPushButton#edpillbtn:hover {{ background: {t['fill']}; }}
QPushButton#edpillbtn:disabled {{ color: {t['disabled']}; background: transparent; }}
QLabel#edpilltext {{ color: {t['muted']}; font-size: 9pt; }}
"""


def restart_app():
    """Запустить программу заново (после восстановления из копии) и выйти без сохранения настроек."""
    if getattr(sys, "frozen", False):
        args = [sys.executable]
    else:
        args = [sys.executable, os.path.abspath(sys.argv[0])]
    try:
        subprocess.Popen(args, cwd=os.path.dirname(args[-1]), creationflags=0x00000008 if C.IS_WIN else 0)
    except Exception as e:
        log_error("Перезапуск программы", e)
    os._exit(0)


def startup_db_check():
    """До открытия окна: если база дел повреждена — предложить вернуть последнюю целую копию."""
    path = os.path.join(data_dir(), BK.DB_NAME)
    if BK.check_db(path):
        return
    log_error("База дел повреждена при запуске")
    good = next((b for b in BK.list_backups() if BK.backup_is_valid(b["path"])), None)
    if good:
        cases = "" if good["cases"] is None else f", дел: {good['cases']}"
        ans = QMessageBox.warning(
            None, APP_NAME, "База дел повреждена (например, после сбоя питания или ошибки).\n\n"
            f"Восстановить её из резервной копии от {good['created']:%d.%m.%Y %H:%M}{cases}?\n"
            "Повреждённый файл будет сохранён рядом.", QMessageBox.Yes | QMessageBox.No)
        if ans == QMessageBox.Yes:
            try:
                import shutil
                shutil.copy2(path, path + f".повреждена-{int(__import__('time').time())}")
                BK.restore(good["path"], data_dir(), APP_VERSION)
                QMessageBox.information(None, APP_NAME, "Данные восстановлены.")
            except Exception as e:
                QMessageBox.critical(None, APP_NAME, f"Не удалось восстановить: {e}")
            return
    else:
        QMessageBox.warning(None, APP_NAME, "База дел повреждена, а резервных копий нет. Программа попробует "
                                            "открыть её как есть; повреждённый файл: " + path)


def polish_ui(root):
    """Мелочи оформления, которые не задаются стилями: красные кнопки «Удалить» (как деструктивные
    действия в iOS), таблицы без вертикальной сетки, вкладки без линии под ними."""
    for b in root.findChildren(QPushButton):
        if b.text().startswith(("Удалить", "Убрать")) and not b.property("danger"):
            b.setProperty("danger", True)
            b.style().unpolish(b)
            b.style().polish(b)
    for t in root.findChildren(QTableWidget):
        t.setShowGrid(False)
    for bar in root.findChildren(QTabBar):
        bar.setDrawBase(False)


def _selftest(say):
    """Собрать главное окно и загрузить все библиотеки, которые программа подгружает позже (Word, Excel,
    распознавание…). Код выхода 0 — всё на месте; иначе причина — в отчёте SELFTEST_LOG. Окно не показывается."""
    code = 0
    try:
        w = MainWindow()
        say("MainWindow ok")
        QApplication.processEvents()
        for mod in ("pdf2docx", "cv2", "numpy", "docx", "pptx", "openpyxl", "palette", "word_editor", "lxml",
                    "PySide6.QtWebEngineWidgets"):
            try:
                __import__(mod)
                say("import ok", mod)
            except Exception as e:
                say("IMPORT FAILED", mod, repr(e))
                code = 2
        try:                                 # встроенный браузер («Карта дела») действительно открывает страницу
            from PySide6.QtWebEngineWidgets import QWebEngineView
            import time as _t
            view = QWebEngineView()
            done = []
            view.loadFinished.connect(done.append)
            view.setHtml("<html><body><p id='x'>Проверка</p></body></html>")
            t0 = _t.time()
            while not done and _t.time() - t0 < 40:
                QApplication.processEvents()
                _t.sleep(0.05)
            say("webengine load:", done[:1] or "нет ответа за 40 с")
            if done and not done[0]:
                code = 4
        except Exception as e:
            say("WEBENGINE FAILED", repr(e))
            code = 4
        w.hide()
    except Exception:
        say("FAILED:\n" + traceback.format_exc())
        code = 1
    say("exit code", code)
    os._exit(code)


def _safe_delete(w):
    try:
        w.deleteLater()
    except RuntimeError:
        pass


SELFTEST_LOG = os.path.join(tempfile.gettempdir(), "legalhelper_selftest.txt")


def _selftest_guard():
    """Для пробного запуска: никаких окон с вопросами (их некому закрыть) — всё в отчёт; зависание дольше
    минуты — записать, где программа застряла, и выйти с кодом 3."""
    import faulthandler
    import threading
    rep = open(SELFTEST_LOG, "w", encoding="utf-8", buffering=1)
    rep.write(f"LegalHelper {APP_VERSION} selftest\n")
    faulthandler.enable(rep)

    def say(*a):
        rep.write(" ".join(str(x) for x in a) + "\n")

    def box(kind):
        def f(*a, **k):
            say(f"QMessageBox.{kind}:", *[x for x in a if isinstance(x, str)][:2])
            return QMessageBox.No if kind == "question" else QMessageBox.Ok
        return staticmethod(f)
    for kind in ("warning", "information", "critical", "question"):
        setattr(QMessageBox, kind, box(kind))
    QDialog.exec = lambda self, *a: (say("QDialog.exec:", type(self).__name__, self.windowTitle()), 0)[1]
    QMessageBox.exec = lambda self, *a: (say("QMessageBox.exec:", self.text()[:120]), 0)[1]

    def watchdog():
        import time
        time.sleep(90)
        say("ЗАВИСАНИЕ: где сейчас каждый поток:")
        faulthandler.dump_traceback(rep, all_threads=True)
        rep.flush()
        os._exit(3)
    threading.Thread(target=watchdog, daemon=True).start()
    return say


def main():
    say = _selftest_guard() if "--selftest" in sys.argv else None
    if C.IS_WIN:
        try:  # своя иконка на панели задач
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("LegalHelper.App.1")
        except Exception:
            pass
    def hook(t, e, tb):                     # непойманные ошибки — в журнал и окно, а не молча
        text = "".join(traceback.format_exception(t, e, tb))
        log_error("Непредвиденная ошибка", tb=text)
        try:
            QMessageBox.warning(None, APP_NAME, f"Произошла ошибка:\n{e}\n\nОна записана в журнал "
                                                "(Справка → Журнал ошибок).")
        except Exception:
            pass
    sys.excepthook = hook
    from PySide6.QtCore import QCoreApplication
    QCoreApplication.setAttribute(Qt.AA_ShareOpenGLContexts)   # нужно для встроенной карты дела (WebEngine)
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    from PySide6.QtCore import QLocale
    QLocale.setDefault(QLocale(QLocale.Russian, QLocale.Russia))
    try:                                    # системные надписи Qt по-русски («Копировать», «Вставить», «Да»…)
        from PySide6.QtCore import QTranslator, QLibraryInfo
        tr = QTranslator(app)
        if tr.load("qtbase_ru", QLibraryInfo.path(QLibraryInfo.TranslationsPath)):
            app.installTranslator(tr)
    except Exception:
        pass
    app.setStyle("Fusion")
    f = app.font()
    fams = set(QFontDatabase.families())
    for fam in ("Segoe UI Variable Text", "SF Pro Text", "Segoe UI", "Helvetica Neue", "Inter"):
        if fam in fams:
            f.setFamily(fam)
            break
    f.setPointSize(10)
    app.setFont(f)
    apply_theme(app)
    startup_db_check()
    try:   # «Как в Windows»: следить за сменой темы системы на лету
        app.styleHints().colorSchemeChanged.connect(
            lambda *_: theme_choice() == "system" and (apply_theme(app), [w.refresh_theme() for w in
                                                       app.topLevelWidgets() if hasattr(w, "refresh_theme")]))
    except Exception:
        pass
    if say:                                     # пробный запуск при сборке установщика (см. release.yml)
        say("QApplication ok, db ok")
        _selftest(say)
    anim.ENABLED = str(settings().value("animations", "1")) != "0"
    splash = None
    if anim.ENABLED:                            # заставка, пока открывается главное окно
        splash = anim.Splash(QIcon(resource("app.ico")).pixmap(256, 256), APP_NAME, APP_VERSION,
                             dark=T.get("name") == "dark")
        splash.start()
        anim.wait(220)                          # дать заставке проявиться (раньше 0,42 с — лишнее ожидание)
        splash.hold()
    w = MainWindow()
    if splash:
        w.setWindowOpacity(0.0)
        w.show()
        splash.finish(w)
    else:
        w.show()
    files = [a for a in sys.argv[1:] if os.path.isfile(a)]
    if files:
        QTimer.singleShot(100, lambda: w.open_paths(files, replace=True))
    QTimer.singleShot(90_000, tidy_old_build)
    sys.exit(app.exec())


def tidy_old_build():
    """Убрать остатки старого способа обновления (до 3.2.1 программа собиралась прямо на компьютере):
    в %LOCALAPPDATA%\\PDFMaster-build лежали Python со всеми библиотеками и черновики сборки — часто больше
    гигабайта. Теперь обновление ставится готовым установщиком, и они не нужны. Копия прошлой версии
    для «Вернуть предыдущую версию» (previous) остаётся."""
    if not (C.IS_WIN and getattr(sys, "frozen", False)):
        return
    work = os.path.join(os.environ.get("LOCALAPPDATA", ""), "PDFMaster-build")
    if not os.path.isdir(work) or os.path.abspath(sys.executable).lower().startswith(os.path.abspath(work).lower()):
        return
    keep = {"previous", "rollback.cmd", "update.log"}

    def work_():
        import shutil
        for name in os.listdir(work):
            if name.lower() in keep:
                continue
            p = os.path.join(work, name)
            try:
                if os.path.isdir(p):
                    shutil.rmtree(p, ignore_errors=True)
                else:
                    os.remove(p)
            except OSError:
                pass
    import threading
    threading.Thread(target=work_, daemon=True).start()


if __name__ == "__main__":
    main()
