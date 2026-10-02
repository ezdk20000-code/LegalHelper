# -*- coding: utf-8 -*-
"""
Современный вид стандартных окон: сообщения и вопросы (QMessageBox) — с цветным значком-кружком,
крупным заголовком, пояснением ниже и кнопками по-русски («Да», «Нет», «Отмена»), а не серое окно
из Windows 98 с «Yes / No». Подключается один раз при запуске (install), остальной код не меняется.
"""
from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QPixmap, QPainter, QColor, QFont
from PySide6.QtWidgets import QMessageBox, QApplication, QDialogButtonBox

_theme = {"accent": "#007aff", "danger": "#ff3b30"}

BUTTON_RU = {
    QMessageBox.Yes: "Да", QMessageBox.No: "Нет", QMessageBox.Ok: "ОК", QMessageBox.Cancel: "Отмена",
    QMessageBox.Save: "Сохранить", QMessageBox.Discard: "Не сохранять", QMessageBox.Close: "Закрыть",
    QMessageBox.Retry: "Повторить", QMessageBox.Ignore: "Пропустить", QMessageBox.Abort: "Прервать",
    QMessageBox.YesToAll: "Да для всех", QMessageBox.NoToAll: "Нет для всех", QMessageBox.Apply: "Применить",
    QMessageBox.Open: "Открыть", QMessageBox.Help: "Справка", QMessageBox.Reset: "Сбросить",
}
DIALOG_RU = {QDialogButtonBox.Ok: "ОК", QDialogButtonBox.Cancel: "Отмена", QDialogButtonBox.Yes: "Да",
             QDialogButtonBox.No: "Нет", QDialogButtonBox.Close: "Закрыть", QDialogButtonBox.Save: "Сохранить",
             QDialogButtonBox.Apply: "Применить", QDialogButtonBox.Discard: "Не сохранять"}


def set_theme(t):
    _theme.update(t)


def badge(glyph, color, size=44, soft=True):
    """Значок-кружок: мягкий цветной круг и знак по центру (как в современных программах)."""
    dpr = 2.0
    pm = QPixmap(int(size * dpr), int(size * dpr))
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.TextAntialiasing)
    c = QColor(color)
    bg = QColor(c)
    bg.setAlpha(38 if soft else 255)
    p.setPen(Qt.NoPen)
    p.setBrush(bg)
    p.drawEllipse(QRectF(0, 0, size, size))
    p.setBrush(c)
    inner = size * 0.62
    p.drawEllipse(QRectF((size - inner) / 2, (size - inner) / 2, inner, inner))
    f = QFont()
    f.setBold(True)
    f.setPixelSize(int(size * 0.36))
    p.setFont(f)
    p.setPen(QColor("#ffffff"))
    p.drawText(QRectF(0, 0, size, size), Qt.AlignCenter, glyph)
    p.end()
    return pm


def emoji_tile(emoji, color, size=48):
    """Плитка со значком для заголовков окон инструментов: скруглённый квадрат цвета акцента и эмодзи."""
    dpr = 2.0
    pm = QPixmap(int(size * dpr), int(size * dpr))
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    c = QColor(color)
    c.setAlpha(36)
    p.setPen(Qt.NoPen)
    p.setBrush(c)
    p.drawRoundedRect(QRectF(0, 0, size, size), size * 0.28, size * 0.28)
    f = QFont()
    f.setPixelSize(int(size * 0.5))
    p.setFont(f)
    p.setPen(QColor(color))
    p.drawText(QRectF(0, 0, size, size), Qt.AlignCenter, emoji)
    p.end()
    return pm


def _icon_for(kind):
    if kind == QMessageBox.Question:
        return badge("?", _theme["accent"])
    if kind == QMessageBox.Warning:
        return badge("!", "#ff9500")
    if kind == QMessageBox.Critical:
        return badge("✕", _theme.get("danger", "#ff3b30"))
    if kind == QMessageBox.Information:
        return badge("i", _theme["accent"])
    return None


