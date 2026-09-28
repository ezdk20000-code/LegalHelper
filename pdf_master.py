# -*- coding: utf-8 -*-
"""
LegalHelper — рабочее место юриста и настольный редактор PDF.
Запуск:  python pdf_master.py [файлы...]
"""
import os
import sys
import tempfile
import traceback
import subprocess
from pathlib import Path

import pymupdf as fitz
from PySide6.QtCore import (Qt, QSize, QTimer, Signal, QPointF, QRectF, QUrl, QByteArray, QBuffer,
                            QIODevice)
from PySide6.QtGui import (QAction, QActionGroup, QIcon, QImage, QPixmap, QPainter, QPen, QColor,
                           QFont, QKeySequence, QDesktopServices, QPainterPath, QPalette, QFontDatabase)
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QListWidget, QListWidgetItem, QListView, QAbstractItemView,
    QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QPushButton, QToolBar, QFileDialog, QMessageBox,
    QInputDialog, QLineEdit, QDialog, QDialogButtonBox, QSpinBox, QDoubleSpinBox, QComboBox,
    QCheckBox, QPlainTextEdit, QColorDialog, QProgressDialog, QTreeWidget, QTreeWidgetItem, QSplitter,
    QScrollArea, QMenu, QSlider, QTabWidget, QTableWidget, QTableWidgetItem, QHeaderView, QToolButton,
    QSizePolicy, QStyle, QFrame, QRadioButton, QButtonGroup, QStackedWidget, QTabBar)

import pdf_core as C
import legal_core as L
import legal_ui as U
import help_ui as H
import updater as UPD
import timecheck as TC
import backup as BK
import casefile as CF
import anim

APP_NAME = "LegalHelper"
APP_VERSION = "2.2"
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


