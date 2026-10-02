# -*- coding: utf-8 -*-
"""
Современный вид стандартных окон: сообщения и вопросы (QMessageBox) — с цветным значком-кружком,
крупным заголовком, пояснением ниже и кнопками по-русски («Да», «Нет», «Отмена»), а не серое окно
из Windows 98 с «Yes / No». Подключается один раз при запуске (install), остальной код не меняется.
"""
from PySide6.QtCore import Qt, QRectF, QTimer
from PySide6.QtGui import QPixmap, QPainter, QColor, QFont, QFontMetrics
from PySide6.QtWidgets import (QMessageBox, QApplication, QDialogButtonBox, QDialog, QLabel, QPushButton, QVBoxLayout,
                               QHBoxLayout, QFrame, QPlainTextEdit)

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


def fit_primary(root):
    """Главные кнопки (жирный текст): ширина по жирному шрифту — иначе Qt считает ширину по обычному
    и конец надписи обрезается («Добавить файлы в конец..»)."""
    from PySide6.QtWidgets import QPushButton
    for b in root.findChildren(QPushButton):
        if b.text() and (b.objectName() == "primary" or b.isDefault()):
            f = QFont(b.font())
            f.setBold(True)
            need = QFontMetrics(f).horizontalAdvance(b.text().replace("&", "")) + 40
            if b.minimumWidth() < need and b.maximumWidth() >= need:
                b.setMinimumWidth(need)


def _appear(dlg):
    """Окна появляются мягко (проявление и лёгкое «всплытие»), если анимации включены."""
    try:
        import anim
    except Exception:
        return
    if not anim.ENABLED or dlg.property("noanim"):
        return
    dlg.setWindowOpacity(0.0)
    QTimer.singleShot(0, lambda: anim.pop_in(dlg, dy=8, ms=180) if dlg.isVisible() else dlg.setWindowOpacity(1.0))
    QTimer.singleShot(700, lambda: _opaque(dlg))


def _opaque(dlg):
    try:
        import anim
        if dlg.windowOpacity() < 1.0 and id(dlg) not in anim._running:
            dlg.setWindowOpacity(1.0)
    except RuntimeError:
        pass


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
QDialog#tooldlg QLabel#mbhead {{ font-size: 11.5pt; font-weight: 600; }}
QDialog#tooldlg QLabel#mbtext {{ font-size: 10.5pt; }}
QDialog#tooldlg QLabel#mbinfo {{ color: {t['muted']}; font-size: 9.5pt; }}
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
        return ModernBox(self).run()
    QMessageBox.exec = exec_
    orig_dexec = QDialog.exec

    def dexec(self, *a):
        fit_primary(self)
        _appear(self)
        return orig_dexec(self, *a)
    QDialog.exec = dexec
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


