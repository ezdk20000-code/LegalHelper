# -*- coding: utf-8 -*-
"""Интерфейс юридических функций: калькуляторы, дела, пакет в суд, ф. 107, проверка, обезличивание,
поиск по делу, шаблоны, выписки, справка «?»."""
import os
import json
import datetime as dt
from pathlib import Path
from types import SimpleNamespace

import pymupdf as fitz
from PySide6.QtCore import Qt, QDate, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QColor, QFont
from PySide6.QtWidgets import (
    QWidget, QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QGridLayout, QLabel, QPushButton, QToolButton,
    QComboBox, QLineEdit, QSpinBox, QDoubleSpinBox, QDateEdit, QCheckBox, QTextBrowser, QPlainTextEdit,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView, QListWidget, QListWidgetItem,
    QTabWidget, QMessageBox, QFileDialog, QDialogButtonBox, QApplication, QSplitter, QFrame, QInputDialog,
    QRadioButton, QButtonGroup, QScrollArea, QSizePolicy, QMenu, QSystemTrayIcon, QStackedWidget)

import pdf_core as C
import legal_core as L
import legal_data as D
import cases as CS

M = None          # пространство имён главного модуля (bind)
_db = None


def bind(ns):
    global M
    M = SimpleNamespace(**ns)


def db():
    global _db
    if _db is None:
        _db = CS.CaseDB(os.path.join(M.data_dir(), "cases.sqlite"))
    return _db


def templates_dir():
    d = os.path.join(M.data_dir(), "Шаблоны")
    os.makedirs(d, exist_ok=True)
    return d


# =============================================================================
#  Справка «?»
# =============================================================================
HELP = {
    "package": ("Пакет в суд / на почту",
        "Собирает иск (жалобу, письмо) и приложения в пакет, который примет выбранная площадка."
        "<ul><li><b>«Мой арбитр» и ГАС «Правосудие»</b> — каждый документ отдельным PDF до 30 МБ, в имени "
        "файла название и число листов («02. Копия договора 6 л.pdf»). Большие файлы сжимаются, а если не "
        "помогает — делятся на части.</li>"
        "<li><b>Почта России, бумажная доставка</b> — один файл, все страницы A4, всего до 19 страниц и 20 МБ. "
        "Если страниц больше — пакет делится на несколько писем.</li>"
        "<li><b>Почта России, электронная доставка</b> — до 20 МБ.</li></ul>"
        "Первым в списке ставьте основной документ. Программа составит <b>перечень приложений</b> "
        "(«1. Копия договора — на 6 л. в 1 экз.») — его можно скопировать или добавить последней страницей "
        "в основной документ. Из этого же списка можно сразу сделать <b>опись ф. 107</b>."),
    "sheetnum": ("Нумерация листов дела",
        "Ставит номера листов в правом верхнем углу, как в материалах дела. "
        "<ul><li><b>Листов в томе</b> — по Инструкции по делопроизводству том не больше 250 листов; "
        "0 — без деления на тома.</li><li><b>Двусторонние листы</b> — номер ставится только на лицевой "
        "стороне (нечётные страницы).</li><li>Можно сохранить каждый том отдельным файлом с титульным листом.</li></ul>"),
    "certify": ("Штамп заверения",
        "Ставит штамп «Копия верна» с должностью, ФИО, датой — на всех страницах или только на последней. "
        "Можно добавить картинку подписи (PNG с прозрачным фоном) и надпись «Прошито, пронумеровано N листов» "
        "на последней странице. Наборы строк сохраняются как шаблоны."),
    "f107": ("Опись вложения ф. 107",
        "Форма Почты России для ценного письма (бандероли, посылки) с описью. Заполняется в двух экземплярах: "
        "один вкладывается в отправление, второй с отметкой почты остаётся у вас. Короткая опись печатается "
        "двумя экземплярами на одном листе A4 (разрезать по линии), длинная — по листу на экземпляр. "
        "Если ценность не объявляется — оставьте графу пустой (будет прочерк)."),
    "preflight": ("Проверка перед подачей",
        "Находит то, из-за чего документы возвращают: превышение размера, пустые и перевёрнутые страницы, "
        "сканы без текстового слоя (нужен OCR), низкое разрешение (< 150 dpi вместо 200–300), не A4 для почты, "
        "защиту от копирования. Двойной щелчок по строке — перейти к странице."),
    "anonymize": ("Обезличивание (152-ФЗ)",
        "Находит персональные данные: ФИО, паспорта, СНИЛС, ИНН, счета и карты, телефоны, e-mail, адреса, "
        "даты рождения, госномера. Сначала показывает список найденного — снимите галочки с лишнего, затем "
        "данные удаляются <b>безвозвратно</b> (из текста, а не просто закрашиваются). Поиск эвристический: "
        "всегда просматривайте результат, особенно ФИО в падежах и адреса."),
    "compare_ed": ("Сравнение редакций",
        "Сравнивает две редакции договора или документа (PDF, DOCX, TXT) по словам и показывает правки "
        "в стиле «было / стало»: <del style='color:#b3261e'>удалённое</del> и "
        "<ins style='color:#0a7a28'>добавленное</ins>. Отчёт сохраняется в HTML (открывается в браузере, "
        "можно переслать) и PDF."),
    "case_search": ("Поиск по документам",
        "Ищет слово или фразу сразу во всех документах дела (или в выбранных файлах / папке). "
        "Сканы без текстового слоя найти нельзя — программа их перечислит, прогоните их через OCR."),
    "template": ("Документ по шаблону",
        "Шаблон — обычный файл Word (.docx), в котором вместо данных стоят поля в фигурных скобках: "
        "<code>{Доверитель}</code>, <code>{Номер_дела}</code>, <code>{Суд}</code>, <code>{Судья}</code>, "
        "<code>{Оппонент}</code>, <code>{Дата}</code> — или любые свои, например <code>{Сумма_долга}</code>. "
        "Поля из карточки дела подставляются сами, остальные программа спросит. Шаблоны хранятся в папке "
        "«Шаблоны» (кнопка «Открыть папку шаблонов»)."),
    "quote": ("Выписки",
        "Выделите рамкой фрагмент на странице — текст попадёт в выписки выбранного дела с пометкой «л. N». "
        "Потом выписки можно скопировать или выгрузить в Word для позиции по делу."),
    "calc_deadline": ("Процессуальные сроки",
        "Течение срока начинается на следующий день после события. Сроки в днях считаются в рабочих днях "
        "(АПК, ГПК, КАС), календарные — если так указано (сутки в УПК, претензионный срок). Если последний "
        "день нерабочий — срок переносится на следующий рабочий день. Учтены праздники и переносы по "
        "постановлениям Правительства на 2024–2027 годы. Результат можно добавить в дело — он появится "
        "в календаре с напоминанием."),
    "calc_duty": ("Госпошлина",
        "Размеры по ст. 333.19 (суды общей юрисдикции) и ст. 333.21 (арбитражные суды) НК РФ в редакции "
        "259-ФЗ — для заявлений, поданных после 08.09.2024. Пошлина округляется до полного рубля. "
        "Льготы (ст. 333.35–333.37 НК) и особые случаи не учитываются."),
    "calc_interest": ("Проценты и неустойка",
        "<b>Ст. 395 ГК</b> — ключевая ставка Банка России по периодам её действия, база — 365/366 дней. "
        "<b>Неустойка</b> — процент в день или доля ключевой ставки (1/300, 1/150, 1/130). "
        "Оплаты уменьшают долг со следующего дня (день оплаты включается в просрочку); увеличения долга — "
        "с указанной даты. Можно исключить мораторий 01.04.2022–01.10.2022 (ПП РФ № 497). "
        "Таблицу можно вставить в иск (Word) или сохранить в PDF."),
    "cases": ("Дела",
        "Карточки дел хранятся только на этом компьютере. В карточке — стороны, суд, стадия, сроки и "
        "заседания (с напоминаниями), документы, учёт времени и оплат с актом, выписки. "
        "Напоминания показываются при запуске программы и за день до события."),
    "ocr": ("OCR — распознавание текста",
        "Добавляет к сканам невидимый текстовый слой: документ выглядит так же, но в нём работает поиск "
        "и копирование. Суды просят документы «с возможностью копирования текста»."),
    "compress": ("Сжатие PDF",
        "Уменьшает размер за счёт картинок (сканов). «Рекомендуемое» — 150 dpi, текст остаётся чётким. "
        "Для подачи в суд обычно достаточно."),
    "pdfa": ("PDF/A", "Архивный формат для долгого хранения. Нужна бесплатная программа Ghostscript."),
    "redact": ("Скрыть данные",
        "Находит слова и шаблоны (e-mail, телефоны, карты, паспорта) и удаляет их безвозвратно. "
        "Для персональных данных удобнее «Обезличивание (152-ФЗ)»."),
    "split": ("Разделение PDF",
        "Каждая страница отдельным файлом, каждые N страниц, или по диапазонам: «1-3, 4-10, 11-»."),
    "protect": ("Пароль", "Шифрование AES-256. Можно запретить печать, копирование, изменение."),
    "compare": ("Сравнить PDF",
        "Техническое сравнение двух PDF по тексту и картинке страниц. Для договоров удобнее "
        "«Сравнение редакций» — там правки видны по словам."),
    "pagesize": ("Размер страниц", "Приводит страницы к A4 или другому формату. Текст остаётся текстом."),
    "forms": ("PDF-формы", "Заполнение полей интерактивных форм; «вшить» — сделать заполненное неизменяемым."),
}


def show_help(parent, key):
    title, text = HELP.get(key, ("Справка", "Нет справки"))
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setTextFormat(Qt.RichText)
    box.setText(f"<h3 style='margin:0'>{title}</h3><div style='max-width:520px'>{text}</div>")
    box.setIcon(QMessageBox.NoIcon)
    box.exec()


class HelpButton(QToolButton):
    def __init__(self, key, parent=None):
        super().__init__(parent)
        self.key = key
        self.setText("?")
        self.setObjectName("help")
        self.setToolTip("Подробнее об этой функции")
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(22, 22)
        self.clicked.connect(lambda: show_help(self.window(), self.key))


def title_row(text, help_key=None, big=False):
    row = QHBoxLayout()
    lab = QLabel(text)
    lab.setObjectName("title" if big else "subtitle")
    row.addWidget(lab)
    if help_key:
        row.addWidget(HelpButton(help_key))
    row.addStretch(1)
    return row


# =============================================================================
#  Мелкие виджеты
# =============================================================================
def date_edit(d=None):
    w = QDateEdit()
    w.setCalendarPopup(True)
    w.setDisplayFormat("dd.MM.yyyy")
    d = d or dt.date.today()
    w.setDate(QDate(d.year, d.month, d.day))
    return w


def qdate(w):
    q = w.date()
    return dt.date(q.year(), q.month(), q.day())


def money_edit(v=0.0):
    w = QDoubleSpinBox()
    w.setRange(0, 1e13)
    w.setDecimals(2)
    w.setGroupSeparatorShown(True)
    w.setValue(v)
    w.setSuffix(" ₽")
    return w


WEEKDAYS = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]