class OptionsDialog(QDialog):
    """Универсальный диалог параметров.
    fields: (ключ, подпись, тип, значение_по_умолчанию, доп)"""

    def __init__(self, parent, title, fields, note=None, ok_text="Выполнить", depends=None, help=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(460)
        self.w = {}
        lay = QVBoxLayout(self)
        if note:
            lab = QLabel(note)
            lab.setWordWrap(True)
            lab.setObjectName("note")
            lay.addWidget(lab)
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        lay.addLayout(form)
        for f in fields:
            key, label, kind = f[0], f[1], f[2]
            default = f[3] if len(f) > 3 else None
            extra = f[4] if len(f) > 4 else None
            w = self._make(kind, label, default, extra)
            self.w[key] = (kind, w)
            if kind == "check":
                form.addRow("", w)
            else:
                form.addRow(label + ":", w)
        # depends: {поле: (управляющее_поле, функция(значение) -> bool)} — включать поле по условию
        for dep, (ctrl, cond) in (depends or {}).items():
            cw = self.w[ctrl][1]
            dw = self.w[dep][1]
            lbl = form.labelForField(dw)

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
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText(ok_text)
        bb.button(QDialogButtonBox.Cancel).setText("Отмена")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        if help:                                   # кнопка «?» с подсказкой к функции
            row = QHBoxLayout()
            row.addWidget(U.HelpButton(help))
            row.addStretch(1)
            row.addWidget(bb)
            lay.addLayout(row)
        else:
            lay.addWidget(bb)

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
    def ask(parent, title, fields, note=None, ok_text="Выполнить", depends=None, help=None):
        d = OptionsDialog(parent, title, fields, note, ok_text, depends, help)
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

        root = QHBoxLayout(self)
        # ---- панель инструментов слева
        side = QVBoxLayout()
        self.group = QButtonGroup(self)
        self.btns = {}
        for key, label, kind, tip in self.MODES:
            b = QToolButton()
            b.setText(label)
            b.setCheckable(True)
            b.setToolTip(tip)
            b.setToolButtonStyle(Qt.ToolButtonTextOnly)
            b.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            b.setObjectName("mode")
            self.group.addButton(b)
            b.clicked.connect(lambda _=False, k=key: self.set_mode(k))
            self.btns[key] = b
            side.addWidget(b)
        side.addStretch()
        sw = QWidget()
        sw.setLayout(side)
        sw.setFixedWidth(170)
        root.addWidget(sw)

        # ---- правая часть
        right = QVBoxLayout()
        top = QHBoxLayout()
        self.hint = QLabel()
        self.hint.setObjectName("hint")
        top.addWidget(self.hint, 1)
        top.addWidget(QLabel("Цвет:"))
        self.color = ColorButton((0.85, 0.1, 0.1))
        top.addWidget(self.color)
        top.addWidget(QLabel("Толщина:"))
        self.width = QDoubleSpinBox()
        self.width.setRange(0.5, 20)
        self.width.setValue(2)
        top.addWidget(self.width)
        right.addLayout(top)

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
        self.b_prev = QPushButton("◀ Пред.")
        self.b_next = QPushButton("След. ▶")
        self.lbl = QLabel()
        b_zo = QPushButton("−")
        b_zi = QPushButton("+")
        b_fit = QPushButton("По ширине")
        b_undo = QPushButton("Отменить (Ctrl+Z)")
        b_close = QPushButton("Готово")
        b_close.setObjectName("primary")
        for b in (b_zo, b_zi):
            b.setFixedWidth(36)
        self.b_prev.clicked.connect(lambda: self.goto(self.index - 1))
        self.b_next.clicked.connect(lambda: self.goto(self.index + 1))
        b_zo.clicked.connect(lambda: self.set_zoom(self.zoom / 1.2))
        b_zi.clicked.connect(lambda: self.set_zoom(self.zoom * 1.2))
        b_fit.clicked.connect(self.fit_width)
        b_undo.clicked.connect(self.undo)
        b_close.clicked.connect(self.accept)
        for w in (self.b_prev, self.lbl, self.b_next):
            bottom.addWidget(w)
        bottom.addStretch()
        for w in (b_zo, b_zi, b_fit, b_undo, b_close):
            bottom.addWidget(w)
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
                self.hint.setText(tip)
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
        self._build()
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
        self.a_edit = act("✎ Редактировать", lambda: self.open_editor(), "Ctrl+Return",
                          tip="Открыть страницу в редакторе")
        self.a_selall = act("Выделить всё", lambda: self.pages.selectAll(), QKeySequence.SelectAll)
        self.a_nav = act("Мои дела", self.toggle_nav, "Ctrl+B", tip="Показать или скрыть список дел и документов")
        self.a_nav.setCheckable(True)
        self.a_nav.setChecked(settings().value("nav_visible", "true") == "true")
        tb.addAction(self.a_nav)
        self.doc_title = QLabel("Новый документ")
        self.doc_title.setObjectName("doctitle")
        self.doc_title_act = tb.addWidget(self.doc_title)
        self.case_btn = QToolButton()
        self.case_btn.setObjectName("casebtn")
        self.case_btn.setPopupMode(QToolButton.InstantPopup)
        self.case_btn.setToolTip("Привязать открытый документ к делу")
        self.case_menu = QMenu(self)
        self.case_menu.aboutToShow.connect(self.fill_case_menu)
        self.case_btn.setMenu(self.case_menu)
        self.case_btn_act = tb.addWidget(self.case_btn)
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
        mf.addSeparator()
        mf.addAction("Выход", self.close)
        me = mb.addMenu("Правка")
        for a in (self.a_undo, self.a_redo, self.a_selall):
            me.addAction(a)
        me.addSeparator()
        for a in (self.a_rl, self.a_rr, self.a_del, self.a_dup, self.a_blank, self.a_extract, self.a_edit):
            me.addAction(a)
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
                                         ("Подготовить", "prepare"), ("Сроки и заседания", "events"),
                                         ("Расчёты", "calc"), ("Карта дела", "board"))):
            a = mv.addAction(name, lambda key=key: self.open_case_tab(key))
            a.setShortcut(f"Ctrl+{i + 1}")
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
        tb.addSeparator()
        for a in (self.a_rl, self.a_rr, self.a_del, self.a_edit):
            tb.addAction(a)
        for a in (self.a_selall, self.a_dup, self.a_extract):
            self.addAction(a)
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        tb.addWidget(spacer)
        pass
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(80, 320)
        self.slider.setValue(self.thumb_w)
        self.slider.setFixedWidth(70)
        self.slider.setToolTip("Размер миниатюр")
        self.slider.valueChanged.connect(self.set_thumb_size)
        tb.addWidget(self.slider)

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
        self.pages.itemDoubleClicked.connect(lambda it: self.open_editor(self.pages.row(it)))
        self.pages.setContextMenuPolicy(Qt.CustomContextMenu)
        self.pages.customContextMenuRequested.connect(self.context_menu)
        self.pages.itemSelectionChanged.connect(self.update_status)

        # ================= «Всё вокруг дела» =================
        self.mode_cid = None           # дело, открытое сейчас (None — «Без дела»)
        self._entering = False
        # боковая панель: название, «Без дела», список дел, справка
        side = QWidget()
        side.setObjectName("sidebar")
        side.setFixedWidth(300)
        sv = QVBoxLayout(side)
        sv.setContentsMargins(12, 16, 12, 10)
        sv.setSpacing(0)
        brand = QLabel(APP_NAME)
        brand.setObjectName("brand")
        sub = QLabel("документы, дела и сроки")
        sub.setObjectName("brandsub")
        sv.addWidget(brand)
        sv.addWidget(sub)
        sv.addSpacing(14)

        self.cases_page = U.CasesPage(self)
        self.cases_page.openFile.connect(lambda p, pg: self.open_external(p, pg, self.cases_page.cid))
        self.calc_page = U.CalcPage()
        self.help_page = H.HelpPage(sys.modules[__name__])
        self.help_page.on_back = self.leave_help
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
        b_help.setObjectName("sidelink")
        b_help.setCursor(Qt.PointingHandCursor)
        b_help.clicked.connect(lambda: self.show_section(3))
        sv.addWidget(b_help)

        # область документа: панель инструментов + страницы
        self.removeToolBar(self.toolbar)
        self.toolbar.removeAction(self.a_nav)
        self.docarea = QWidget()
        dv = QVBoxLayout(self.docarea)
        dv.setContentsMargins(0, 0, 0, 0)
        dv.setSpacing(0)
        dv.addWidget(self.toolbar)
        dv.addWidget(self.pages, 1)
        self.toolbar.show()
        self._add_tools_button()

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
        llv.addWidget(self.loose_list, 1)
        bo = QPushButton("Открыть файл…")
        bo.setObjectName("primary")
        bo.clicked.connect(self.open_dialog)
        llv.addWidget(bo)
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
        self.stack.currentChanged.connect(lambda *_: anim.fade_in(self.stack.currentWidget()))

        self.banner = QPushButton()
        self.banner.setObjectName("banner")
        self.banner.setCursor(Qt.PointingHandCursor)
        self.banner.clicked.connect(self.show_cases)
        self.banner.hide()

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
        ch.addWidget(right, 1)
        self.setCentralWidget(central)
        QTimer.singleShot(60, self._initial_mode)
        self.status_lbl = QLabel()
        self.statusBar().addPermanentWidget(self.status_lbl)
        self.apply_thumb_geometry()

    # ------------------------------------------------------------- helpers
    def update_title(self):
        name = Path(self.path).name if self.path else ("Новый документ" if self.doc.page_count else "")
        star = " *" if self.modified else ""
        self.setWindowTitle(f"{name}{star} — {APP_NAME}" if name else APP_NAME)
        if hasattr(self, "doc_title"):
            t = (Path(self.path).stem if self.path else "Новый документ") + ("  •" if self.modified else "")
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
            self.doc_title_act.setVisible(not in_case)     # в деле название видно в списке слева
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
        install.clicked.connect(self.download_update)
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
                self.updateChecked.emit(UPD.fetch_info(), "", silent)
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
        self._update_info = info
        self.update_lbl.setText(f"Доступна новая версия {APP_NAME} {info['version']} (у вас {APP_VERSION}).")
        anim.slide_down(self.update_bar)
        if not silent:
            self.show_update_notes()

    def show_update_notes(self):
        info = self._update_info
        if not info:
            return
        items = "".join(f"<li>{n}</li>" for n in info["notes"]) or "<li>Исправления и улучшения.</li>"
        box = QMessageBox(self)
        box.setWindowTitle(APP_NAME)
        box.setIcon(QMessageBox.Information)
        box.setText(f"<b>Новая версия {info['version']}</b> (у вас {APP_VERSION})<ul>{items}</ul>")
        now = box.addButton("Установить сейчас", QMessageBox.AcceptRole)
        box.addButton("Позже", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is now:
            self.download_update()

    def download_update(self):
        info = self._update_info
        if not info or self._update_dlg:
            return
        if QMessageBox.question(
                self, APP_NAME, f"Установить версию {info['version']}?\n\nПрограмма скачает обновление, "
                                "закроется, в отдельном окне соберёт и установит новую версию (обычно 2–4 минуты, "
                                "в первый раз дольше) и откроется снова. Дела, шаблоны и настройки сохранятся."
        ) != QMessageBox.Yes:
            return
        if not self.maybe_save():
            return
        import threading, time
        dest = os.path.join(tempfile.gettempdir(), f"LegalHelper_{info['version']}_{int(time.time())}.zip")
        dlg = QProgressDialog("Скачиваю обновление…", "Отмена", 0, 0, self)
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
                UPD.download(info["zip"], dest, progress=lambda got, total: self.updateProgress.emit(got, total),
                             cancelled=lambda: self._update_cancel)
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
            QMessageBox.warning(self, APP_NAME, f"Не удалось скачать обновление.\n\n{err}\n\n"
                                                "Попробуйте позже: «Справка → Проверить обновления…».")
            return
        self.install_update(path, ask=False)

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

    def base_name(self):
        return Path(self.path).stem if self.path else "документ"

    def default_dir(self):
        if self.path:
            return str(Path(self.path).parent)
        docs = Path.home() / "Documents"
        return str(docs if docs.exists() else Path.home())

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
        return sorted(self.pages.row(it) for it in self.pages.selectedItems())

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
        self.redo_stack.clear()
        self.modified = True

    def _restore(self, data):
        self.doc = fitz.open("pdf", data) if data else fitz.open()

    def undo(self):
        if not self.undo_stack:
            self.msg("Нечего отменять")
            return False
        self.redo_stack.append(self.doc.tobytes() if self.doc.page_count else None)
        self._restore(self.undo_stack.pop())
        self.modified = True
        self.refresh_all()
        self.msg("Действие отменено")
        return True

    def redo(self):
        if not self.redo_stack:
            return
        self.undo_stack.append(self.doc.tobytes() if self.doc.page_count else None)
        self._restore(self.redo_stack.pop())
        self.refresh_all()

    def after_change(self, pages=None, keep_selection=None):
        self.modified = True
        if pages is None:
            self.refresh_all(keep_selection)
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
        sc = T.get("shadow", (0, 0, 0, 40))
        p.setPen(Qt.NoPen)
        for k, al in ((6, 0.18), (3, 0.35), (1, 0.6)):          # мягкая тень листа
            p.setBrush(QColor(sc[0], sc[1], sc[2], int(sc[3] * al)))
            p.drawRoundedRect(QRectF(x - k / 2, y + k / 2 + 1, w + k, h + k / 2), 2, 2)
        if img is not None:
            p.drawImage(QRectF(x, y, w, h), img)
        else:
            p.setBrush(QColor("#ffffff"))
            p.drawRect(QRectF(x, y, w, h))
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
        bw = max(24, p.fontMetrics().horizontalAdvance(label) + 14)
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

    def refresh_all(self, keep_selection=None):
        n = self.doc.page_count
        self.thumbs = [None] * n
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
            it.setToolTip(f"Страница {i + 1} — двойной щелчок для редактирования")
            it.setIcon(self.compose_icon(i))
        for i in keep_selection or []:
            if 0 <= i < n:
                lst.item(i).setSelected(True)
        lst.blockSignals(False)
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

    def load_some_thumbs(self):
        if self.busy:
            return
        n = len(self.thumbs)
        done = 0
        i = getattr(self, "_thumb_pos", 0)
        while i < n and done < 3:
            if self.thumbs[i] is None:
                try:
                    self.thumbs[i] = self.render_thumb(i)
                except Exception:
                    self.thumbs[i] = QImage()
                self.pages.item(i).setIcon(self.compose_icon(i))
                done += 1
            i += 1
        self._thumb_pos = i
        if i >= n:
            self.thumb_timer.stop()

    # ------------------------------------------------------------- files
    def password_prompt(self, name):
        pw, ok = QInputDialog.getText(self, "Пароль", f"Файл «{name}» защищён паролем.\nВведите пароль:",
                                      QLineEdit.Password)
        return pw if ok else None

    def load_file(self, p):
        """Файл любого поддерживаемого типа → fitz.Document (или None)."""
        ext = Path(p).suffix.lower()
        slow = ext in C.OFFICE_EXT or ext in C.HTML_EXT
        if slow:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            self.msg(f"Конвертирую {Path(p).name}…", 0)
            QApplication.processEvents()
        try:
            while True:
                try:
                    return C.open_as_pdf(p, self.password_prompt)
                except Exception as e:
                    if slow:
                        raise
                    raise RuntimeError(f"Не удалось открыть «{Path(p).name}»: {e}")
        except Exception as e:
            if slow:
                QApplication.restoreOverrideCursor()
                slow = False
            self.error(f"Файл «{Path(p).name}» не открыт", e)
            return None
        finally:
            if slow:
                QApplication.restoreOverrideCursor()
            self.statusBar().clearMessage()

    def maybe_save(self):
        if not self.modified or self.doc.page_count == 0:
            return True
        r = QMessageBox.question(self, APP_NAME, "Сохранить изменения в текущем документе?",
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

    def open_paths(self, paths, replace=False, insert_at=None):
        paths = [p for p in paths if p and os.path.isfile(p)]
        if not paths:
            return
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
        if replace or self.doc.page_count == 0:
            if replace:
                self.undo_stack.clear()
                self.redo_stack.clear()
            first_path, first = loaded[0]
            self.doc = first
            self.path = first_path if (len(loaded) == 1 and first_path.lower().endswith(".pdf")) else None
            self.modified = len(loaded) > 1 or not first_path.lower().endswith(".pdf")
            rest = loaded[1:]
        else:
            self.push_undo()
            rest = loaded
        pos = insert_at if insert_at is not None and 0 <= insert_at < self.doc.page_count else None
        new_sel = []
        for p, d in rest:
            start = pos if pos is not None else self.doc.page_count
            if pos is None:
                self.doc.insert_pdf(d)
            else:
                self.doc.insert_pdf(d, start_at=pos)
                pos += d.page_count
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
        self.refresh_all(new_sel)
        self.refresh_loose_list()
        self.update_title()
        self.msg(f"Открыто файлов: {len(loaded)}, страниц в документе: {self.doc.page_count}")

    def save(self):
        if not self.need_doc():
            return False
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
        self.path = p
        self.modified = False
        cid = self.ws[self.cur_ws].get("case_id")
        if cid:
            try:
                U.db().add_doc(cid, p)
                self.cases_page.refresh_docs_if(cid)
            except Exception:
                pass
        self.update_title()
        self.msg(f"Сохранено: {p}")
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
            self.cases_page.board_tab.shutdown()
        except Exception as ex:
            log_error("Сохранение дел при выходе", ex)
        U.sync_case_file(self.mode_cid or self.last_case)

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

    def sync_current_case(self):
        U.sync_case_file(self.mode_cid)

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
        """Вернуть программу, которая стояла до последнего обновления (update.bat сохраняет её копию)."""
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

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        paths = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        self.open_paths(paths)

    # ------------------------------------------------------------- page ops
    def on_reorder(self):
        order = [self.pages.item(i).data(Qt.UserRole) for i in range(self.pages.count())]
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
        self.doc.delete_pages(pages)
        self.after_change(keep_selection=[min(pages[0], self.doc.page_count - 1)])
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

    def open_editor(self, index=None, mode="text"):
        if not self.need_doc():
            return
        if index is None:
            sel = self.selected()
            index = sel[0] if sel else 0
        ed = PageEditor(self, index, mode)
        ed.exec()
        if ed.changed:
            self.after_change(keep_selection=[ed.index])

    def context_menu(self, pos):
        if not self.doc.page_count:
            return
        it = self.pages.itemAt(pos)
        if it and not it.isSelected():
            self.pages.clearSelection()
            it.setSelected(True)
        m = QMenu(self)
        m.addAction("✎ Редактировать страницу", lambda: self.open_editor())
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
        QTimer.singleShot(0, lambda: self.statusBar().setVisible(self.docarea.isVisible()))
        if self.mode_cid:
            self._mount(self.docarea, self.case_doc_slot)
            self._mount(self.calc_page, self.case_calc_slot)
        else:
            self._mount(self.docarea, self.loose_doc_slot)
            self._mount(self.calc_page, self.loose_calc_slot)

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
        self.toolbar.insertWidget(self.a_rl, b)
        self.toolbar.insertSeparator(self.a_rl)

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
        while tabs.count():
            tabs.removeTab(0)
        self.overview = U.OverviewTab(self)
        docs = QSplitter()
        docs.setChildrenCollapsible(False)
        # слева: «Документы» дела или «Комплект для подачи»; справа — рабочая область
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 8, 0, 0)
        lv.setSpacing(6)
        seg = QTabBar()
        seg.setDrawBase(False)
        seg.setExpanding(True)
        seg.addTab("📄  Документы")
        seg.addTab("📦  Комплект для подачи")
        lv.addWidget(seg)
        self.docs_mode = QStackedWidget()
        self.docs_mode.addWidget(cp.docs_widget)
        self.docs_mode.addWidget(cp.sub_tab)
        cp.docs_widget.show()
        cp.sub_tab.show()
        seg.currentChanged.connect(self.docs_mode.setCurrentIndex)
        seg.currentChanged.connect(lambda *_: anim.fade_in(self.docs_mode.currentWidget()))
        self.docs_seg = seg
        lv.addWidget(self.docs_mode, 1)
        dl = left
        dl.setMinimumWidth(360)
        docs.addWidget(dl)
        self.case_doc_slot = self._slot()
        docs.addWidget(self.case_doc_slot)
        docs.setStretchFactor(1, 1)
        docs.setSizes([380, 900])
        cp.l_docs.setColumnHidden(3, True)
        cp.l_docs.setColumnWidth(2, 128)
        prepare = U.PrepareTab(self, None)
        self.case_calc_slot = self._slot()
        order = [("overview", "Обзор", self.overview), ("docs", "Документы", docs), ("prepare", "Подготовить", prepare),
                 ("events", "Сроки и заседания", cp.events_tab), ("calc", "Расчёты", self.case_calc_slot),
                 ("board", "Карта дела", cp.board_tab), ("info", "Сведения о деле", by_name.get("Сведения")),
                 ("laws", "Нормы права", cp.laws_tab), ("money", "Время и оплата", by_name.get("Время и оплата")),
                 ("quotes", "Выписки", by_name.get("Выписки"))]
        self.case_tab_keys = {}
        for key, title, w in order:
            self.case_tab_keys[key] = tabs.addTab(w, title)
        self.hidden_tabs = [self.case_tab_keys[k] for k in ("info", "laws", "money", "quotes")]
        for i in self.hidden_tabs:
            tabs.setTabVisible(i, False)
        more = QToolButton()
        more.setObjectName("moretabs")
        more.setText("Ещё ▾")
        more.setPopupMode(QToolButton.InstantPopup)
        mm = QMenu(more)
        for key, title in (("info", "Сведения о деле"), ("laws", "Нормы права"), ("money", "Время и оплата"),
                           ("quotes", "Выписки")):
            mm.addAction(title, lambda k=key: self.open_case_tab(k))
        mm.addSeparator()
        mm.addAction("📁 Открыть папку дела", lambda: U.open_case_folder(self.mode_cid))
        mm.addAction("📦 Собрать все файлы в папку дела", lambda: U.collect_case_files(self, self.mode_cid))
        more.setMenu(mm)
        tabs.setCornerWidget(more, Qt.TopRightCorner)
        tabs.currentChanged.connect(self._on_case_tab)
        tabs.currentChanged.connect(lambda *_: anim.fade_in(tabs.currentWidget()))

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
        self.home_page.refresh()
        self.stack.setCurrentWidget(self.home_page)

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
                anim.fade_in(self.cases_page.tabs.currentWidget())
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
        """Показать документ этого дела: открытый ранее или пустой лист."""
        if self.ws[self.cur_ws].get("case_id") == cid:
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

    def set_banner(self, text):
        was = self.banner.isVisible()
        self.banner.setText(text)
        if text and not was and self.isVisible():
            anim.slide_down(self.banner)
        else:
            self.banner.setVisible(bool(text))

    def refresh_cases(self):
        if self.cases_page:
            self.cases_page.reload()
            try:
                self.cases_page.reload_upcoming()
            except Exception:
                pass
            if self.last_case:
                self.cases_page.select_case(self.last_case)

    def open_external(self, path, page=0, cid=None):
        if not os.path.exists(path):
            return QMessageBox.warning(self, APP_NAME, f"Файл не найден:\n{path}")
        if os.path.splitext(path)[1].lower() in EXTERNAL_EXT:
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))
            return
        target = cid if cid is not None else self.mode_cid
        if target:
            self.enter_case(target)
        else:
            self.enter_loose()
        self.open_paths([path], replace=True)
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
        vis = not self.navigator.isVisible()
        self.navigator.setVisible(vis)
        self.a_nav.setChecked(vis)
        settings().setValue("nav_visible", "true" if vis else "false")
        if vis:
            self.navigator.refresh()

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

    def tool_merge(self):
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
        self._office("Документы Word", "Word (*.doc *.docx *.rtf *.odt)")

    def tool_ppt2pdf(self):
        self._office("Презентации", "PowerPoint (*.ppt *.pptx *.pps *.ppsx *.odp)")

    def tool_xls2pdf(self):
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
QToolBar QToolButton {{ padding: 6px 11px; border-radius: 8px; color: {A}; }}
QToolBar QToolButton:hover {{ background: {t['fill']}; }}
QToolBar QToolButton:pressed {{ background: {t['fill_hover']}; }}
QToolBar QToolButton:disabled {{ color: {t['disabled']}; }}
QToolBar QToolButton#tbprimary {{ background: {A}; color: white; font-weight: 600; padding: 6px 16px; border-radius: 9px; }}
QToolBar QLabel {{ color: {t['muted']}; }}
QToolBar QLabel#doctitle {{ color: {t['text']}; font-family: "{S}"; font-size: 13pt; font-weight: 600; padding-right: 14px; }}

/* уведомления сверху — скруглённые плашки */
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
QTreeWidget::item, QTreeView::item {{ padding: 3px 2px; }}
QTableWidget::item:selected, QTreeWidget::item:selected, QListWidget::item:selected {{ background: {t['accent_soft']}; color: {t['text']}; }}
QTreeView::branch {{ background: transparent; }}
QTreeView::branch:selected {{ background: {t['accent_soft']}; }}
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
    app.setStyleSheet(make_style(t))
    return name


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


def main():
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
    anim.ENABLED = str(settings().value("animations", "1")) != "0"
    splash = None
    if anim.ENABLED:                            # заставка, пока открывается главное окно
        splash = anim.Splash(QIcon(resource("app.ico")).pixmap(256, 256), APP_NAME, APP_VERSION,
                             dark=T.get("name") == "dark")
        splash.start()
        anim.wait(450)
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
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