class ModernBox(QDialog):
    """Окно сообщения нашей вёрстки вместо стандартного QMessageBox. Стандартное окно на Windows считало
    ширину до того, как применялся шрифт оформления, и длинный текст обрезался справа. Здесь текст всегда
    переносится по ширине окна. Кнопки — те же, что у исходного окна: нажатие передаётся ему, поэтому
    box.clickedButton() и всё остальное работают как раньше."""
    MAXW = 520

    def __init__(self, box):
        super().__init__(box.parentWidget())
        self.box = box
        self.chosen = None
        t = _theme
        self.setWindowTitle(box.windowTitle() or "LegalHelper")
        self.setObjectName("tooldlg")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        top = QHBoxLayout()
        top.setContentsMargins(22, 20, 24, 16)
        top.setSpacing(14)
        pm = box.iconPixmap()
        if pm is not None and not pm.isNull():
            ic = QLabel()
            ic.setPixmap(pm)
            ic.setFixedSize(int(pm.width() / max(1.0, pm.devicePixelRatio())) + 2,
                            int(pm.height() / max(1.0, pm.devicePixelRatio())) + 2)
            top.addWidget(ic, 0, Qt.AlignTop)
        col = QVBoxLayout()
        col.setSpacing(6)
        info = box.informativeText()
        head = QLabel(box.text())
        head.setObjectName("mbhead" if info else "mbtext")
        head.setTextFormat(box.textFormat())
        col.addWidget(head)
        labels = [head]
        if info:
            sub = QLabel(info)
            sub.setObjectName("mbinfo")
            sub.setTextFormat(box.textFormat())
            col.addWidget(sub)
            labels.append(sub)
        fm = head.fontMetrics()
        longest = max((fm.horizontalAdvance(line) for lab in labels for line in lab.text().splitlines()), default=0)
        width = max(300, min(self.MAXW, longest + 30))
        for lab in labels:
            lab.setWordWrap(True)
            lab.setFixedWidth(width)
            lab.setOpenExternalLinks(True)
            lab.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.LinksAccessibleByMouse)
        details = box.detailedText()
        if details:
            self.det = QPlainTextEdit(details)
            self.det.setReadOnly(True)
            self.det.setFixedSize(width, 160)
            self.det.hide()
            col.addWidget(self.det)
        top.addLayout(col, 1)
        lay.addLayout(top)
        foot = QFrame()
        foot.setObjectName("dlgfoot")
        row = QHBoxLayout(foot)
        row.setContentsMargins(22, 12, 22, 14)
        row.setSpacing(8)
        if details:
            more = QPushButton("Подробнее")
            more.setCursor(Qt.PointingHandCursor)
            more.clicked.connect(lambda: (self.det.setVisible(not self.det.isVisible()), self.adjustSize()))
            row.addWidget(more)
        row.addStretch(1)
        # своя кнопка «Подробнее» уже есть; служебную «Show Details…» стандартного окна не показываем
        src = [b for b in box.buttons() if not (details and box.buttonRole(b) == QMessageBox.ActionRole
                                                and "detail" in b.text().lower().replace("&", ""))]
        if details and not src:
            src = [box.addButton(QMessageBox.Ok)]
            src[0].setText("ОК")
        default = box.defaultButton()
        if default is None:
            for role in (QMessageBox.AcceptRole, QMessageBox.YesRole, QMessageBox.ApplyRole):
                default = next((b for b in src if box.buttonRole(b) == role), None)
                if default:
                    break
        if default is None and len(src) == 1:
            default = src[0]
        esc = box.escapeButton()
        if esc is None:
            for role in (QMessageBox.RejectRole, QMessageBox.NoRole):
                esc = next((b for b in src if box.buttonRole(b) == role), None)
                if esc:
                    break
        if esc is None and len(src) == 1:
            esc = src[0]
        self.esc = esc
        order = [b for b in src if b is not default] + ([default] if default is not None else [])
        for b in order:
            pb = QPushButton(b.text().replace("&", ""))
            pb.setCursor(Qt.PointingHandCursor)
            bf = QFont(pb.font())
            bf.setBold(True)                     # ширина — по жирному шрифту, чтобы текст не обрезался
            pb.setMinimumWidth(max(96, QFontMetrics(bf).horizontalAdvance(pb.text()) + 44))
            if b is default:
                pb.setObjectName("primary")
                pb.setDefault(True)
                pb.setAutoDefault(True)
            else:
                pb.setAutoDefault(False)
            pb.clicked.connect(lambda _=False, b=b: self._pick(b))
            row.addWidget(pb)
        lay.addWidget(foot)
        if not src:                       # окно без кнопок (бывает у QMessageBox) — дать хотя бы «ОК»
            pb = QPushButton("ОК")
            pb.setObjectName("primary")
            pb.clicked.connect(self.accept)
            row.addWidget(pb)

    def _pick(self, b):
        self.chosen = b
        self.accept()

    def reject(self):
        if self.chosen is None:
            self.chosen = self.esc
        super().reject()

    def run(self):
        QDialog.exec(self)                        # с мягким появлением (обёртка _appear)
        b = self.chosen
        box = self.box
        if b is None:
            return 0
        sb = box.standardButton(b)
        try:
            b.click()                             # исходное окно запоминает нажатую кнопку
        except RuntimeError:
            pass
        return int(sb) if sb != QMessageBox.NoButton else box.buttons().index(b) if b in box.buttons() else 0
