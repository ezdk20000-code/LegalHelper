# -*- coding: utf-8 -*-
"""
Масштаб всей программы — как в браузере: 50–200 %. Увеличивается всё сразу: буквы, кнопки, значки, отступы.
Qt умеет так масштабировать окно только при запуске (переменная QT_SCALE_FACTOR), поэтому после выбора
программа сама перезапускается за пару секунд и открывается на том же месте (см. MainWindow.save_place).
"""
import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame, QGridLayout)

STEPS = [50, 67, 75, 80, 90, 100, 110, 125, 150, 175, 200]
KEY = "ui_zoom"


def get_zoom(settings):
    try:
        z = int(float(settings().value(KEY, 100) or 100))
    except (TypeError, ValueError):
        z = 100
    return min(STEPS, key=lambda s: abs(s - z))


def apply_env(settings):
    """До создания QApplication: выставить масштаб. Свою переменную помечаем, чтобы при перезапуске
    (дочерний процесс наследует окружение) брать новое значение, а не старое."""
    if "QT_SCALE_FACTOR" in os.environ and not os.environ.get("LH_ZOOM"):
        return                                   # масштаб задан снаружи — не трогаем
    z = get_zoom(settings)
    if z == 100:
        os.environ.pop("QT_SCALE_FACTOR", None)
        os.environ.pop("LH_ZOOM", None)
    else:
        os.environ["QT_SCALE_FACTOR"] = f"{z / 100:.2f}"
        os.environ["LH_ZOOM"] = "1"


def step(z, d):
    i = min(range(len(STEPS)), key=lambda k: abs(STEPS[k] - z))
    return STEPS[max(0, min(len(STEPS) - 1, i + d))]


class ZoomDialog(QDialog):
    """Выбор масштаба: −/+, частые значения, образец текста; «Применить» перезапускает программу."""

    def __init__(self, parent, current, start=None):
        super().__init__(parent)
        self.setObjectName("tooldlg")
        self.setWindowTitle("Масштаб программы")
        self.current = current
        self.value = start if start is not None else current
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        body = QVBoxLayout()
        body.setContentsMargins(24, 20, 24, 16)
        body.setSpacing(12)
        t = QLabel("🔍  Масштаб программы")
        t.setObjectName("dlgtitle")
        body.addWidget(t)
        sub = QLabel("Как в браузере: крупнее или мельче становится всё — текст, кнопки, значки и отступы. "
                     "Быстро: Ctrl+Shift+плюс / минус.")
        sub.setObjectName("dlgsub")
        sub.setWordWrap(True)
        body.addWidget(sub)
        row = QHBoxLayout()
        row.setSpacing(10)
        self.b_minus = QPushButton("−")
        self.b_plus = QPushButton("+")
        for b in (self.b_minus, self.b_plus):
            b.setFixedSize(44, 40)
            f = b.font()
            f.setPointSizeF(f.pointSizeF() * 1.5)
            f.setBold(True)
            b.setFont(f)
            b.setCursor(Qt.PointingHandCursor)
        self.b_minus.clicked.connect(lambda: self.set_value(step(self.value, -1)))
        self.b_plus.clicked.connect(lambda: self.set_value(step(self.value, 1)))
        self.big = QLabel()
        self.big.setAlignment(Qt.AlignCenter)
        f = self.big.font()
        f.setPointSizeF(f.pointSizeF() * 2.2)
        f.setBold(True)
        self.big.setFont(f)
        self.big.setMinimumWidth(130)
        row.addStretch(1)
        row.addWidget(self.b_minus)
        row.addWidget(self.big)
        row.addWidget(self.b_plus)
        row.addStretch(1)
        body.addLayout(row)
        grid = QGridLayout()
        grid.setSpacing(6)
        self.chips = {}
        for i, z in enumerate(STEPS):
            b = QPushButton(f"{z}%")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, z=z: self.set_value(z))
            grid.addWidget(b, i // 6, i % 6)
            self.chips[z] = b
        body.addLayout(grid)
        self.sample = QLabel("Образец: «Предварительное заседание — 15 октября, 10:30»")
        self.sample.setAlignment(Qt.AlignCenter)
        self.sample.setMinimumHeight(56)
        self.sample.setWordWrap(True)
        body.addWidget(self.sample)
        self.note = QLabel()
        self.note.setObjectName("dlgsub")
        self.note.setWordWrap(True)
        body.addWidget(self.note)
        v.addLayout(body)
        foot = QFrame()
        foot.setObjectName("dlgfoot")
        fh = QHBoxLayout(foot)
        fh.setContentsMargins(24, 12, 24, 12)
        b_reset = QPushButton("Сбросить (100%)")
        b_reset.clicked.connect(lambda: self.set_value(100))
        fh.addWidget(b_reset)
        fh.addStretch(1)
        cancel = QPushButton("Отмена")
        cancel.clicked.connect(self.reject)
        self.ok = QPushButton("Применить")
        self.ok.setObjectName("primary")
        self.ok.setDefault(True)
        self.ok.clicked.connect(self.accept)
        fh.addWidget(cancel)
        fh.addWidget(self.ok)
        v.addWidget(foot)
        self._base_pt = self.sample.font().pointSizeF()
        self.setMinimumWidth(560)
        self.set_value(self.value)

    def set_value(self, z):
        self.value = z
        self.big.setText(f"{z}%")
        for k, b in self.chips.items():
            b.setChecked(k == z)
        self.b_minus.setEnabled(z > STEPS[0])
        self.b_plus.setEnabled(z < STEPS[-1])
        f = QFont(self.sample.font())
        f.setPointSizeF(self._base_pt * z / max(self.current, 1))
        self.sample.setFont(f)
        same = z == self.current
        self.ok.setEnabled(not same)
        self.ok.setText("Применить" if same else f"Применить {z}%")
        self.note.setText("Сейчас стоит этот масштаб." if same else
                          "Программа перезапустится на 2–3 секунды и откроется там же, где вы сейчас. "
                          "Несохранённые документы она предложит сохранить.")

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Plus, Qt.Key_Equal):
            return self.set_value(step(self.value, 1))
        if e.key() in (Qt.Key_Minus, Qt.Key_Underscore):
            return self.set_value(step(self.value, -1))
        if e.key() == Qt.Key_0:
            return self.set_value(100)
        super().keyPressEvent(e)
