# -*- coding: utf-8 -*-
"""
PDF Мастер — настольный редактор PDF.
Запуск:  python pdf_master.py [файлы...]
"""
import os
import sys
import tempfile
import traceback
import subprocess
from pathlib import Path

import pymupdf as fitz
from PySide6.QtCore import Qt, QSize, QTimer, Signal, QPointF, QRectF, QUrl, QByteArray, QBuffer, QIODevice
from PySide6.QtGui import (QAction, QActionGroup, QIcon, QImage, QPixmap, QPainter, QPen, QColor,
                           QFont, QKeySequence, QDesktopServices, QPainterPath, QPalette, QFontDatabase)
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QListWidget, QListWidgetItem, QListView, QAbstractItemView,
    QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QPushButton, QToolBar, QFileDialog, QMessageBox,
    QInputDialog, QLineEdit, QDialog, QDialogButtonBox, QSpinBox, QDoubleSpinBox, QComboBox,
    QCheckBox, QPlainTextEdit, QColorDialog, QProgressDialog, QTreeWidget, QTreeWidgetItem, QSplitter,
    QScrollArea, QMenu, QSlider, QTabWidget, QTableWidget, QTableWidgetItem, QHeaderView, QToolButton,
    QSizePolicy, QStyle, QFrame, QRadioButton, QButtonGroup)

import pdf_core as C

APP_NAME = "PDF Мастер"
APP_VERSION = "1.0"
ACCENT = "#d9363e"
FAILED = object()
PDF_FILTER = "PDF (*.pdf)"
OPEN_FILTER = ("Все поддерживаемые (*.pdf *.jpg *.jpeg *.png *.bmp *.gif *.tif *.tiff *.webp "
               "*.doc *.docx *.rtf *.odt *.xls *.xlsx *.ppt *.pptx *.html *.htm *.xps *.epub *.fb2 *.svg *.txt);;"
               "PDF (*.pdf);;Изображения (*.jpg *.jpeg *.png *.bmp *.gif *.tif *.tiff *.webp);;"
               "Документы Office (*.doc *.docx *.rtf *.odt *.xls *.xlsx *.ppt *.pptx);;Все файлы (*)")
IMG_FILTER = "Изображения (*.jpg *.jpeg *.png *.bmp *.gif *.tif *.tiff *.webp)"


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


class OptionsDialog(QDialog):
    """Универсальный диалог параметров.
    fields: (ключ, подпись, тип, значение_по_умолчанию, доп)"""

    def __init__(self, parent, title, fields, note=None, ok_text="Выполнить"):
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
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText(ok_text)
        bb.button(QDialogButtonBox.Cancel).setText("Отмена")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
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
        elif kind in ("text", "password", "pages"):
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
    def ask(parent, title, fields, note=None, ok_text="Выполнить"):
        d = OptionsDialog(parent, title, fields, note, ok_text)
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
            p.setPen(QColor("#8a8f98"))
            f = p.font()
            f.setPointSize(13)
            p.setFont(f)
            p.drawText(self.viewport().rect(), Qt.AlignCenter,
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
        self.color = QColor(ACCENT)
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
    ("Организация", [
        ("merge", "Объединить PDF", "Добавить PDF-файлы и картинки в конец документа. Порядок меняется перетаскиванием"),
        ("organize", "Организовать страницы", "Перетаскивайте миниатюры мышью, удаляйте и добавляйте страницы"),
        ("split", "Разделить PDF", "Разбить документ на несколько файлов"),
        ("rotate", "Повернуть PDF", "Повернуть все или выбранные страницы"),
        ("delete", "Удалить страницы", "Удалить страницы по номерам"),
        ("extract", "Извлечь страницы", "Сохранить выбранные страницы в новый файл"),
        ("blank", "Вставить пустую страницу", "Добавить чистый лист после выбранной страницы"),
        ("reverse", "Обратный порядок", "Развернуть порядок страниц"),
    ]),
    ("Оптимизация", [
        ("compress", "Сжать PDF", "Уменьшить размер файла"),
        ("repair", "Восстановить PDF", "Починить повреждённый файл"),
        ("ocr", "OCR — распознать текст", "Сделать скан доступным для поиска и копирования"),
        ("pdfa", "PDF в PDF/A", "Архивный формат (нужен Ghostscript)"),
    ]),
    ("Конвертировать в PDF", [
        ("img2pdf", "JPG / картинки в PDF", "Собрать PDF из изображений"),
        ("word2pdf", "Word в PDF", "DOC, DOCX, RTF, ODT (нужен MS Office или LibreOffice)"),
        ("ppt2pdf", "PowerPoint в PDF", "PPT, PPTX (нужен MS Office или LibreOffice)"),
        ("xls2pdf", "Excel в PDF", "XLS, XLSX (нужен MS Office или LibreOffice)"),
        ("html2pdf", "HTML / сайт в PDF", "Страница сайта или HTML-файл (через Edge/Chrome)"),
    ]),
    ("Конвертировать из PDF", [
        ("pdf2word", "PDF в Word", "Редактируемый DOCX"),
        ("pdf2excel", "PDF в Excel", "Таблицы из PDF в XLSX"),
        ("pdf2ppt", "PDF в PowerPoint", "Каждая страница — слайд"),
        ("pdf2jpg", "PDF в JPG / PNG", "Страницы в картинки или извлечь все изображения"),
        ("pdf2md", "PDF в Markdown", "Для заметок (Obsidian и т.п.) и нейросетей"),
        ("pdf2txt", "PDF в текст (TXT)", "Весь текст документа"),
    ]),
    ("Редактирование", [
        ("edit", "Редактировать PDF", "Текст, картинки, фигуры, пометки, ссылки"),
        ("sign", "Подписать PDF", "Нарисовать, напечатать или вставить скан подписи/печати"),
        ("watermark", "Водяной знак", "Текст или картинка поверх страниц"),
        ("numbers", "Номера страниц", "Пронумеровать страницы"),
        ("crop", "Обрезка PDF", "Обрезать поля страниц"),
        ("redact", "Скрыть данные", "Найти и безвозвратно закрасить текст, e-mail, телефоны"),
        ("highlight", "Найти и выделить", "Подсветить все вхождения слов"),
        ("forms", "PDF-формы", "Заполнить поля формы"),
        ("meta", "Свойства документа", "Название, автор, тема, ключевые слова"),
    ]),
    ("Безопасность и сравнение", [
        ("protect", "Защитить паролем", "Зашифровать PDF (AES-256)"),
        ("unlock", "Снять пароль", "Открыть защищённый PDF и сохранить без пароля"),
        ("compare", "Сравнить PDF", "Найти отличия между двумя версиями"),
    ]),
]