def pick_case(parent, title="Выберите дело"):
    items = db().cases()
    if not items:
        if QMessageBox.question(parent, M.APP_NAME, "Дел пока нет. Создать новое дело?") != QMessageBox.Yes:
            return None
        name, ok = QInputDialog.getText(parent, "Новое дело", "Название дела (например, «ООО Ромашка — взыскание долга»):")
        if not ok or not name.strip():
            return None
        return db().add_case(title=name.strip())
    labels = [f"{c['title']}" + (f"  ·  {c['number']}" if c["number"] else "") for c in items]
    s, ok = QInputDialog.getItem(parent, title, "Дело:", labels, 0, False)
    if not ok:
        return None
    return items[labels.index(s)]["id"]


class ResultView(QWidget):
    """Результат расчёта + экспорт (Word, PDF, буфер обмена)."""

    def __init__(self):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.view = QTextBrowser()
        self.view.setOpenExternalLinks(True)
        self.view.setObjectName("result")
        lay.addWidget(self.view, 1)
        row = QHBoxLayout()
        self.b_copy = QPushButton("Копировать")
        self.b_word = QPushButton("В Word…")
        self.b_pdf = QPushButton("В PDF…")
        for b in (self.b_copy, self.b_word, self.b_pdf):
            row.addWidget(b)
            b.setEnabled(False)
        row.addStretch(1)
        lay.addLayout(row)
        self.data = None
        self.b_copy.clicked.connect(self.copy)
        self.b_word.clicked.connect(self.to_word)
        self.b_pdf.clicked.connect(self.to_pdf)

    def set_html(self, html_text, data=None):
        self.view.setHtml(html_text)
        self.data = data
        for b in (self.b_copy, self.b_word, self.b_pdf):
            b.setEnabled(data is not None)

    def copy(self):
        from PySide6.QtCore import QMimeData
        title, head, body, foot = self.data
        md = QMimeData()
        md.setHtml(L.table_html(title, head, body, foot))
        md.setText(L.table_tsv(head, body, foot))
        QApplication.clipboard().setMimeData(md)
        QMessageBox.information(self, M.APP_NAME, "Таблица скопирована — вставьте её в Word (Ctrl+V).")

    def _ask(self, suffix, flt):
        p, _ = QFileDialog.getSaveFileName(self, "Сохранить", os.path.join(str(Path.home() / "Documents"),
                                           "Расчёт" + suffix), flt)
        if p and not p.lower().endswith(suffix):
            p += suffix
        return p

    def to_word(self):
        p = self._ask(".docx", "Word (*.docx)")
        if p:
            title, head, body, foot = self.data
            L.table_docx(p, title, head, body, foot)
            QDesktopServices.openUrl(QUrl.fromLocalFile(p))

    def to_pdf(self):
        p = self._ask(".pdf", "PDF (*.pdf)")
        if p:
            title, head, body, foot = self.data
            L.html_to_pdf_file(L.table_html(title, head, body, foot), p)
            QDesktopServices.openUrl(QUrl.fromLocalFile(p))


def _small_btn(text):
    b = QPushButton(text)
    b.setFixedWidth(38)
    b.setStyleSheet("padding: 4px 0px;")
    return b


def card(widget_or_layout):
    f = QFrame()
    f.setObjectName("card")
    lay = QVBoxLayout(f)
    lay.setContentsMargins(16, 14, 16, 14)
    if isinstance(widget_or_layout, QWidget):
        lay.addWidget(widget_or_layout)
    else:
        lay.addLayout(widget_or_layout)
    return f


# =============================================================================
#  Калькуляторы
# =============================================================================
class DeadlineTab(QWidget):
    def __init__(self):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.addLayout(title_row("Процессуальный срок", "calc_deadline"))
        f = QFormLayout()
        self.preset = QComboBox()
        self.preset.addItems([p[0] for p in D.DEADLINE_PRESETS])
        self.start = date_edit()
        self.n = QSpinBox()
        self.n.setRange(1, 3650)
        self.unit = QComboBox()
        self.units = list(D.UNIT_NAMES)
        self.unit.addItems(list(D.UNIT_NAMES.values()))
        rown = QHBoxLayout()
        rown.addWidget(self.n)
        rown.addWidget(self.unit, 1)
        self.hint = QLabel()
        self.hint.setObjectName("hint")
        self.hint.setWordWrap(True)
        f.addRow("Вид срока", self.preset)
        f.addRow("", self.hint)
        f.addRow("Дата события", self.start)
        f.addRow("Длительность", rown)
        lay.addWidget(card(f))
        self.res = QLabel()
        self.res.setObjectName("bigresult")
        self.res.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.notes = QLabel()
        self.notes.setWordWrap(True)
        self.notes.setObjectName("hint")
        b_add = QPushButton("Добавить в дело…")
        b_add.clicked.connect(self.add_to_case)
        r = QVBoxLayout()
        r.addWidget(self.res)
        r.addWidget(self.notes)
        rb = QHBoxLayout()
        rb.addWidget(b_add)
        rb.addStretch(1)
        r.addLayout(rb)
        lay.addWidget(card(r))
        # между датами
        lay.addLayout(title_row("Дней между датами"))
        g = QHBoxLayout()
        self.d1, self.d2 = date_edit(), date_edit(dt.date.today() + dt.timedelta(days=30))
        g.addWidget(QLabel("с"))
        g.addWidget(self.d1)
        g.addWidget(QLabel("по"))
        g.addWidget(self.d2)
        self.between = QLabel()
        g.addWidget(self.between, 1)
        lay.addWidget(card(g))
        lay.addStretch(1)
        self.preset.currentIndexChanged.connect(self.on_preset)
        for w in (self.start, self.d1, self.d2):
            w.dateChanged.connect(self.calc)
        self.n.valueChanged.connect(self.calc)
        self.unit.currentIndexChanged.connect(self.calc)
        self.on_preset(0)

    def on_preset(self, i):
        name, n, unit, hint = D.DEADLINE_PRESETS[i]
        self.n.blockSignals(True)
        self.unit.blockSignals(True)
        self.n.setValue(n)
        self.unit.setCurrentIndex(self.units.index(unit))
        self.n.blockSignals(False)
        self.unit.blockSignals(False)
        self.hint.setText(hint)
        self.calc()

    def calc(self):
        d, notes = L.compute_deadline(qdate(self.start), self.n.value(), self.units[self.unit.currentIndex()])
        self.result = d
        self.res.setText(f"Последний день срока: <b>{L.ddmmyyyy(d)}</b> ({WEEKDAYS[d.weekday()]})")
        left = (d - dt.date.today()).days
        extra = f"Осталось дней: {left}." if left >= 0 else f"Срок истёк {-left} дн. назад."
        self.notes.setText(" ".join(notes + [extra]))
        cal, work = L.days_between(qdate(self.d1), qdate(self.d2))
        self.between.setText(f"   календарных: <b>{cal}</b>, рабочих: <b>{work}</b> (включительно)")

    def add_to_case(self):
        cid = pick_case(self)
        if not cid:
            return
        title = self.preset.currentText() if self.preset.currentIndex() else \
            f"Срок {self.n.value()} {self.unit.currentText()} от {L.ddmmyyyy(qdate(self.start))}"
        title, ok = QInputDialog.getText(self, "Срок в деле", "Название:", text=title.split(" — ")[0])
        if ok:
            db().add_event(cid, self.result, "Срок", title)
            QMessageBox.information(self, M.APP_NAME, f"Срок {L.ddmmyyyy(self.result)} добавлен в дело.")


class DutyTab(QWidget):
    def __init__(self):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.addLayout(title_row("Государственная пошлина", "calc_duty"))
        f = QFormLayout()
        self.court = QComboBox()
        self.court.addItems(["Арбитражный суд (ст. 333.21 НК)", "Суд общей юрисдикции (ст. 333.19 НК)"])
        self.kind = QComboBox()
        self.person = QComboBox()
        self.person.addItems(["Организация", "Физическое лицо / ИП"])
        self.amount = money_edit(100000)
        f.addRow("Суд", self.court)
        f.addRow("Заявление", self.kind)
        f.addRow("Заявитель", self.person)
        f.addRow("Цена иска", self.amount)
        lay.addWidget(card(f))
        self.res = QLabel()
        self.res.setObjectName("bigresult")
        self.res.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.expl = QLabel()
        self.expl.setWordWrap(True)
        self.expl.setObjectName("hint")
        r = QVBoxLayout()
        r.addWidget(self.res)
        r.addWidget(self.expl)
        lay.addWidget(card(r))
        lay.addStretch(1)
        self.court.currentIndexChanged.connect(self.fill_kinds)
        self.kind.currentIndexChanged.connect(self.calc)
        self.person.currentIndexChanged.connect(self.calc)
        self.amount.valueChanged.connect(self.calc)
        self.fill_kinds()

    def fill_kinds(self):
        self.kind.blockSignals(True)
        self.kind.clear()
        fixed = D.DUTY_ARB_FIXED if self.court.currentIndex() == 0 else D.DUTY_SOJ_FIXED
        self.kind.addItems(["Имущественный иск (по цене иска)", "Судебный приказ"] + [n for n, _ in fixed])
        self.kind.blockSignals(False)
        self.calc()

    def calc(self):
        court = "arb" if self.court.currentIndex() == 0 else "soj"
        k = self.kind.currentIndex()
        person = "org" if self.person.currentIndex() == 0 else "fl"
        self.amount.setEnabled(k < 2)
        if k < 2:
            v, e = L.state_duty(court, self.amount.value(), order=(k == 1))
        else:
            v, e = L.state_duty(court, fixed_index=k - 2, person=person)
        self.res.setText(f"Госпошлина: <b>{L.money(v, False)} ₽</b>")
        self.expl.setText(e)