def modernize(box):
    """Привести окно сообщения к новому виду (можно вызывать повторно)."""
    if box.property("modern"):
        return box
    box.setProperty("modern", True)
    box.setObjectName("mbox")
    pm = _icon_for(box.icon())
    if pm is not None:
        box.setIconPixmap(pm)
    text = box.text() or ""
    # «Заголовок\n\nподробности» → крупный заголовок и пояснение ниже серым
    if box.textFormat() != Qt.RichText and not box.informativeText() and "\n\n" in text:
        head, rest = text.split("\n\n", 1)
        if 0 < len(head) <= 140 and not head.lstrip().startswith("•"):
            box.setText(head)
            box.setInformativeText(rest)
    if box.informativeText():
        box.setProperty("split", True)
    for sb, ru in BUTTON_RU.items():
        b = box.button(sb)
        if b is not None and b.text().replace("&", "").lower() in (_en(sb), ""):
            b.setText(ru)
    for b in box.buttons():
        b.setCursor(Qt.PointingHandCursor)
        b.setMinimumWidth(max(96, b.sizeHint().width() + 16))
    return box


def _en(sb):
    return {QMessageBox.Yes: "yes", QMessageBox.No: "no", QMessageBox.Ok: "ok", QMessageBox.Cancel: "cancel",
            QMessageBox.Save: "save", QMessageBox.Discard: "discard", QMessageBox.Close: "close",
            QMessageBox.Retry: "retry", QMessageBox.Ignore: "ignore", QMessageBox.Abort: "abort",
            QMessageBox.YesToAll: "yes to all", QMessageBox.NoToAll: "no to all", QMessageBox.Apply: "apply",
            QMessageBox.Open: "open", QMessageBox.Help: "help", QMessageBox.Reset: "reset"}.get(sb, "")


def russify(bb):
    """Кнопки QDialogButtonBox по-русски, если текст оставлен английским по умолчанию."""
    for sb, ru in DIALOG_RU.items():
        b = bb.button(sb)
        if b is not None and b.text().replace("&", "").lower() in ("ok", "cancel", "yes", "no", "close", "save",
                                                                    "apply", "discard"):
            b.setText(ru)


def stylesheet(t):
    A = t["accent"]
    return f"""
QMessageBox#mbox {{ background: {t['panel']}; }}
QMessageBox#mbox QLabel#qt_msgbox_label {{ font-size: 10.5pt; min-width: 320px; padding: 4px 6px 2px 4px; }}
QMessageBox#mbox[split="true"] QLabel#qt_msgbox_label {{ font-size: 11.5pt; font-weight: 600; }}
QMessageBox#mbox QLabel#qt_msgbox_informativelabel {{ color: {t['muted']}; font-size: 9.5pt; padding: 0 6px 6px 4px; }}
QMessageBox#mbox QLabel#qt_msgboxex_icon_label {{ padding: 4px 10px 0 4px; }}
QMessageBox#mbox QPushButton {{ padding: 8px 18px; font-weight: 600; }}
QMessageBox#mbox QPushButton:default {{ background: {A}; color: white; }}
QDialogButtonBox QPushButton {{ font-weight: 600; padding: 8px 18px; min-height: 18px; }}
"""


def _static(kind, default_buttons):
    def f(parent, title, text, buttons=default_buttons, defaultButton=QMessageBox.NoButton):
        box = QMessageBox(kind, title, text, buttons, parent)
        if defaultButton != QMessageBox.NoButton:
            box.setDefaultButton(defaultButton)
        modernize(box)
        r = box.exec()
        clicked = box.clickedButton()
        sb = box.standardButton(clicked) if clicked is not None else QMessageBox.NoButton
        if sb == QMessageBox.NoButton and isinstance(r, int) and r:
            return QMessageBox.StandardButton(r)
        return sb
    return staticmethod(f)


def install(theme=None):
    """Подменить стандартные окна сообщений на новый вид (вызвать один раз при запуске)."""
    if theme:
        set_theme(theme)
    if getattr(QMessageBox, "_modern_installed", False):
        return
    QMessageBox._modern_installed = True
    orig_exec = QMessageBox.exec

    def exec_(self, *a):
        modernize(self)
        return orig_exec(self, *a)
    QMessageBox.exec = exec_
    QMessageBox.information = _static(QMessageBox.Information, QMessageBox.Ok)
    QMessageBox.warning = _static(QMessageBox.Warning, QMessageBox.Ok)
    QMessageBox.critical = _static(QMessageBox.Critical, QMessageBox.Ok)
    QMessageBox.question = _static(QMessageBox.Question, QMessageBox.Yes | QMessageBox.No)

    def about(parent, title, text):
        box = QMessageBox(QMessageBox.Information, title, text, QMessageBox.Ok, parent)
        box.setTextFormat(Qt.RichText if "<" in text else Qt.AutoText)
        modernize(box)
        box.exec()
    QMessageBox.about = staticmethod(about)