class MainWindow(QMainWindow):
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
        self._build()
        self.update_title()

    # ------------------------------------------------------------------ UI
    def _build(self):
        tb = QToolBar("Главная")
        tb.setMovable(False)
        tb.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        tb.setIconSize(QSize(18, 18))
        self.addToolBar(tb)
        st = self.style()

        def act(text, slot, shortcut=None, icon=None, tip=None):
            a = QAction(text, self)
            if icon is not None:
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
        self.a_rl = act("↺ Влево", lambda: self.rotate_selected(-90), "Ctrl+L", tip="Повернуть влево")
        self.a_rr = act("↻ Вправо", lambda: self.rotate_selected(90), "Ctrl+R", tip="Повернуть вправо")
        self.a_del = act("Удалить", self.delete_selected, QKeySequence.Delete, QStyle.SP_TrashIcon,
                         "Удалить выбранные страницы")
        self.a_dup = act("Дублировать", self.duplicate_selected, "Ctrl+D")
        self.a_blank = act("Пустая страница", self.insert_blank)
        self.a_extract = act("Извлечь", self.extract_selected, "Ctrl+E", tip="Сохранить выбранные страницы в новый файл")
        self.a_edit = act("✎ Редактировать", lambda: self.open_editor(), "Ctrl+Return",
                          tip="Открыть страницу в редакторе")
        self.a_selall = act("Выделить всё", lambda: self.pages.selectAll(), QKeySequence.SelectAll)
        for a in (self.a_open, self.a_add, self.a_save):
            tb.addAction(a)
        tb.addAction(self.a_saveas)
        mb = self.menuBar()
        mf = mb.addMenu("Файл")
        for a in (self.a_open, self.a_add, self.a_save, self.a_saveas):
            mf.addAction(a)
        mf.addSeparator()
        mf.addAction("Новый (пустой) документ", self.new_doc)
        mf.addSeparator()
        mf.addAction("Выход", self.close)
        me = mb.addMenu("Правка")
        for a in (self.a_undo, self.a_redo, self.a_selall):
            me.addAction(a)
        me.addSeparator()
        for a in (self.a_rl, self.a_rr, self.a_del, self.a_dup, self.a_blank, self.a_extract, self.a_edit):
            me.addAction(a)
        mt = mb.addMenu("Инструменты")
        for cat, items in TOOLS:
            sub = mt.addMenu(cat)
            for key, label, _tip in items:
                sub.addAction(label, getattr(self, "tool_" + key))
        mh = mb.addMenu("Справка")
        mh.addAction("Как пользоваться", self.tool_organize)
        mh.addAction("О программе", lambda: QMessageBox.about(
            self, APP_NAME, f"<b>{APP_NAME}</b> {APP_VERSION}<br>Настольный редактор PDF.<br><br>"
            "Работает без интернета, файлы никуда не отправляются.<br>"
            "Основано на PyMuPDF (MuPDF), Qt (PySide6), pdf2docx, openpyxl, python-pptx."))
        tb.addSeparator()
        for a in (self.a_undo, self.a_redo):
            tb.addAction(a)
            tb.widgetForAction(a).setToolButtonStyle(Qt.ToolButtonIconOnly)
        tb.addSeparator()
        for a in (self.a_rl, self.a_rr, self.a_del, self.a_dup, self.a_blank, self.a_extract, self.a_edit):
            tb.addAction(a)
        self.addAction(self.a_selall)
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        tb.addWidget(spacer)
        tb.addWidget(QLabel("Размер миниатюр "))
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(80, 320)
        self.slider.setValue(self.thumb_w)
        self.slider.setFixedWidth(130)
        self.slider.valueChanged.connect(self.set_thumb_size)
        tb.addWidget(self.slider)

        # левая панель инструментов
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setIndentation(10)
        self.tree.setObjectName("tools")
        bold = QFont()
        bold.setBold(True)
        for cat, items in TOOLS:
            top = QTreeWidgetItem([cat])
            top.setFont(0, bold)
            top.setFlags(Qt.ItemIsEnabled)
            self.tree.addTopLevelItem(top)
            for key, label, tip in items:
                it = QTreeWidgetItem([label])
                it.setData(0, Qt.UserRole, key)
                it.setToolTip(0, tip)
                top.addChild(it)
            top.setExpanded(True)
        self.tree.itemClicked.connect(self.on_tool)
        self.tree.setMinimumWidth(240)

        self.pages = PageList()
        self.pages.orderChanged.connect(self.on_reorder)
        self.pages.filesDropped.connect(lambda paths, idx: self.open_paths(paths, insert_at=idx))
        self.pages.itemDoubleClicked.connect(lambda it: self.open_editor(self.pages.row(it)))
        self.pages.setContextMenuPolicy(Qt.CustomContextMenu)
        self.pages.customContextMenuRequested.connect(self.context_menu)
        self.pages.itemSelectionChanged.connect(self.update_status)

        split = QSplitter()
        split.addWidget(self.tree)
        split.addWidget(self.pages)
        split.setStretchFactor(1, 1)
        split.setSizes([260, 1100])
        self.setCentralWidget(split)
        self.status_lbl = QLabel()
        self.statusBar().addPermanentWidget(self.status_lbl)
        self.apply_thumb_geometry()

    # ------------------------------------------------------------- helpers
    def update_title(self):
        name = Path(self.path).name if self.path else ("Новый документ" if self.doc.page_count else "")
        star = " *" if self.modified else ""
        self.setWindowTitle(f"{name}{star} — {APP_NAME}" if name else APP_NAME)
        self.update_status()

    def update_status(self):
        n = self.doc.page_count
        sel = len(self.pages.selectedItems())
        self.status_lbl.setText(f"Страниц: {n}" + (f"   ·   выбрано: {sel}" if sel else "") + "  ")

    def msg(self, text, ms=6000):
        self.statusBar().showMessage(text, ms)

    def error(self, title, exc):
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle(APP_NAME)
        box.setText(f"{title}\n\n{exc}")
        box.setDetailedText("".join(traceback.format_exception(type(exc), exc, exc.__traceback__)))
        box.exec()

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
        s = self.cell_size()
        dpr = self.devicePixelRatioF()
        pm = QPixmap(int(s.width() * dpr), int(s.height() * dpr))
        pm.setDevicePixelRatio(dpr)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        img = self.thumbs[i] if i < len(self.thumbs) else None
        area_h = s.height() - 26
        if img is not None:
            w, h = img.width() / dpr, img.height() / dpr
        else:
            r = self.doc[i].rect
            z = min(self.thumb_w / r.width, self.thumb_w * 1.42 / r.height)
            w, h = r.width * z, r.height * z
        x, y = (s.width() - w) / 2, (area_h - h) / 2 + 4
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 35))
        p.drawRect(QRectF(x + 2, y + 3, w, h))
        if img is not None:
            p.drawImage(QRectF(x, y, w, h), img)
        else:
            p.setBrush(QColor("#ffffff"))
            p.drawRect(QRectF(x, y, w, h))
        p.setPen(QPen(QColor("#c9ccd1"), 1))
        p.setBrush(Qt.NoBrush)
        p.drawRect(QRectF(x, y, w, h))
        p.setPen(QColor("#3a3f47"))
        f = QFont()
        f.setPointSize(9)
        p.setFont(f)
        p.drawText(QRectF(0, s.height() - 22, s.width(), 20), Qt.AlignCenter, str(i + 1))
        p.end()
        icon = QIcon()
        icon.addPixmap(pm, QIcon.Normal)
        icon.addPixmap(pm, QIcon.Selected)   # без синей подкраски выделенной страницы
        return icon

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
        if self.maybe_save():
            self.doc, self.path, self.modified = fitz.open(), None, False
            self.undo_stack.clear()
            self.redo_stack.clear()
            self.refresh_all()

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
        if replace and not self.maybe_save():
            return
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
        self.refresh_all(new_sel)
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
        self.update_title()
        self.msg(f"Сохранено: {p}")
        return True

    def closeEvent(self, e):
        if self.maybe_save():
            e.accept()
        else:
            e.ignore()

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
    def on_tool(self, item, _col=0):
        key = item.data(0, Qt.UserRole)
        if not key:
            return
        fn = getattr(self, "tool_" + key, None)
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
        self.insert_blank()

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
            ("mode", "Размер страницы", "combo", None, C.PAGE_MODES),
            ("margin", "Поля, мм", "int", 0, (0, 50)),
            ("where", "Результат", "combo", None, ["Добавить в текущий документ", "Новый документ"]),
        ], note=f"Выбрано изображений: {len(paths)}. Порядок потом можно поменять перетаскиванием.",
            ok_text="Создать")
        if not v:
            return
        res = self.run("Создание PDF…", C.images_to_pdf, sorted(paths), v["mode"], v["margin"])
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
STYLE = f"""
QMainWindow, QDialog {{ background: #f4f5f7; }}
QToolBar {{ background: #ffffff; border: none; border-bottom: 1px solid #e1e3e8; padding: 4px; spacing: 2px; }}
QToolBar QToolButton {{ padding: 5px 9px; border-radius: 6px; color: #23272e; }}
QToolBar QToolButton:hover {{ background: #f1f2f5; }}
QToolBar QToolButton:pressed {{ background: #e6e8ec; }}
QTreeWidget#tools {{ background: #ffffff; border: none; border-right: 1px solid #e1e3e8; font-size: 10pt; padding: 6px 4px; }}
QTreeWidget#tools::item {{ padding: 5px 4px; border-radius: 6px; }}
QTreeWidget#tools::item:hover {{ background: #fdecec; color: {ACCENT}; }}
QTreeWidget#tools::item:selected {{ background: {ACCENT}; color: white; }}
QListWidget#pages {{ background: #eceef1; border: none; padding: 10px; }}
QListWidget#pages::item {{ border-radius: 8px; }}
QListWidget#pages::item:selected {{ background: rgba(217,54,62,0.18); border: 2px solid {ACCENT}; }}
QListWidget#pages::item:hover {{ background: rgba(0,0,0,0.05); }}
QPushButton {{ padding: 6px 14px; border: 1px solid #c9ccd3; border-radius: 6px; background: #ffffff; }}
QPushButton:hover {{ border-color: {ACCENT}; }}
QPushButton#primary, QDialogButtonBox QPushButton:default {{ background: {ACCENT}; color: white; border-color: {ACCENT}; }}
QToolButton#mode {{ text-align: left; padding: 7px 10px; border-radius: 6px; border: 1px solid transparent; background: #ffffff; }}
QToolButton#mode:hover {{ border-color: #e5b3b5; }}
QToolButton#mode:checked {{ background: {ACCENT}; color: white; }}
QLabel#note {{ background: #fff7e6; border: 1px solid #f3d9a4; border-radius: 6px; padding: 8px; color: #5a4a1f; }}
QLabel#hint {{ color: #555; font-style: italic; }}
QScrollArea#canvasArea {{ background: #6b7078; border: none; }}
QStatusBar {{ background: #ffffff; border-top: 1px solid #e1e3e8; }}
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit {{ padding: 4px 6px; border: 1px solid #c9ccd3; border-radius: 5px; background: white; }}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus, QPlainTextEdit:focus {{ border-color: {ACCENT}; }}
"""


def main():
    if C.IS_WIN:
        try:  # своя иконка на панели задач
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("PDFMaster.App.1")
        except Exception:
            pass
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setStyle("Fusion")
    pal = app.palette()
    pal.setColor(QPalette.Highlight, QColor(ACCENT))
    app.setPalette(pal)
    f = app.font()
    f.setPointSize(10)
    app.setFont(f)
    app.setStyleSheet(STYLE)
    w = MainWindow()
    w.show()
    files = [a for a in sys.argv[1:] if os.path.isfile(a)]
    if files:
        QTimer.singleShot(100, lambda: w.open_paths(files, replace=True))
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