class InterestTab(QWidget):
    MODES = ["Проценты по ст. 395 ГК (ключевая ставка)", "Неустойка — % в день",
             "Неустойка — доля ключевой ставки (1/300, 1/150…)"]

    def __init__(self):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.addLayout(title_row("Проценты и неустойка", "calc_interest"))
        top = QHBoxLayout()
        f = QFormLayout()
        self.mode = QComboBox()
        self.mode.addItems(self.MODES)
        self.principal = money_edit(100000)
        self.d_from = date_edit(dt.date.today() - dt.timedelta(days=180))
        self.d_to = date_edit()
        self.pct = QDoubleSpinBox()
        self.pct.setRange(0.0001, 100)
        self.pct.setDecimals(4)
        self.pct.setValue(0.1)
        self.pct.setSuffix(" % в день")
        self.div = QComboBox()
        self.div.addItems(["1/300", "1/150", "1/130", "1/360"])
        self.fixed = QCheckBox("Ставка на дату:")
        self.fixed_date = date_edit()
        rf = QHBoxLayout()
        rf.addWidget(self.fixed)
        rf.addWidget(self.fixed_date)
        rf.addStretch(1)
        self.morat = QCheckBox("Исключить мораторий 01.04–01.10.2022")
        self.capc = QCheckBox("Не больше суммы долга")
        f.addRow("Что считаем", self.mode)
        f.addRow("Сумма долга", self.principal)
        f.addRow("Просрочка с", self.d_from)
        f.addRow("по (включительно)", self.d_to)
        f.addRow("Размер", self.pct)
        f.addRow("Доля ставки", self.div)
        f.addRow("", rf)
        f.addRow("", self.morat)
        f.addRow("", self.capc)
        self.form = f
        top.addWidget(card(f), 3)
        # оплаты
        pv = QVBoxLayout()
        pv.addWidget(QLabel("Оплаты и увеличения долга"))
        self.moves = QTableWidget(0, 3)
        self.moves.setHorizontalHeaderLabels(["Дата", "Сумма, ₽", "Тип"])
        self.moves.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.moves.verticalHeader().setVisible(False)
        pv.addWidget(self.moves)
        rb = QHBoxLayout()
        b1, b2 = QPushButton("+ Оплата"), QPushButton("+ Долг")
        b3 = QPushButton("Удалить")
        b1.clicked.connect(lambda: self.add_move("Оплата"))
        b2.clicked.connect(lambda: self.add_move("Увеличение долга"))
        b3.clicked.connect(lambda: self.moves.removeRow(self.moves.currentRow()))
        for b in (b1, b2, b3):
            rb.addWidget(b)
        pv.addLayout(rb)
        top.addWidget(card(pv), 2)
        lay.addLayout(top)
        rowc = QHBoxLayout()
        b = QPushButton("Рассчитать")
        b.setObjectName("primary")
        b.clicked.connect(self.calc)
        self.total = QLabel()
        self.total.setObjectName("bigresult")
        rowc.addWidget(b)
        rowc.addSpacing(12)
        rowc.addWidget(self.total, 1)
        lay.addLayout(rowc)
        self.result = ResultView()
        lay.addWidget(self.result, 1)
        self.mode.currentIndexChanged.connect(self.on_mode)
        self.on_mode(0)

    def on_mode(self, i):
        for w, vis in ((self.pct, i == 1), (self.div, i == 2), (self.fixed, i == 2), (self.fixed_date, i == 2),
                       (self.capc, i > 0)):
            w.setVisible(vis)
            lab = self.form.labelForField(w)
            if lab:
                lab.setVisible(vis)

    def add_move(self, kind):
        r = self.moves.rowCount()
        self.moves.insertRow(r)
        de = date_edit()
        me = money_edit(0)
        self.moves.setCellWidget(r, 0, de)
        self.moves.setCellWidget(r, 1, me)
        it = QTableWidgetItem(kind)
        it.setFlags(Qt.ItemIsEnabled)
        self.moves.setItem(r, 2, it)

    def calc(self):
        pays, adds = [], []
        for r in range(self.moves.rowCount()):
            d = qdate(self.moves.cellWidget(r, 0))
            a = self.moves.cellWidget(r, 1).value()
            (pays if self.moves.item(r, 2).text() == "Оплата" else adds).append((d, a))
        m = self.mode.currentIndex()
        try:
            res = L.interest_calc(self.principal.value(), qdate(self.d_from), qdate(self.d_to), pays, adds,
                                  mode=["395", "pct", "frac"][m], pct_per_day=self.pct.value(),
                                  rate_divisor=int(self.div.currentText().split("/")[1]),
                                  fixed_rate_date=qdate(self.fixed_date) if (m == 2 and self.fixed.isChecked()) else None,
                                  exclude_moratorium=self.morat.isChecked(), cap_principal=self.capc.isChecked() and m > 0)
        except ValueError as e:
            QMessageBox.warning(self, M.APP_NAME, str(e))
            return
        head, body = L.calc_table(res, m)
        title = ["Расчёт процентов по ст. 395 ГК РФ", "Расчёт неустойки", "Расчёт неустойки"][m]
        title += f" на сумму {L.money(self.principal.value())} ₽ за период {L.ddmmyyyy(qdate(self.d_from))} – " \
                 f"{L.ddmmyyyy(qdate(self.d_to))}"
        foot = [f"Итого: {L.money(res['total'])} ₽"] + res["notes"]
        self.total.setText(f"Итого: <b>{L.money(res['total'])} ₽</b>")
        self.result.set_html(L.table_html(title, head, body, foot), (title, head, body, foot))


class CalcPage(QWidget):
    def __init__(self):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 18, 24, 18)
        lay.addLayout(title_row("Калькуляторы", big=True))
        self.tabs = tabs = QTabWidget()
        tabs.setObjectName("segmented")
        tabs.setDocumentMode(True)
        for w, name in ((DeadlineTab(), "Сроки"), (DutyTab(), "Госпошлина"), (InterestTab(), "Проценты и неустойка")):
            sc = QScrollArea()
            sc.setWidget(w)
            sc.setWidgetResizable(True)
            sc.setFrameShape(QFrame.NoFrame)
            tabs.addTab(sc, name)
        lay.addWidget(tabs, 1)
        info = QLabel(f"Данные (ставки ЦБ, календари, пошлины) — на {D.DATA_DATE}. Обновляются вместе с программой.")
        info.setObjectName("hint")
        lay.addWidget(info)


# =============================================================================
#  Дела
# =============================================================================
class CasesPage(QWidget):
    openFile = Signal(str, int)          # путь, страница
    buildPackage = Signal(list)          # пути

    def __init__(self, main):
        super().__init__()
        self.main = main
        self.cid = None
        self._loading = False
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        split = QSplitter()
        root.addWidget(split)
        # ---- левая колонка
        left = QWidget()
        left.setObjectName("sidepanel")
        lv = QVBoxLayout(left)
        lv.setContentsMargins(14, 14, 14, 14)
        lv.addLayout(title_row("Дела", "cases", big=True))
        self.search = QLineEdit()
        self.search.setPlaceholderText("Поиск: номер, доверитель, суд…")
        self.search.textChanged.connect(self.reload)
        lv.addWidget(self.search)
        self.list = QListWidget()
        self.list.setObjectName("caselist")
        self.list.currentItemChanged.connect(self.on_select)
        lv.addWidget(self.list, 1)
        rb = QHBoxLayout()
        b_new = QPushButton("+ Новое дело")
        b_new.setObjectName("primary")
        b_new.clicked.connect(self.new_case)
        self.show_arch = QCheckBox("Архив")
        self.show_arch.toggled.connect(self.reload)
        rb.addWidget(b_new)
        rb.addStretch(1)
        rb.addWidget(self.show_arch)
        lv.addLayout(rb)
        lv.addWidget(QLabel("Ближайшие 14 дней"))
        self.upcoming = QListWidget()
        self.upcoming.setObjectName("upcoming")
        self.upcoming.setMaximumHeight(190)
        self.upcoming.setWordWrap(True)
        self.upcoming.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.upcoming.itemDoubleClicked.connect(self.goto_event_case)
        lv.addWidget(self.upcoming)
        split.addWidget(left)
        # ---- карточка
        self.stack = QStackedWidget()
        empty = QLabel("Выберите дело слева или создайте новое")
        empty.setAlignment(Qt.AlignCenter)
        empty.setObjectName("hint")
        self.stack.addWidget(empty)
        self.card = QWidget()
        cv = QVBoxLayout(self.card)
        cv.setContentsMargins(22, 16, 22, 16)
        head = QHBoxLayout()
        self.h_title = QLabel()
        self.h_title.setObjectName("title")
        head.addWidget(self.h_title, 1)
        self.b_arch = QPushButton("В архив")
        self.b_arch.clicked.connect(self.toggle_archive)
        b_del = QPushButton("Удалить")
        b_del.clicked.connect(self.delete_case)
        head.addWidget(self.b_arch)
        head.addWidget(b_del)
        cv.addLayout(head)
        self.tabs = QTabWidget()
        self.tabs.setObjectName("segmented")
        self.tabs.setDocumentMode(True)
        cv.addWidget(self.tabs, 1)
        self._build_info()
        self._build_events()
        self._build_docs()
        self._build_money()
        self._build_quotes()
        self.stack.addWidget(self.card)
        split.addWidget(self.stack)
        split.setStretchFactor(1, 1)
        split.setSizes([300, 900])
        self.save_timer = QTimer(self)
        self.save_timer.setSingleShot(True)
        self.save_timer.setInterval(600)
        self.save_timer.timeout.connect(self.save_info)
        self.reload()

    # ------------------------------------------------------------ вкладки
    def _build_info(self):
        w = QWidget()
        f = QFormLayout(w)
        self.fields = {}
        for key, label in CS.CASE_FIELDS:
            if key == "stage":
                e = QComboBox()
                e.setEditable(True)
                e.addItems(D.CASE_STAGES)
                e.currentTextChanged.connect(lambda *_: self.save_timer.start())
            elif key == "notes":
                e = QPlainTextEdit()
                e.setMinimumHeight(120)
                e.textChanged.connect(lambda *_: self.save_timer.start())
            elif key == "rate":
                e = money_edit(0)
                e.valueChanged.connect(lambda *_: self.save_timer.start())
            elif key == "folder":
                e = QLineEdit()
                e.textChanged.connect(lambda *_: self.save_timer.start())
                row = QHBoxLayout()
                row.addWidget(e, 1)
                bb = _small_btn("…")
                bb.setFixedWidth(34)
                bb.clicked.connect(self.pick_folder)
                row.addWidget(bb)
                bo = QPushButton("Открыть")
                bo.clicked.connect(lambda: self.fields["folder"].text() and
                                   QDesktopServices.openUrl(QUrl.fromLocalFile(self.fields["folder"].text())))
                row.addWidget(bo)
                self.fields[key] = e
                f.addRow(label, row)
                continue
            else:
                e = QLineEdit()
                e.textChanged.connect(lambda *_: self.save_timer.start())
            self.fields[key] = e
            f.addRow(label, e)
        sc = QScrollArea()
        sc.setWidget(w)
        sc.setWidgetResizable(True)
        sc.setFrameShape(QFrame.NoFrame)
        self.tabs.addTab(sc, "Сведения")

    def _table(self, headers):
        t = QTableWidget(0, len(headers))
        t.setHorizontalHeaderLabels(headers)
        t.verticalHeader().setVisible(False)
        t.setSelectionBehavior(QAbstractItemView.SelectRows)
        t.setEditTriggers(QAbstractItemView.NoEditTriggers)
        t.horizontalHeader().setStretchLastSection(True)
        t.setAlternatingRowColors(True)
        return t

    def _build_events(self):
        w = QWidget()
        v = QVBoxLayout(w)
        self.t_events = self._table(["Дата", "Время", "Вид", "Что", "Место", "Готово"])
        self.t_events.cellDoubleClicked.connect(self.edit_event)
        v.addWidget(self.t_events, 1)
        r = QHBoxLayout()
        for text, fn in (("+ Заседание", lambda: self.add_event("Заседание")), ("+ Срок", lambda: self.add_event("Срок")),
                         ("+ Задача", lambda: self.add_event("Задача")), ("Отметить выполненным", self.toggle_done),
                         ("Удалить", self.del_event)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            r.addWidget(b)
        r.addStretch(1)
        v.addLayout(r)
        self.tabs.addTab(w, "Сроки и заседания")

    def _build_docs(self):
        w = QWidget()
        v = QVBoxLayout(w)
        self.l_docs = QListWidget()
        self.l_docs.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.l_docs.itemDoubleClicked.connect(lambda it: self.openFile.emit(it.data(Qt.UserRole), 0))
        v.addWidget(self.l_docs, 1)
        r = QHBoxLayout()
        for text, fn in (("+ Добавить файлы", self.add_docs), ("Открыть", self.open_doc),
                         ("Пакет в суд из выбранных", self.package_from_docs), ("Поиск по документам", self.search_docs),
                         ("Документ по шаблону", lambda: tool_template(self.main, self.cid)), ("Убрать", self.del_doc)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            r.addWidget(b)
        r.addStretch(1)
        v.addLayout(r)
        self.tabs.addTab(w, "Документы")

    def _build_money(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.addWidget(QLabel("Учёт времени и работ"))
        self.t_time = self._table(["Дата", "Часы", "Ставка", "Сумма, ₽", "Работа"])
        v.addWidget(self.t_time, 2)
        r = QHBoxLayout()
        for text, fn in (("+ Работа", self.add_time), ("Удалить", lambda: self._del_row(self.t_time, db().delete_time)),
                         ("Акт (Word)…", self.make_act)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            r.addWidget(b)
        r.addStretch(1)
        v.addLayout(r)
        v.addWidget(QLabel("Оплаты"))
        self.t_pay = self._table(["Дата", "Сумма, ₽", "Комментарий"])
        v.addWidget(self.t_pay, 1)
        r2 = QHBoxLayout()
        for text, fn in (("+ Оплата", self.add_payment), ("Удалить", lambda: self._del_row(self.t_pay, db().delete_payment))):
            b = QPushButton(text)
            b.clicked.connect(fn)
            r2.addWidget(b)
        self.balance = QLabel()
        self.balance.setObjectName("subtitle")
        r2.addStretch(1)
        r2.addWidget(self.balance)
        v.addLayout(r2)
        self.tabs.addTab(w, "Время и оплата")

    def _build_quotes(self):
        w = QWidget()
        v = QVBoxLayout(w)
        hint = QLabel("Выписки добавляются из редактора страницы: режим «Выписка» — выделите фрагмент рамкой.")
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        v.addWidget(hint)
        self.l_quotes = QListWidget()
        self.l_quotes.setWordWrap(True)
        self.l_quotes.setSelectionMode(QAbstractItemView.ExtendedSelection)
        v.addWidget(self.l_quotes, 1)
        r = QHBoxLayout()
        for text, fn in (("Копировать", self.copy_quotes), ("В Word…", self.quotes_word), ("Удалить", self.del_quote)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            r.addWidget(b)
        r.addStretch(1)
        v.addLayout(r)
        self.tabs.addTab(w, "Выписки")

    # ------------------------------------------------------------ список дел
    def reload(self, *_):
        cur = self.cid
        self.list.blockSignals(True)
        self.list.clear()
        for c in db().cases(self.show_arch.isChecked(), self.search.text()):
            sub = " · ".join(x for x in (c["number"], c["client"], c["stage"]) if x)
            it = QListWidgetItem(c["title"] + (f"\n{sub}" if sub else ""))
            it.setData(Qt.UserRole, c["id"])
            self.list.addItem(it)
            if c["id"] == cur:
                self.list.setCurrentItem(it)
        self.list.blockSignals(False)
        self.reload_upcoming()
        if self.list.currentItem() is None:
            self.cid = None
            self.stack.setCurrentIndex(0)

    def reload_upcoming(self):
        self.upcoming.clear()
        today = dt.date.today()
        for e in db().events(upcoming_days=14, include_done=False):
            d = dt.date.fromisoformat(e["date"])
            when = "сегодня" if d == today else "завтра" if d == today + dt.timedelta(days=1) else \
                ("просрочено " if d < today else "") + CS.ru(e["date"])
            it = QListWidgetItem(f"{when} {e['time']} — {e['kind']}: {e['title']}\n{e['case_title'] or ''}")
            it.setData(Qt.UserRole, e["case_id"])
            if d <= today:
                it.setForeground(QColor("#d70015"))
            self.upcoming.addItem(it)
        if not self.upcoming.count():
            it = QListWidgetItem("Ничего не запланировано")
            it.setFlags(Qt.NoItemFlags)
            self.upcoming.addItem(it)

    def goto_event_case(self, it):
        cid = it.data(Qt.UserRole)
        if cid:
            self.select_case(cid)
            self.tabs.setCurrentIndex(1)

    def select_case(self, cid):
        for i in range(self.list.count()):
            if self.list.item(i).data(Qt.UserRole) == cid:
                self.list.setCurrentRow(i)
                return
        self.show_arch.setChecked(not self.show_arch.isChecked())
        for i in range(self.list.count()):
            if self.list.item(i).data(Qt.UserRole) == cid:
                self.list.setCurrentRow(i)

    def on_select(self, it, _prev=None):
        if self.save_timer.isActive():
            self.save_timer.stop()
            self.save_info()
        self.cid = it.data(Qt.UserRole) if it else None
        if not self.cid:
            self.stack.setCurrentIndex(0)
            return
        self.stack.setCurrentIndex(1)
        self.load_case()

    def load_case(self):
        c = db().case(self.cid)
        if not c:
            return
        self._loading = True
        self.h_title.setText(c["title"])
        self.b_arch.setText("Вернуть из архива" if c["archived"] else "В архив")
        for k, w in self.fields.items():
            v = c.get(k) or ""
            if isinstance(w, QComboBox):
                w.setCurrentText(str(v))
            elif isinstance(w, QPlainTextEdit):
                w.setPlainText(str(v))
            elif isinstance(w, QDoubleSpinBox):
                w.setValue(float(v or 0))
            else:
                w.setText(str(v))
        self._loading = False
        self.load_events()
        self.load_docs()
        self.load_money()
        self.load_quotes()

    def save_info(self):
        if self._loading or not self.cid:
            return
        vals = {}
        for k, w in self.fields.items():
            if isinstance(w, QComboBox):
                vals[k] = w.currentText()
            elif isinstance(w, QPlainTextEdit):
                vals[k] = w.toPlainText()
            elif isinstance(w, QDoubleSpinBox):
                vals[k] = w.value()
            else:
                vals[k] = w.text()
        if not vals.get("title", "").strip():
            vals["title"] = "Без названия"
        db().update_case(self.cid, **vals)
        self.h_title.setText(vals["title"])
        it = self.list.currentItem()
        if it:
            sub = " · ".join(x for x in (vals["number"], vals["client"], vals["stage"]) if x)
            it.setText(vals["title"] + (f"\n{sub}" if sub else ""))

    def new_case(self):
        name, ok = QInputDialog.getText(self, "Новое дело", "Название (например, «ООО Ромашка — взыскание долга»):")
        if ok and name.strip():
            self.cid = db().add_case(title=name.strip(), stage=D.CASE_STAGES[1])
            self.show_arch.setChecked(False)
            self.reload()
            self.select_case(self.cid)
            self.tabs.setCurrentIndex(0)

    def delete_case(self):
        c = db().case(self.cid)
        if c and QMessageBox.question(self, M.APP_NAME, f"Удалить дело «{c['title']}» со всеми сроками, учётом "
                                      "времени и выписками?\nФайлы документов на диске не удаляются.") == QMessageBox.Yes:
            db().delete_case(self.cid)
            self.cid = None
            self.reload()

    def toggle_archive(self):
        c = db().case(self.cid)
        db().update_case(self.cid, archived=0 if c["archived"] else 1)
        self.cid = None
        self.reload()

    def pick_folder(self):
        p = QFileDialog.getExistingDirectory(self, "Папка с документами дела", self.fields["folder"].text())
        if p:
            self.fields["folder"].setText(p)
            if QMessageBox.question(self, M.APP_NAME, "Добавить PDF и Word-файлы из этой папки в документы дела?") \
                    == QMessageBox.Yes:
                for f in sorted(Path(p).rglob("*")):
                    if f.suffix.lower() in (".pdf", ".docx", ".doc", ".jpg", ".png", ".tif", ".tiff"):
                        db().add_doc(self.cid, str(f))
                self.load_docs()

    # ------------------------------------------------------------ события
    def load_events(self):
        t = self.t_events
        t.setRowCount(0)
        for e in db().events(self.cid):
            r = t.rowCount()
            t.insertRow(r)
            for c, v in enumerate([CS.ru(e["date"]), e["time"], e["kind"], e["title"], e["place"],
                                   "✓" if e["done"] else ""]):
                it = QTableWidgetItem(v)
                it.setData(Qt.UserRole, e["id"])
                t.setItem(r, c, it)
        t.resizeColumnsToContents()
        t.horizontalHeader().setStretchLastSection(True)

    def _event_dialog(self, e=None, kind="Срок"):
        e = e or {}
        dlg = QDialog(self)
        dlg.setWindowTitle(e.get("kind", kind))
        f = QFormLayout(dlg)
        de = date_edit(dt.date.fromisoformat(e["date"]) if e.get("date") else dt.date.today())
        te = QLineEdit(e.get("time", ""))
        te.setPlaceholderText("10:30")
        ke = QComboBox()
        ke.addItems(D.EVENT_KINDS)
        ke.setCurrentText(e.get("kind", kind))
        ti = QLineEdit(e.get("title", ""))
        ti.setPlaceholderText("Предварительное заседание / Отзыв на иск / …")
        pl = QLineEdit(e.get("place", ""))
        pl.setPlaceholderText("Каб. 305")
        f.addRow("Дата", de)
        f.addRow("Время", te)
        f.addRow("Вид", ke)
        f.addRow("Что", ti)
        f.addRow("Место", pl)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        f.addRow(bb)
        if dlg.exec() != QDialog.Accepted:
            return None
        return dict(date=qdate(de), time=te.text().strip(), kind=ke.currentText(), title=ti.text().strip(),
                    place=pl.text().strip())

    def add_event(self, kind):
        v = self._event_dialog(kind=kind)
        if v:
            db().add_event(self.cid, v["date"], v["kind"], v["title"], v["time"], v["place"])
            self.load_events()
            self.reload_upcoming()

    def _cur_id(self, t):
        r = t.currentRow()
        return t.item(r, 0).data(Qt.UserRole) if r >= 0 and t.item(r, 0) else None

    def edit_event(self, row, _col):
        eid = self.t_events.item(row, 0).data(Qt.UserRole)
        e = next((x for x in db().events(self.cid) if x["id"] == eid), None)
        v = self._event_dialog(e)
        if v:
            db().update_event(eid, **v, notified=0)
            self.load_events()
            self.reload_upcoming()

    def toggle_done(self):
        eid = self._cur_id(self.t_events)
        if eid:
            e = next(x for x in db().events(self.cid) if x["id"] == eid)
            db().update_event(eid, done=0 if e["done"] else 1)
            self.load_events()
            self.reload_upcoming()

    def del_event(self):
        eid = self._cur_id(self.t_events)
        if eid:
            db().delete_event(eid)
            self.load_events()
            self.reload_upcoming()

    # ------------------------------------------------------------ документы
    def load_docs(self):
        self.l_docs.clear()
        for d in db().docs(self.cid):
            it = QListWidgetItem(("" if os.path.exists(d["path"]) else "⚠ ") + d["title"])
            it.setToolTip(d["path"])
            it.setData(Qt.UserRole, d["path"])
            it.setData(Qt.UserRole + 1, d["id"])
            self.l_docs.addItem(it)

    def add_docs(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Документы дела", self.fields["folder"].text() or
                                                str(Path.home() / "Documents"), M.OPEN_FILTER)
        for p in paths:
            db().add_doc(self.cid, p)
        self.load_docs()

    def add_doc_path(self, cid, path):
        db().add_doc(cid, path)
        if cid == self.cid:
            self.load_docs()

    def sel_doc_paths(self):
        return [it.data(Qt.UserRole) for it in self.l_docs.selectedItems()]

    def open_doc(self):
        for p in self.sel_doc_paths()[:1]:
            self.openFile.emit(p, 0)

    def package_from_docs(self):
        paths = self.sel_doc_paths() or [self.l_docs.item(i).data(Qt.UserRole) for i in range(self.l_docs.count())]
        if paths:
            PackageDialog(self.main, paths).exec()

    def search_docs(self):
        paths = [self.l_docs.item(i).data(Qt.UserRole) for i in range(self.l_docs.count())]
        SearchDialog(self.main, paths).exec()

    def del_doc(self):
        for it in self.l_docs.selectedItems():
            db().delete_doc(it.data(Qt.UserRole + 1))
        self.load_docs()

    # ------------------------------------------------------------ время и деньги
    def load_money(self):
        t = self.t_time
        t.setRowCount(0)
        for e in db().time_entries(self.cid):
            r = t.rowCount()
            t.insertRow(r)
            s = e["amount"] or (e["hours"] or 0) * (e["rate"] or 0)
            for c, v in enumerate([CS.ru(e["date"]), f"{e['hours']:g}", L.money(e["rate"] or 0, False), L.money(s),
                                   e["description"]]):
                it = QTableWidgetItem(v)
                it.setData(Qt.UserRole, e["id"])
                t.setItem(r, c, it)
        p = self.t_pay
        p.setRowCount(0)
        for e in db().payments(self.cid):
            r = p.rowCount()
            p.insertRow(r)
            for c, v in enumerate([CS.ru(e["date"]), L.money(e["amount"]), e["note"]]):
                it = QTableWidgetItem(v)
                it.setData(Qt.UserRole, e["id"])
                p.setItem(r, c, it)
        b = db().balance(self.cid)
        self.balance.setText(f"Часов: {b['hours']:g} · Начислено: {L.money(b['billed'])} ₽ · Оплачено: "
                             f"{L.money(b['paid'])} ₽ · Долг: {L.money(b['due'])} ₽")

    def _del_row(self, table, fn):
        i = self._cur_id(table)
        if i:
            fn(i)
            self.load_money()

    def add_time(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("Работа по делу")
        f = QFormLayout(dlg)
        de = date_edit()
        hours = QDoubleSpinBox()
        hours.setRange(0, 1000)
        hours.setDecimals(2)
        hours.setValue(1)
        rate = money_edit(self.fields["rate"].value())
        fixed = money_edit(0)
        desc = QLineEdit()
        desc.setPlaceholderText("Подготовка отзыва на иск")
        f.addRow("Дата", de)
        f.addRow("Часы", hours)
        f.addRow("Ставка за час", rate)
        f.addRow("Или фикс. сумма", fixed)
        f.addRow("Работа", desc)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        f.addRow(bb)
        if dlg.exec() == QDialog.Accepted:
            db().add_time(self.cid, qdate(de), hours.value(), desc.text(), rate.value(), fixed.value())
            self.load_money()

    def add_payment(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("Оплата")
        f = QFormLayout(dlg)
        de, am, note = date_edit(), money_edit(0), QLineEdit()
        f.addRow("Дата", de)
        f.addRow("Сумма", am)
        f.addRow("Комментарий", note)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        f.addRow(bb)
        if dlg.exec() == QDialog.Accepted:
            db().add_payment(self.cid, qdate(de), am.value(), note.text())
            self.load_money()

    def make_act(self):
        entries = [dict(date=CS.ru(e["date"]), description=e["description"], hours=e["hours"], rate=e["rate"],
                        amount=e["amount"]) for e in db().time_entries(self.cid)]
        if not entries:
            QMessageBox.information(self, M.APP_NAME, "Добавьте хотя бы одну работу.")
            return
        c = db().case(self.cid)
        executor, ok = QInputDialog.getText(self, "Акт", "Исполнитель (адвокат, ФИО):",
                                            text=M.settings().value("executor", ""))
        if not ok:
            return
        M.settings().setValue("executor", executor)
        p, _ = QFileDialog.getSaveFileName(self, "Акт", os.path.join(c.get("folder") or str(Path.home() / "Documents"),
                                           L.clean_filename(f"Акт — {c['title']}") + ".docx"), "Word (*.docx)")
        if p:
            L.act_docx(p, c, entries, executor=executor)
            db().add_doc(self.cid, p)
            self.load_docs()
            QDesktopServices.openUrl(QUrl.fromLocalFile(p))

    # ------------------------------------------------------------ выписки
    def load_quotes(self):
        self.l_quotes.clear()
        for q in db().quotes(self.cid):
            src = f"{q['source']}, л. {q['page']}" if q["page"] else q["source"]
            it = QListWidgetItem(f"«{q['text']}»\n— {src}")
            it.setData(Qt.UserRole, q["id"])
            it.setData(Qt.UserRole + 1, (q["text"], src))
            self.l_quotes.addItem(it)

    def _sel_quotes(self):
        items = self.l_quotes.selectedItems() or [self.l_quotes.item(i) for i in range(self.l_quotes.count())]
        return [it.data(Qt.UserRole + 1) for it in items]

    def copy_quotes(self):
        QApplication.clipboard().setText("\n\n".join(f"«{t}» ({s})" for t, s in self._sel_quotes()))
        self.main.msg("Выписки скопированы")

    def quotes_word(self):
        import docx
        qs = self._sel_quotes()
        if not qs:
            return
        c = db().case(self.cid)
        p, _ = QFileDialog.getSaveFileName(self, "Выписки", os.path.join(c.get("folder") or str(Path.home() / "Documents"),
                                           L.clean_filename(f"Выписки — {c['title']}") + ".docx"), "Word (*.docx)")
        if p:
            d = docx.Document()
            d.add_heading(f"Выписки по делу: {c['title']}", 1)
            for t, s in qs:
                d.add_paragraph(f"«{t}» ({s})")
            d.save(p)
            QDesktopServices.openUrl(QUrl.fromLocalFile(p))

    def del_quote(self):
        for it in self.l_quotes.selectedItems():
            db().delete_quote(it.data(Qt.UserRole))
        self.load_quotes()


# =============================================================================
#  Пакет в суд / на почту
# =============================================================================
class PackageDialog(QDialog):
    def __init__(self, main, paths=()):
        super().__init__(main)
        self.main = main
        self.setWindowTitle("Пакет в суд / на почту")
        self.resize(900, 640)
        v = QVBoxLayout(self)
        v.addLayout(title_row("Пакет документов", "package", big=True))
        f = QFormLayout()
        self.portal = QComboBox()
        self.keys = list(D.PORTALS)
        self.portal.addItems([D.PORTALS[k]["title"] for k in self.keys])
        self.pnote = QLabel()
        self.pnote.setWordWrap(True)
        self.pnote.setObjectName("hint")
        f.addRow("Куда", self.portal)
        f.addRow("", self.pnote)
        v.addLayout(f)
        self.t = QTableWidget(0, 4)
        self.t.setHorizontalHeaderLabels(["Документ (как в перечне приложений)", "Листов", "Экз.", "Файл"])
        self.t.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.t.horizontalHeader().setSectionResizeMode(3, QHeaderView.Interactive)
        self.t.verticalHeader().setVisible(False)
        self.t.setSelectionBehavior(QAbstractItemView.SelectRows)
        v.addWidget(self.t, 1)
        r = QHBoxLayout()
        for text, fn in (("+ Файлы…", self.add_files), ("+ Текущий документ", self.add_current), ("▲", lambda: self.move(-1)),
                         ("▼", lambda: self.move(1)), ("Убрать", lambda: self.t.removeRow(self.t.currentRow()))):
            b = QPushButton(text)
            b.clicked.connect(fn)
            r.addWidget(b)
        r.addStretch(1)
        hint = QLabel("Первая строка — основной документ (иск, жалоба, письмо)")
        hint.setObjectName("hint")
        r.addWidget(hint)
        v.addLayout(r)
        g = QGridLayout()
        self.c_prefix = QCheckBox("Номер по порядку в имени файла (01., 02., …)")
        self.c_prefix.setChecked(True)
        self.c_list = QCheckBox("Добавить перечень приложений последней страницей основного документа")
        self.c_duplex = QCheckBox("Двусторонняя печать (листов = страниц / 2)")
        self.c_combined = QCheckBox("Дополнительно — весь пакет одним файлом с закладками (для себя)")
        self.c_combined.setChecked(True)
        self.c_duplex.toggled.connect(self.recount)
        for i, c in enumerate((self.c_prefix, self.c_list, self.c_duplex, self.c_combined)):
            g.addWidget(c, i // 2, i % 2)
        v.addLayout(g)
        fo = QHBoxLayout()
        fo.addWidget(QLabel("Сохранить в папку:"))
        self.out = QLineEdit(os.path.join(main.default_dir(), "Пакет " + dt.date.today().strftime("%d.%m.%Y")))
        fo.addWidget(self.out, 1)
        b = _small_btn("…")
        b.setFixedWidth(34)
        b.clicked.connect(self.pick_out)
        fo.addWidget(b)
        v.addLayout(fo)
        bb = QHBoxLayout()
        b107 = QPushButton("Опись ф. 107 из списка…")
        b107.clicked.connect(self.to_f107)
        bl = QPushButton("Копировать перечень")
        bl.clicked.connect(self.copy_list)
        bb.addWidget(b107)
        bb.addWidget(bl)
        bb.addStretch(1)
        bc = QPushButton("Закрыть")
        bc.clicked.connect(self.reject)
        bg = QPushButton("Собрать пакет")
        bg.setObjectName("primary")
        bg.clicked.connect(self.build)
        bb.addWidget(bc)
        bb.addWidget(bg)
        v.addLayout(bb)
        self.portal.currentIndexChanged.connect(self.on_portal)
        self.portal.setCurrentIndex(int(M.settings().value("last_portal", 0) or 0))
        self.on_portal()
        for p in paths:
            self.add_path(p)

    def on_portal(self, *_):
        P = D.PORTALS[self.keys[self.portal.currentIndex()]]
        self.pnote.setText(P["note"] + f" Форматы: {P['formats']}.")
        M.settings().setValue("last_portal", self.portal.currentIndex())

    def pick_out(self):
        p = QFileDialog.getExistingDirectory(self, "Папка для пакета", self.out.text())
        if p:
            self.out.setText(os.path.join(p, "Пакет " + dt.date.today().strftime("%d.%m.%Y")))

    def add_path(self, p, title=None, pages=None):
        if pages is None:
            try:
                d = fitz.open(p) if p.lower().endswith(".pdf") else None
                pages = d.page_count if d else 1
            except Exception:
                pages = 1
        r = self.t.rowCount()
        self.t.insertRow(r)
        self.t.setItem(r, 0, QTableWidgetItem(title or Path(p).stem))
        sp = QSpinBox()
        sp.setRange(1, 100000)
        sp.setProperty("pages", pages)
        sp.setValue(L.count_sheets(pages, self.c_duplex.isChecked()))
        self.t.setCellWidget(r, 1, sp)
        cp = QSpinBox()
        cp.setRange(1, 100)
        self.t.setCellWidget(r, 2, cp)
        it = QTableWidgetItem(Path(p).name)
        it.setData(Qt.UserRole, p)
        it.setToolTip(p)
        it.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
        self.t.setItem(r, 3, it)

    def recount(self):
        for r in range(self.t.rowCount()):
            sp = self.t.cellWidget(r, 1)
            sp.setValue(L.count_sheets(int(sp.property("pages") or 1), self.c_duplex.isChecked()))

    def add_files(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Документы", self.main.default_dir(), M.OPEN_FILTER)
        for p in paths:
            self.add_path(p)

    def add_current(self):
        if not self.main.doc.page_count:
            return
        import tempfile
        p = os.path.join(tempfile.mkdtemp(prefix="pdfm_"), (self.main.base_name() or "Документ") + ".pdf")
        self.main.doc.save(p)
        self.add_path(p, self.main.base_name())

    def move(self, step):
        r = self.t.currentRow()
        n = r + step
        if r < 0 or not 0 <= n < self.t.rowCount():
            return
        rows = self.items()
        rows[r], rows[n] = rows[n], rows[r]
        self.t.setRowCount(0)
        for it in rows:
            self.add_path(it["path"], it["title"], it["pages"])
            self.t.cellWidget(self.t.rowCount() - 1, 1).setValue(it["sheets"])
            self.t.cellWidget(self.t.rowCount() - 1, 2).setValue(it["copies"])
        self.t.selectRow(n)

    def items(self):
        out = []
        for r in range(self.t.rowCount()):
            out.append(dict(title=self.t.item(r, 0).text().strip() or "Документ",
                            sheets=self.t.cellWidget(r, 1).value(), copies=self.t.cellWidget(r, 2).value(),
                            path=self.t.item(r, 3).data(Qt.UserRole),
                            pages=int(self.t.cellWidget(r, 1).property("pages") or 1)))
        return out

    def copy_list(self):
        lines = L.attachments_text(self.items())
        QApplication.clipboard().setText("Приложения:\n" + "\n".join(lines))
        QMessageBox.information(self, M.APP_NAME, "Перечень приложений скопирован:\n\n" + "\n".join(lines))

    def to_f107(self):
        rows = [(f"{it['title']} на {it['sheets']} л.", it["copies"], 1) for it in self.items()]
        F107Dialog(self, rows).exec()

    def build(self):
        items = self.items()
        if not items:
            return
        out = self.out.text().strip()
        if os.path.isdir(out) and os.listdir(out):
            if QMessageBox.question(self, M.APP_NAME, "Папка не пустая. Файлы с такими же именами будут "
                                    "перезаписаны. Продолжить?") != QMessageBox.Yes:
                return
        res = self.main.run("Сборка пакета…", L.build_package, items, self.keys[self.portal.currentIndex()], out,
                            number_prefix=self.c_prefix.isChecked(), add_list=self.c_list.isChecked(),
                            combined=self.c_combined.isChecked(), password_cb=self.main.ask_password)
        if res is M.FAILED:
            return
        lines = [f"• {os.path.basename(p)} — {n} стр., {s / 1048576:.1f} МБ" for p, n, s in res["files"]]
        text = "Готово. Файлы:\n" + "\n".join(lines)
        if res["warnings"]:
            text += "\n\nОбратите внимание:\n" + "\n".join("• " + w for w in res["warnings"])
        self.main.done(text, res["files"][0][0] if res["files"] else out, open_file=False)


# =============================================================================
#  Опись ф. 107
# =============================================================================
class F107Dialog(QDialog):
    def __init__(self, parent, rows=()):
        super().__init__(parent)
        self.setWindowTitle("Опись вложения ф. 107")
        self.resize(820, 620)
        v = QVBoxLayout(self)
        v.addLayout(title_row("Опись вложения ф. 107", "f107", big=True))
        s = M.settings()
        f = QFormLayout()
        self.kind = QComboBox()
        self.kind.setEditable(True)
        self.kind.addItems(L.F107_KINDS)
        self.to = QLineEdit(s.value("f107_to", ""))
        self.to.setPlaceholderText("Индекс, город, улица, дом, офис")
        self.rcpt = QLineEdit(s.value("f107_rcpt", ""))
        self.rcpt.setPlaceholderText("Арбитражный суд … / ООО «…»")
        self.sender = QLineEdit(s.value("f107_sender", ""))
        self.sender.setPlaceholderText("ФИО или организация отправителя")
        f.addRow("Вложения в", self.kind)
        f.addRow("Куда", self.to)
        f.addRow("На имя", self.rcpt)
        f.addRow("Отправитель", self.sender)
        v.addLayout(f)
        self.t = QTableWidget(0, 3)
        self.t.setHorizontalHeaderLabels(["Наименование предметов", "Кол-во", "Ценность, руб."])
        self.t.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.t.verticalHeader().setVisible(True)
        v.addWidget(self.t, 1)
        r = QHBoxLayout()
        for text, fn in (("+ Строка", lambda: self.add_row("", 1, 1)), ("Убрать", lambda: self.t.removeRow(self.t.currentRow()))):
            b = QPushButton(text)
            b.clicked.connect(fn)
            r.addWidget(b)
        r.addStretch(1)
        hint = QLabel("Пустая ценность — прочерк")
        hint.setObjectName("hint")
        r.addWidget(hint)
        v.addLayout(r)
        bb = QHBoxLayout()
        bb.addStretch(1)
        bc = QPushButton("Закрыть")
        bc.clicked.connect(self.reject)
        bs = QPushButton("Сохранить PDF…")
        bs.setObjectName("primary")
        bs.clicked.connect(self.save)
        bb.addWidget(bc)
        bb.addWidget(bs)
        v.addLayout(bb)
        for row in rows:
            self.add_row(*row)
        if not rows:
            self.add_row("", 1, 1)

    def add_row(self, name, q, val):
        r = self.t.rowCount()
        self.t.insertRow(r)
        self.t.setItem(r, 0, QTableWidgetItem(str(name)))
        self.t.setItem(r, 1, QTableWidgetItem(str(q)))
        self.t.setItem(r, 2, QTableWidgetItem("" if val in (None, "") else str(val)))

    def save(self):
        items = []
        for r in range(self.t.rowCount()):
            name = (self.t.item(r, 0) or QTableWidgetItem("")).text().strip()
            if not name:
                continue
            q = (self.t.item(r, 1) or QTableWidgetItem("1")).text().strip() or "1"
            val = (self.t.item(r, 2) or QTableWidgetItem("")).text().strip().replace(",", ".")
            try:
                items.append((name, int(q), float(val) if val else None))
            except ValueError:
                QMessageBox.warning(self, M.APP_NAME, f"Строка {r + 1}: количество и ценность — числа.")
                return
        if not items:
            return
        s = M.settings()
        s.setValue("f107_to", self.to.text())
        s.setValue("f107_rcpt", self.rcpt.text())
        s.setValue("f107_sender", self.sender.text())
        p, _ = QFileDialog.getSaveFileName(self, "Опись ф. 107", os.path.join(str(Path.home() / "Documents"),
                                           "Опись вложения ф107.pdf"), "PDF (*.pdf)")
        if not p:
            return
        if not p.lower().endswith(".pdf"):
            p += ".pdf"
        try:
            L.f107_pdf(items, self.kind.currentText(), self.to.text(), self.rcpt.text(), self.sender.text(), out=p)
        except Exception as e:
            QMessageBox.warning(self, M.APP_NAME, str(e))
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(p))


# =============================================================================
#  Проверка перед подачей
# =============================================================================
class PreflightDialog(QDialog):
    ICON = {"error": "⛔", "warn": "⚠️", "info": "ℹ️", "ok": "✅"}

    def __init__(self, main):
        super().__init__(main)
        self.main = main
        self.setWindowTitle("Проверка перед подачей")
        self.resize(720, 460)
        v = QVBoxLayout(self)
        v.addLayout(title_row("Проверка перед подачей", "preflight", big=True))
        r = QHBoxLayout()
        r.addWidget(QLabel("Требования:"))
        self.portal = QComboBox()
        self.keys = [None] + list(D.PORTALS)
        self.portal.addItems(["Общие"] + [D.PORTALS[k]["title"] for k in self.keys[1:]])
        r.addWidget(self.portal, 1)
        v.addLayout(r)
        self.list = QListWidget()
        self.list.setWordWrap(True)
        self.list.itemDoubleClicked.connect(self.goto)
        v.addWidget(self.list, 1)
        self.portal.currentIndexChanged.connect(self.check)
        self.portal.setCurrentIndex(0)
        QTimer.singleShot(0, self.check)

    def check(self, *_):
        self.list.clear()
        size = os.path.getsize(self.main.path) if self.main.path and not self.main.modified else None
        res = L.preflight(self.main.doc, self.keys[self.portal.currentIndex()], size)
        for lvl, page, text in res:
            it = QListWidgetItem(f"{self.ICON[lvl]}  {text}")
            it.setData(Qt.UserRole, page)
            self.list.addItem(it)

    def goto(self, it):
        p = it.data(Qt.UserRole)
        if p:
            self.main.pages.clearSelection()
            self.main.pages.item(p - 1).setSelected(True)
            self.main.pages.scrollToItem(self.main.pages.item(p - 1))


# =============================================================================
#  Обезличивание
# =============================================================================
class AnonymizeDialog(QDialog):
    def __init__(self, main):
        super().__init__(main)
        self.main = main
        self.setWindowTitle("Обезличивание (152-ФЗ)")
        self.resize(760, 640)
        v = QVBoxLayout(self)
        v.addLayout(title_row("Обезличивание персональных данных", "anonymize", big=True))
        g = QGridLayout()
        self.checks = {}
        for i, (k, (label, _, _)) in enumerate(L.ANON_PATTERNS.items()):
            c = QCheckBox(label)
            c.setChecked(k not in ("name_patr",))
            self.checks[k] = c
            g.addWidget(c, i // 2, i % 2)
        v.addWidget(card(g))
        f = QFormLayout()
        self.custom = QLineEdit()
        self.custom.setPlaceholderText("Свои слова через запятую: Ромашка, Иванова, 1234567")
        self.mode = QComboBox()
        self.mode.addItems(L.ANON_MODES)
        self.meta = QCheckBox("Очистить свойства документа (автор, название)")
        self.meta.setChecked(True)
        f.addRow("Ещё скрыть", self.custom)
        f.addRow("Как скрыть", self.mode)
        f.addRow("", self.meta)
        v.addLayout(f)
        rb = QHBoxLayout()
        b = QPushButton("Найти")
        b.clicked.connect(self.find)
        rb.addWidget(b)
        self.cnt = QLabel()
        rb.addWidget(self.cnt, 1)
        v.addLayout(rb)
        self.list = QListWidget()
        v.addWidget(self.list, 1)
        bb = QHBoxLayout()
        bb.addStretch(1)
        bc = QPushButton("Отмена")
        bc.clicked.connect(self.reject)
        self.bgo = QPushButton("Скрыть отмеченное")
        self.bgo.setObjectName("primary")
        self.bgo.setEnabled(False)
        self.bgo.clicked.connect(self.apply)
        bb.addWidget(bc)
        bb.addWidget(self.bgo)
        v.addLayout(bb)

    def find(self):
        keys = [k for k, c in self.checks.items() if c.isChecked()]
        custom = [w.strip() for w in self.custom.text().split(",") if w.strip()]
        found = L.find_personal(self.main.doc, keys, custom)
        self.list.clear()
        seen = {}
        for pno, hits in found.items():
            for s, tag in hits:
                seen.setdefault((s, tag), []).append(pno + 1)
        for (s, tag), pages in sorted(seen.items(), key=lambda x: (x[0][1], x[0][0])):
            it = QListWidgetItem(f"{tag}  {s.replace(chr(10), ' ')}   — стр. {L.C_ranges(pages)}")
            it.setData(Qt.UserRole, s)
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked)
            self.list.addItem(it)
        self.cnt.setText(f"Найдено: {len(seen)} уникальных фрагментов" if seen else "Ничего не найдено")
        self.bgo.setEnabled(bool(seen))

    def apply(self):
        words = [self.list.item(i).data(Qt.UserRole) for i in range(self.list.count())
                 if self.list.item(i).checkState() == Qt.Checked]
        if not words:
            return
        self.main.push_undo()
        n = self.main.run("Обезличивание…", L.anonymize, self.main.doc, [], words, self.mode.currentText(),
                          self.meta.isChecked())
        if n is M.FAILED:
            return
        self.main.after_change()
        self.accept()
        self.main.done(f"Скрыто фрагментов: {n}. Данные удалены из текста безвозвратно.\n"
                       "Просмотрите документ и сохраните его под новым именем (Файл → Сохранить как).")


# =============================================================================
#  Поиск по документам
# =============================================================================
class SearchDialog(QDialog):
    def __init__(self, main, paths=()):
        super().__init__(main)
        self.main = main
        self.paths = list(paths)
        self.setWindowTitle("Поиск по документам")
        self.resize(860, 560)
        v = QVBoxLayout(self)
        v.addLayout(title_row("Поиск по документам", "case_search", big=True))
        r = QHBoxLayout()
        self.q = QLineEdit()
        self.q.setPlaceholderText("Что ищем: «неустойка», «акт сверки», номер договора…")
        self.q.returnPressed.connect(self.search)
        r.addWidget(self.q, 1)
        b = QPushButton("Найти")
        b.setObjectName("primary")
        b.clicked.connect(self.search)
        r.addWidget(b)
        v.addLayout(r)
        r2 = QHBoxLayout()
        self.src = QLabel()
        r2.addWidget(self.src, 1)
        for text, fn in (("Файлы…", self.pick_files), ("Папка…", self.pick_folder)):
            bb = QPushButton(text)
            bb.clicked.connect(fn)
            r2.addWidget(bb)
        v.addLayout(r2)
        self.t = QTableWidget(0, 3)
        self.t.setHorizontalHeaderLabels(["Файл", "Стр.", "Фрагмент"])
        self.t.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.t.verticalHeader().setVisible(False)
        self.t.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.t.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.t.cellDoubleClicked.connect(self.open_hit)
        v.addWidget(self.t, 1)
        self.foot = QLabel()
        self.foot.setWordWrap(True)
        self.foot.setObjectName("hint")
        v.addWidget(self.foot)
        self.update_src()

    def update_src(self):
        self.src.setText(f"Документов для поиска: {len(self.paths)}")

    def pick_files(self):
        p, _ = QFileDialog.getOpenFileNames(self, "Файлы", self.main.default_dir(), M.OPEN_FILTER)
        if p:
            self.paths = p
            self.update_src()

    def pick_folder(self):
        d = QFileDialog.getExistingDirectory(self, "Папка", self.main.default_dir())
        if d:
            self.paths = [str(f) for f in sorted(Path(d).rglob("*")) if f.suffix.lower() in (".pdf", ".docx")]
            self.update_src()

    def search(self):
        q = self.q.text().strip()
        if not q or not self.paths:
            return
        res = self.main.run("Поиск…", L.search_files, [p for p in self.paths if os.path.exists(p)], q)
        if res is M.FAILED:
            return
        hits, no_text = res
        self.t.setRowCount(0)
        for p, pg, snip in hits:
            r = self.t.rowCount()
            self.t.insertRow(r)
            it = QTableWidgetItem(Path(p).name)
            it.setData(Qt.UserRole, p)
            self.t.setItem(r, 0, it)
            self.t.setItem(r, 1, QTableWidgetItem(str(pg)))
            self.t.setItem(r, 2, QTableWidgetItem(snip))
        self.t.resizeColumnToContents(0)
        foot = f"Найдено: {len(hits)}."
        if no_text:
            foot += " Без текстового слоя (нужен OCR): " + ", ".join(Path(p).name for p in no_text[:8])
        self.foot.setText(foot)

    def open_hit(self, row, _c):
        p = self.t.item(row, 0).data(Qt.UserRole)
        pg = int(self.t.item(row, 1).text())
        self.main.open_external(p, pg - 1)


# =============================================================================
#  Шаблоны
# =============================================================================
def ensure_sample_templates():
    d = templates_dir()
    if any(Path(d).glob("*.docx")):
        return
    import docx
    from docx.shared import Pt
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    samples = {
        "Ходатайство об ознакомлении с материалами дела": [
            ("right", "В {Суд}\nСудье {Судья}\n\nДело № {Номер_дела}\n\nОт: {Доверитель}\nПредставитель: {Представитель}"),
            ("center", "\nХОДАТАЙСТВО\nоб ознакомлении с материалами дела"),
            ("just", "В производстве {Суд} находится дело № {Номер_дела} по иску {Доверитель} к {Оппонент}. "
                     "На основании ч. 1 ст. 41 АПК РФ (ст. 35 ГПК РФ) прошу предоставить возможность ознакомиться "
                     "с материалами дела, в том числе путём фотографирования."),
            ("left", "\n{Дата}\t\t\t\t\t\t____________ / {Представитель}"),
        ],
        "Ходатайство об отложении судебного заседания": [
            ("right", "В {Суд}\nСудье {Судья}\n\nДело № {Номер_дела}\n\nОт: {Доверитель}"),
            ("center", "\nХОДАТАЙСТВО\nоб отложении судебного заседания"),
            ("just", "Судебное заседание по делу № {Номер_дела} назначено на {Дата_заседания}. "
                     "Прошу отложить судебное заседание в связи с {Причина}."),
            ("left", "\n{Дата}\t\t\t\t\t\t____________ / {Представитель}"),
        ],
    }
    for name, paras in samples.items():
        doc = docx.Document()
        st = doc.styles["Normal"]
        st.font.name = "Times New Roman"
        st.font.size = Pt(14)
        for al, text in paras:
            p = doc.add_paragraph(text)
            p.alignment = {"right": WD_ALIGN_PARAGRAPH.RIGHT, "center": WD_ALIGN_PARAGRAPH.CENTER,
                           "just": WD_ALIGN_PARAGRAPH.JUSTIFY, "left": WD_ALIGN_PARAGRAPH.LEFT}[al]
            if al == "center":
                for r in p.runs:
                    r.bold = True
        doc.save(os.path.join(d, name + ".docx"))


class TemplateDialog(QDialog):
    def __init__(self, main, cid=None):
        super().__init__(main)
        self.main = main
        self.setWindowTitle("Документ по шаблону")
        self.resize(720, 620)
        ensure_sample_templates()
        v = QVBoxLayout(self)
        v.addLayout(title_row("Документ по шаблону", "template", big=True))
        f = QFormLayout()
        self.tpl = QComboBox()
        self.case = QComboBox()
        self.case.addItem("— без дела —", None)
        for c in db().cases():
            self.case.addItem(c["title"] + (f" · {c['number']}" if c["number"] else ""), c["id"])
        if cid:
            self.case.setCurrentIndex(max(0, self.case.findData(cid)))
        rt = QHBoxLayout()
        rt.addWidget(self.tpl, 1)
        bo = QPushButton("Открыть папку шаблонов")
        bo.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(templates_dir())))
        rt.addWidget(bo)
        br = _small_btn("⟳")
        br.setFixedWidth(34)
        br.setToolTip("Обновить список")
        br.clicked.connect(self.load_templates)
        rt.addWidget(br)
        f.addRow("Шаблон", rt)
        f.addRow("Дело", self.case)
        v.addLayout(f)
        self.form_box = QWidget()
        self.form = QFormLayout(self.form_box)
        sc = QScrollArea()
        sc.setWidget(self.form_box)
        sc.setWidgetResizable(True)
        v.addWidget(sc, 1)
        self.c_pdf = QCheckBox("Сразу сделать и PDF (нужен MS Office или LibreOffice)")
        v.addWidget(self.c_pdf)
        bb = QHBoxLayout()
        bb.addStretch(1)
        bc = QPushButton("Закрыть")
        bc.clicked.connect(self.reject)
        bg = QPushButton("Создать документ")
        bg.setObjectName("primary")
        bg.clicked.connect(self.make)
        bb.addWidget(bc)
        bb.addWidget(bg)
        v.addLayout(bb)
        self.tpl.currentIndexChanged.connect(self.build_form)
        self.case.currentIndexChanged.connect(self.build_form)
        self.load_templates()

    def load_templates(self):
        self.tpl.blockSignals(True)
        self.tpl.clear()
        for p in sorted(Path(templates_dir()).glob("*.docx")):
            if not p.name.startswith("~$"):
                self.tpl.addItem(p.stem, str(p))
        self.tpl.addItem("Другой файл…", "__other__")
        self.tpl.blockSignals(False)
        self.build_form()

    def build_form(self, *_):
        if self.tpl.currentData() == "__other__":
            p, _ = QFileDialog.getOpenFileName(self, "Шаблон Word", templates_dir(), "Word (*.docx)")
            if not p:
                self.tpl.setCurrentIndex(0)
                return
            self.tpl.insertItem(0, Path(p).stem, p)
            self.tpl.setCurrentIndex(0)
            return
        while self.form.rowCount():
            self.form.removeRow(0)
        self.edits = {}
        path = self.tpl.currentData()
        if not path:
            return
        try:
            fields = L.template_fields(path)
        except Exception as e:
            self.form.addRow(QLabel(f"Не удалось прочитать шаблон: {e}"))
            return
        vals = db().template_values(self.case.currentData()) if self.case.currentData() else \
            {"Дата": dt.date.today().strftime("%d.%m.%Y")}
        vals.setdefault("Представитель", M.settings().value("executor", ""))
        if not fields:
            self.form.addRow(QLabel("В шаблоне нет полей {…}"))
        for name in fields:
            e = QLineEdit(str(vals.get(name, "")))
            self.edits[name] = e
            self.form.addRow(name.replace("_", " "), e)

    def make(self):
        path = self.tpl.currentData()
        if not path or path == "__other__":
            return
        values = {k: e.text() for k, e in self.edits.items()}
        if values.get("Представитель"):
            M.settings().setValue("executor", values["Представитель"])
        cid = self.case.currentData()
        folder = (db().case(cid) or {}).get("folder") if cid else ""
        name = Path(path).stem + (f" — {values.get('Номер_дела')}" if values.get("Номер_дела") else "")
        out, _ = QFileDialog.getSaveFileName(self, "Сохранить документ", os.path.join(
            folder or self.main.default_dir(), L.clean_filename(name) + ".docx"), "Word (*.docx)")
        if not out:
            return
        if not out.lower().endswith(".docx"):
            out += ".docx"
        try:
            L.fill_template(path, values, out)
        except Exception as e:
            self.main.error("Не удалось заполнить шаблон", e)
            return
        if cid:
            db().add_doc(cid, out)
        result = out
        if self.c_pdf.isChecked():
            pdf = out[:-5] + ".pdf"
            try:
                C.office_to_pdf(out, pdf)
                result = pdf
                if cid:
                    db().add_doc(cid, pdf)
            except Exception as e:
                self.main.error("PDF не создан (нужен MS Office или LibreOffice)", e)
        self.main.refresh_cases()
        QDesktopServices.openUrl(QUrl.fromLocalFile(result))
        self.accept()


# =============================================================================
#  Выписка
# =============================================================================
def save_quote(main, text, page_no):
    if not text:
        QMessageBox.information(main, M.APP_NAME, "В выделенной области нет текста. Если это скан — сначала "
                                                  "распознайте его (OCR).")
        return
    dlg = QDialog(main)
    dlg.setWindowTitle("Выписка")
    dlg.resize(560, 360)
    v = QVBoxLayout(dlg)
    ed = QPlainTextEdit(text)
    v.addWidget(ed, 1)
    f = QFormLayout()
    src = QLineEdit(main.base_name() or "Документ")
    pg = QSpinBox()
    pg.setRange(0, 100000)
    pg.setValue(page_no)
    f.addRow("Источник", src)
    f.addRow("Лист / стр.", pg)
    v.addLayout(f)
    bb = QHBoxLayout()
    b_copy = QPushButton("Только копировать")
    b_save = QPushButton("Сохранить в дело…")
    b_save.setObjectName("primary")
    bb.addWidget(b_copy)
    bb.addStretch(1)
    bb.addWidget(b_save)
    v.addLayout(bb)

    def copy():
        QApplication.clipboard().setText(f"«{ed.toPlainText().strip()}» ({src.text()}, л. {pg.value()})")
        main.msg("Цитата скопирована")
        dlg.accept()

    def save():
        cid = main.last_case or pick_case(dlg)
        if not cid:
            return
        db().add_quote(cid, ed.toPlainText().strip(), src.text(), pg.value())
        main.last_case = cid
        main.refresh_cases()
        main.msg("Выписка сохранена в дело")
        dlg.accept()
    b_copy.clicked.connect(copy)
    b_save.clicked.connect(save)
    dlg.exec()


# =============================================================================
#  Инструменты главного окна (вызываются как tool_<ключ>(main))
# =============================================================================
def tool_package(main):
    PackageDialog(main).exec()


def tool_f107(main):
    F107Dialog(main).exec()


def tool_preflight(main):
    if main.need_doc():
        PreflightDialog(main).exec()


def tool_anonymize(main):
    if main.need_doc():
        AnonymizeDialog(main).exec()


def tool_case_search(main):
    paths = []
    if main.cases_page and main.cases_page.cid:
        paths = [d["path"] for d in db().docs(main.cases_page.cid)]
    SearchDialog(main, paths).exec()


def tool_template(main, cid=None):
    TemplateDialog(main, cid or (main.cases_page.cid if main.cases_page else None)).exec()


def tool_quote(main):
    if main.need_doc():
        main.open_editor(mode="quote")


def tool_compare_ed(main):
    v = M.OptionsDialog.ask(main, "Сравнение редакций", [
        ("old", "Было (старая редакция)", "file", main.path or "", "PDF, Word (*.pdf *.docx *.txt)"),
        ("new", "Стало (новая редакция)", "file", "", "PDF, Word (*.pdf *.docx *.txt)"),
        ("only", "Показывать только изменённые абзацы", "check", False),
    ], ok_text="Сравнить", help="compare_ed")
    if not v or not v["old"] or not v["new"]:
        return
    base = os.path.join(os.path.dirname(v["new"]), f"Сравнение — {Path(v['new']).stem}")
    res = main.run("Сравнение…", lambda progress=None: L.compare_versions(v["old"], v["new"], base, v["only"]))
    if res is M.FAILED:
        return
    hp, pp, st = res
    main.done(f"Изменённых фрагментов: {st['changed']}, добавлено слов: {st['added']}, удалено: {st['deleted']}.\n"
              f"Отчёт: {hp}", pp or hp)
    QDesktopServices.openUrl(QUrl.fromLocalFile(hp))


def tool_sheetnum(main):
    if not main.need_doc():
        return
    v = M.OptionsDialog.ask(main, "Нумерация листов дела", [
        ("start", "Первый номер", "int", 1, (1, 100000)),
        ("per", "Листов в томе (0 — без томов)", "int", 250, (0, 5000)),
        ("pos", "Где ставить номер", "combo", None, L.SHEET_POSITIONS),
        ("size", "Размер цифр", "int", 12, (6, 36)),
        ("duplex", "Двусторонние листы (номер только на лицевой стороне)", "check", False),
        ("restart", "В каждом томе нумерация с 1", "check", True),
        ("split", "Сохранить тома отдельными файлами", "check", False),
        ("cover", "Добавить титульный лист тома", "check", False),
        ("title", "Надпись на титуле", "text", "Дело № ", None),
    ], ok_text="Пронумеровать", help="sheetnum",
        depends={"restart": ("per", lambda t: t not in ("0", "")), "cover": ("split", lambda c: c),
                 "title": ("split", lambda c: c)})
    if not v:
        return
    main.push_undo()
    vols = main.run("Нумерация листов…", L.number_sheets, main.doc, v["start"], v["per"], v["pos"], v["size"], 8,
                    v["duplex"], v["restart"])
    if vols is M.FAILED:
        return
    main.after_change()
    text = f"Пронумеровано. Томов: {len(vols)}.\n" + "\n".join(
        f"Том {i}: стр. {a + 1}–{b + 1}, листы {s1}–{s2}" for i, (a, b, s1, s2) in enumerate(vols, 1))
    if v["split"] and len(vols) >= 1:
        folder = QFileDialog.getExistingDirectory(main, "Папка для томов", main.default_dir())
        if folder:
            for i, (a, b, s1, s2) in enumerate(vols, 1):
                d = fitz.open()
                if v["cover"]:
                    d.insert_pdf(L.volume_cover(v["title"], i, s1, s2))
                d.insert_pdf(main.doc, from_page=a, to_page=b)
                C.save_pdf(d, os.path.join(folder, f"{main.base_name()} — том {i}.pdf"))
            main.done(text + f"\n\nТома сохранены в папку:\n{folder}", folder, open_file=False)
            return
    main.done(text)


def _stamp_templates():
    try:
        return json.loads(M.settings().value("stamp_templates", "") or "{}")
    except Exception:
        return {}


def tool_certify(main):
    if not main.need_doc():
        return
    tpls = _stamp_templates()
    default = "Копия верна\nАдвокат\n____________ Фамилия И.О.\n" + dt.date.today().strftime("%d.%m.%Y")
    names = ["— новый —"] + list(tpls)
    last = M.settings().value("stamp_last", "")
    v = M.OptionsDialog.ask(main, "Штамп заверения", [
        ("tpl", "Шаблон", "combo", last if last in tpls else names[0], names),
        ("lines", "Текст штампа", "multiline", tpls.get(last, default)),
        ("mode", "Где", "combo", None, L.STAMP_MODES),
        ("pos", "Положение", "combo", None, L.STAMP_POSITIONS),
        ("size", "Размер шрифта", "int", 10, (6, 20)),
        ("width", "Ширина штампа, мм", "int", 75, (30, 180)),
        ("frame", "Рамка", "check", True),
        ("color", "Цвет", "combo", None, ["Синий", "Чёрный"]),
        ("sig", "Подпись (PNG, необязательно)", "file", "", "Изображения (*.png *.jpg)"),
        ("bound", "На последней странице — «Прошито, пронумеровано N листов»", "check", False),
        ("save", "Сохранить как шаблон с именем", "text", ""),
    ], ok_text="Поставить штамп", help="certify")
    if not v:
        return
    if v["tpl"] != names[0] and v["lines"] == default:
        v["lines"] = tpls.get(v["tpl"], v["lines"])
    if v["save"].strip():
        tpls[v["save"].strip()] = v["lines"]
        M.settings().setValue("stamp_templates", json.dumps(tpls, ensure_ascii=False))
        M.settings().setValue("stamp_last", v["save"].strip())
    pages = L.stamp_pages(main.doc.page_count, v["mode"])
    sig = None
    if v["sig"]:
        try:
            sig = C.image_bytes(v["sig"])[0]
        except Exception as e:
            return main.error("Не удалось открыть картинку", e)
    color = (0.05, 0.1, 0.55) if v["color"] == "Синий" else (0, 0, 0)
    main.push_undo()

    def work(progress=None):
        L.certify_stamp(main.doc, pages, v["lines"].splitlines(), v["pos"], v["size"], v["width"], 10, v["frame"],
                        color, sig, progress)
        if v["bound"]:
            last_p = main.doc.page_count - 1
            lines = L.bound_stamp_lines(main.doc.page_count, "", "")
            pos = "Внизу слева" if "справа" in v["pos"] else "Внизу справа"
            L.certify_stamp(main.doc, [last_p], lines, pos, v["size"], 70, 10, True, color)
    if main.run("Штамп…", work) is M.FAILED:
        return
    main.after_change()
    main.msg(f"Штамп поставлен на {len(pages)} стр.")


# =============================================================================
#  Напоминания
# =============================================================================
class Reminders:
    def __init__(self, main):
        self.main = main
        self.tray = None
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray = QSystemTrayIcon(main.windowIcon(), main)
            self.tray.setToolTip(M.APP_NAME)
            self.tray.messageClicked.connect(lambda: main.show_cases())
            self.tray.show()
        self.timer = QTimer(main)
        self.timer.setInterval(20 * 60 * 1000)
        self.timer.timeout.connect(self.check)
        self.timer.start()
        QTimer.singleShot(1500, lambda: self.check(startup=True))

    def check(self, startup=False):
        try:
            events = db().events(upcoming_days=1, include_done=False)
        except Exception:
            return
        today = dt.date.today()
        due = [e for e in events if dt.date.fromisoformat(e["date"]) <= today + dt.timedelta(days=1)]
        if not due:
            self.main.set_banner("")
            return
        overdue = [e for e in due if dt.date.fromisoformat(e["date"]) < today]
        todays = [e for e in due if dt.date.fromisoformat(e["date"]) == today]
        tomorrow = [e for e in due if dt.date.fromisoformat(e["date"]) > today]
        parts = []
        if overdue:
            parts.append(f"просрочено: {len(overdue)}")
        if todays:
            parts.append(f"сегодня: {len(todays)}")
        if tomorrow:
            parts.append(f"завтра: {len(tomorrow)}")
        first = (todays or tomorrow or overdue)[0]
        self.main.set_banner(f"🔔  {', '.join(parts).capitalize()} — ближайшее: {first['kind'].lower()} "
                             f"«{first['title']}» ({first['case_title'] or ''})  →  открыть дела")
        new = [e for e in due if not e["notified"]]
        if new and self.tray:
            text = "\n".join(f"{CS.ru(e['date'])} {e['time']} {e['kind']}: {e['title']} ({e['case_title'] or ''})"
                             for e in new[:5])
            self.tray.showMessage("Сроки и заседания", text, QSystemTrayIcon.Information, 15000)
            for e in new:
                db().update_event(e["id"], notified=1)
