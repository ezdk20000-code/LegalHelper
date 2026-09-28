# -*- coding: utf-8 -*-
"""
Обучение для новичков: программа сама показывает стрелкой, куда нажать, и ждёт, пока человек сделает это сам.

Работает на «Учебном деле» с примерами файлов (его создаёт обучение, настоящие дела не трогаются; в конце его
можно удалить вместе с папкой). Шаг засчитывается сам, когда действие выполнено (например, страница
удалена или документ добавлен в PDF дела); у каждого шага есть «Пропустить шаг», у пояснений — «Далее».
Запуск: при первом старте программа предлагает обучение; повторить — «Справка → 🎓 Обучение».

Устройство: поверх окна — полупрозрачная «шторка» с вырезом вокруг нужной кнопки и стрелкой к ней (она
пропускает щелчки мыши насквозь), рядом — окошко-подсказка с текстом и кнопками. Если открыт редактор
страницы (модальное окно), шторка и подсказка переезжают на него.
"""
import os
import shutil
import sys

import pymupdf as fitz
from PySide6.QtCore import Qt, QTimer, QRect, QRectF, QPoint, QPointF
from PySide6.QtGui import QPainter, QColor, QPen, QPainterPath, QPolygonF, QFont
from PySide6.QtWidgets import (QWidget, QFrame, QLabel, QPushButton, QVBoxLayout, QHBoxLayout, QApplication,
                               QMessageBox, QLayout)

TRAIN_TITLE = "Учебное дело (обучение)"
FILES = {"claim": "Исковое заявление.pdf", "contract": "Договор поставки.pdf", "receipt": "Квитанция госпошлины.png"}
EXTRA = "ЛИШНЯЯ СТРАНИЦА"


# --------------------------------------------------------------------------- учебные файлы
def _write(page, rect, text, size=12, bold=False):
    """Текст с переносами и кириллицей (HTML-блок PyMuPDF)."""
    page.insert_htmlbox(fitz.Rect(*rect), f"<div style='font-size:{size}pt;{'font-weight:bold;' if bold else ''}'>"
                                          f"{text}</div>")


def make_training_files(folder):
    os.makedirs(folder, exist_ok=True)
    out = {}
    d = fitz.open()
    p = d.new_page()
    _write(p, (70, 60, 530, 130), "В Арбитражный суд города Москвы<br>Истец: ООО «Ромашка»<br>Ответчик: ООО «Лютик»", 11)
    _write(p, (70, 170, 530, 210), "ИСКОВОЕ ЗАЯВЛЕНИЕ<br>о взыскании задолженности по договору поставки", 14, True)
    _write(p, (70, 240, 530, 760), ("Между истцом и ответчиком заключён договор поставки № 12 от 01.02.2026. Истец "
                                    "поставил товар на сумму 450 000 рублей, ответчик товар принял, но не оплатил. "
                                    "Претензия от 01.04.2026 оставлена без ответа.<br><br>") * 3, 11)
    p = d.new_page()
    _write(p, (70, 60, 530, 400), "На основании изложенного, руководствуясь ст. 309, 310, 516 ГК РФ,<br><br>"
                                  "ПРОШУ:<br>взыскать с ООО «Лютик» в пользу ООО «Ромашка» 450 000 рублей долга.<br><br>"
                                  "Приложение: договор поставки, квитанция об уплате госпошлины.<br><br>"
                                  "Представитель ______________", 11)
    out["claim"] = os.path.join(folder, FILES["claim"])
    d.save(out["claim"])
    d = fitz.open()
    for i, text in enumerate(("ДОГОВОР ПОСТАВКИ № 12<br>г. Москва, 01.02.2026<br><br>1. Поставщик обязуется "
                              "передать товар, а Покупатель — принять и оплатить его в течение 30 дней.",
                              "2. Цена договора — 450 000 рублей.<br>3. Подписи сторон:<br><br>Поставщик ______ "
                              "Покупатель ______",
                              EXTRA + "<br><br>Эта страница попала сюда по ошибке —<br>удалите её (так и учимся).")):
        p = d.new_page()
        _write(p, (70, 70, 530, 500), text, 16 if i == 2 else 12, i == 2)
    out["contract"] = os.path.join(folder, FILES["contract"])
    d.save(out["contract"])
    # «скан» квитанции — картинка, лежащая боком (её учатся поворачивать)
    d = fitz.open()
    p = d.new_page(width=420, height=260)
    p.draw_rect(p.rect, color=(0.5, 0.5, 0.5), fill=(0.97, 0.97, 0.92))
    _write(p, (20, 20, 400, 240), "КВИТАНЦИЯ<br>Госпошлина за подачу иска<br>Сумма: 12 000 руб.<br>Оплачено ✓", 16, True)
    pix = p.get_pixmap(matrix=fitz.Matrix(2, 2).prerotate(-90))
    out["receipt"] = os.path.join(folder, FILES["receipt"])
    pix.save(out["receipt"])
    return out


def create_training_case(main):
    U, CF = main_modules(main)
    db = U.db()
    for c in db.cases():                        # прошлое учебное дело — заменить новым
        if c["title"] == TRAIN_TITLE:
            delete_training_case(main, c["id"], ask=False)
    cid = db.add_case(title=TRAIN_TITLE, client="ООО «Ромашка»", opponent="ООО «Лютик»",
                      court="Арбитражный суд города Москвы", number="А40-00000/2026",
                      notes="Это учебное дело — на нём можно пробовать всё что угодно.")
    folder = CF.ensure_folder(db, cid)
    files = make_training_files(os.path.join(folder, "Файлы для обучения"))
    for key in ("claim", "contract"):
        db.add_doc(cid, files[key])
    main.refresh_cases()
    return cid, files


def delete_training_case(main, cid, ask=True):
    U, CF = main_modules(main)
    db = U.db()
    c = db.case(cid)
    if not c:
        return
    if ask and QMessageBox.question(main, "Обучение", f"Удалить «{c['title']}» вместе с его папкой?") != QMessageBox.Yes:
        return
    for i in reversed(range(len(main.ws))):     # закрыть его документы без вопросов о сохранении
        if main.ws[i].get("case_id") == cid:
            main.ws[i]["modified"] = False
            if i == main.cur_ws:
                main.modified = False
    main._store_ws() if hasattr(main, "_store_ws") else None
    main.ws = [w for w in main.ws if w.get("case_id") != cid] or [main._blank_ws()]
    main._load_ws(0)
    folder = c.get("folder")
    db.delete_case(cid)
    if folder and os.path.isdir(folder) and os.path.basename(folder).startswith("Учебное дело"):
        shutil.rmtree(folder, ignore_errors=True)
    if main.mode_cid == cid:
        main.mode_cid = None
    main.cases_page.cid = None
    main.refresh_cases()
    main.show_home() if hasattr(main, "show_home") else None


def _alive(obj):
    """Объект Qt ещё существует (не удалён вместе с родительским окном)."""
    if obj is None:
        return False
    try:
        import shiboken6
        return shiboken6.isValid(obj)
    except Exception:
        return True


def P_of(main):
    """Модуль главного окна (pdf_master, даже если он запущен как __main__)."""
    return sys.modules[type(main).__module__]


def main_modules(main):
    import legal_ui as U
    import casefile as CF
    return U, CF


# --------------------------------------------------------------------------- геометрия
def wrect(w):
    if w is None or not w.isVisible():
        return None
    return QRect(w.mapToGlobal(QPoint(0, 0)), w.size())


def item_rect(view, item):
    if item is None:
        return None
    r = view.visualItemRect(item)
    if r.isEmpty():
        return None
    return QRect(view.viewport().mapToGlobal(r.topLeft()), r.size())


def tab_rect(bar, i):
    if bar is None or not bar.isVisible() or i < 0:
        return None
    r = bar.tabRect(i)
    return QRect(bar.mapToGlobal(r.topLeft()), r.size())


def table_row_rect(t, row):
    if row is None or row < 0 or not t.isVisible():
        return None
    a = t.visualItemRect(t.item(row, 1))
    r = QRect(0, a.top(), t.viewport().width(), a.height())
    return QRect(t.viewport().mapToGlobal(r.topLeft()), r.size())


# --------------------------------------------------------------------------- шторка со стрелкой
class Spotlight(QWidget):
    def __init__(self):
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowTransparentForInput |
                         Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.hole = None           # в координатах шторки
        self.bubble = None
        self.phase = 0
        self.accent = QColor("#0a84ff")

    def set_state(self, hole, bubble, phase):
        self.hole, self.bubble, self.phase = hole, bubble, phase
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        path = QPainterPath()
        path.addRect(QRectF(self.rect()))
        if self.hole is not None:
            h = QRectF(self.hole).adjusted(-6, -6, 6, 6)
            hp = QPainterPath()
            hp.addRoundedRect(h, 10, 10)
            path = path.subtracted(hp)
        p.fillPath(path, QColor(0, 0, 0, 95))
        if self.hole is not None:
            h = QRectF(self.hole).adjusted(-6, -6, 6, 6)
            glow = 3 + 2 * abs((self.phase % 20) - 10) / 10          # мягкая «пульсация» рамки
            p.setPen(QPen(self.accent, glow))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(h, 10, 10)
            if self.bubble is not None:
                self._arrow(p, QRectF(self.bubble), h)
        p.end()

    def _arrow(self, p, b, h):
        """Стрелка от края подсказки к краю выделенного места."""
        bc, hc = b.center(), h.center()

        def edge(r, towards):
            dx, dy = towards.x() - r.center().x(), towards.y() - r.center().y()
            if dx == 0 and dy == 0:
                return r.center()
            sx = (r.width() / 2) / abs(dx) if dx else float("inf")
            sy = (r.height() / 2) / abs(dy) if dy else float("inf")
            s = min(sx, sy)
            return QPointF(r.center().x() + dx * s, r.center().y() + dy * s)
        a, z = edge(b, hc), edge(h, bc)
        if (a - z).manhattanLength() < 12 or b.intersects(h):
            return
        v = z - a
        ln = max(1.0, (v.x() ** 2 + v.y() ** 2) ** 0.5)
        u = QPointF(v.x() / ln, v.y() / ln)
        tip = z - u * 4
        p.setPen(QPen(self.accent, 4, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(a, tip - u * 10)
        n = QPointF(-u.y(), u.x())
        head = QPolygonF([tip, tip - u * 18 + n * 10, tip - u * 18 - n * 10])
        p.setPen(Qt.NoPen)
        p.setBrush(self.accent)
        p.drawPolygon(head)


class Bubble(QWidget):
    """Окошко-подсказка: прозрачное окно, внутри — скруглённая карточка (углы без белых квадратов)."""

    def __init__(self, tutor):
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_TranslucentBackground)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSizeConstraint(QLayout.SetFixedSize)
        card = QFrame()
        card.setObjectName("tutorbubble")
        card.setFixedWidth(390)
        outer.addWidget(card)
        v = QVBoxLayout(card)
        v.setContentsMargins(18, 14, 18, 14)
        v.setSpacing(8)
        top = QHBoxLayout()
        self.counter = QLabel()
        self.counter.setObjectName("tutorcount")
        top.addWidget(self.counter)
        top.addStretch(1)
        self.b_quit = QPushButton("Пропустить обучение")
        self.b_quit.setObjectName("tutorlink")
        self.b_quit.setCursor(Qt.PointingHandCursor)
        self.b_quit.clicked.connect(tutor.quit)
        top.addWidget(self.b_quit)
        v.addLayout(top)
        self.title = QLabel()
        self.title.setObjectName("tutortitle")
        self.title.setWordWrap(True)
        v.addWidget(self.title)
        self.text = QLabel()
        self.text.setObjectName("tutortext")
        self.text.setWordWrap(True)
        self.text.setTextFormat(Qt.RichText)
        v.addWidget(self.text)
        self.done = QLabel("✓  Отлично, получилось!")
        self.done.setObjectName("tutordone")
        self.done.hide()
        v.addWidget(self.done)
        row = QHBoxLayout()
        self.b_back = QPushButton("← Назад")
        self.b_back.clicked.connect(tutor.back)
        self.b_skip = QPushButton("Пропустить шаг")
        self.b_skip.setObjectName("tutorlink")
        self.b_skip.clicked.connect(tutor.next)
        self.b_next = QPushButton("Далее →")
        self.b_next.setObjectName("primary")
        self.b_next.clicked.connect(tutor.next)
        row.addWidget(self.b_back)
        row.addStretch(1)
        row.addWidget(self.b_skip)
        row.addWidget(self.b_next)
        v.addLayout(row)
        self.extra = QHBoxLayout()
        v.addLayout(self.extra)


# --------------------------------------------------------------------------- шаги
class Step:
    def __init__(self, title, text, target=None, check=None, enter=None, next_text=None):
        self.title, self.text, self.target, self.check, self.enter = title, text, target, check, enter
        self.next_text = next_text


class Tutor:
    def __init__(self, main):
        self.m = main
        self.cid, self.files = None, {}
        self.i = 0
        self.passed = False
        self.spot = Spotlight()
        self.bub = Bubble(self)
        self.host = None
        self.phase = 0
        self.timer = QTimer()
        self.timer.setInterval(120)
        self.timer.timeout.connect(self.tick)
        self.steps = self.build_steps()
        self._restyle()

    def _restyle(self):
        T = self.m_T()
        self.spot.accent = QColor(T.get("accent", "#0a84ff"))
        self.bub.setStyleSheet(f"""
            QFrame#tutorbubble {{ background: {T['panel']}; border: 2px solid {T['accent']}; border-radius: 16px; }}
            QLabel#tutorcount {{ color: {T['muted']}; font-size: 10pt; }}
            QLabel#tutortitle {{ color: {T['text']}; font-size: 15pt; font-weight: 700; }}
            QLabel#tutortext {{ color: {T['text']}; font-size: 12.5pt; }}
            QLabel#tutordone {{ color: {T['success']}; font-size: 12.5pt; font-weight: 700; }}
            QPushButton#tutorlink {{ background: transparent; border: none; color: {T['muted']};
                                     text-decoration: underline; padding: 4px; }}
        """)

    def m_T(self):
        return P_of(self.m).T

    # ---- что где на экране
    def _case_item(self):
        lst = self.m.cases_page.list
        for k in range(lst.count()):
            if lst.item(k).data(Qt.UserRole) == self.cid:
                return lst, lst.item(k)
        return lst, None

    def _doc_row(self, key):
        t = self.m.cases_page.l_docs
        want = os.path.normcase(os.path.abspath(self.files.get(key, "")))
        for r in range(t.rowCount()):
            p = t.row_doc(r)[1]
            if p and os.path.normcase(os.path.abspath(p)) == want:
                return r
        return None

    def _in_pdf(self, key):
        return os.path.normcase(os.path.abspath(self.files[key])) in self.m.case_pdf_sources(self.cid)

    def _page_of(self, key=None, text=None):
        d = self.m.doc
        P = P_of(self.m)
        want = os.path.normcase(os.path.abspath(self.files[key])) if key else None
        for k in range(d.page_count):
            if want and os.path.normcase(P._pdf_key(d, k, "LHSrc") or "") == want:
                return k
            if text and text in d[k].get_text():
                return k
        return None

    def _page_rect(self, k):
        if k is None:
            return None
        it = self.m.pages.item(k)
        if it is None or it.isHidden():
            return None
        return item_rect(self.m.pages, it)

    def _in_case_docs(self):
        return self.m.mode_cid == self.cid and self.m.cases_page.tabs.currentIndex() == self.m.case_tab_keys["docs"]

    def _ed(self):
        return getattr(self.m, "_editor", None)

    def build_steps(self):
        m = self.m
        tabs = lambda: m.cases_page.tabs.tabBar()
        tb = lambda a: wrect(m.toolbar.widgetForAction(a)) or wrect(m.toolbar2.widgetForAction(a))

        def pages_ready():
            m.open_case_tab("docs") if m.mode_cid == self.cid else None

        return [
            Step("Добро пожаловать в LegalHelper!",
                 "Это короткое обучение — минут десять. Я буду показывать <b>стрелкой</b>, куда нажать, а вы "
                 "делаете это сами. Шаг засчитается сам, как только получится.<br><br>Для обучения я создал "
                 "<b>«Учебное дело»</b> с примерами файлов — ваши настоящие дела не пострадают. В конце его можно "
                 "удалить.", next_text="Начать →"),
            Step("1. Выберите дело",
                 "Слева — список ваших дел. Щёлкните по <b>«Учебное дело (обучение)»</b>.",
                 target=lambda: item_rect(*self._case_item()), check=lambda: m.mode_cid == self.cid),
            Step("2. Вкладки дела",
                 "У дела есть вкладки: <b>Обзор</b> (сроки, заметки, напоминания), <b>Документы</b>, "
                 "<b>Подготовить</b> (шаблоны и инструменты), <b>Сроки и заседания</b>, <b>Расчёты</b>, "
                 "<b>Карта дела</b>. Главная работа с файлами — во вкладке «Документы».",
                 target=lambda: wrect(tabs())),
            Step("3. Откройте «Документы»",
                 "Щёлкните по вкладке <b>«Документы»</b>.",
                 target=lambda: tab_rect(tabs(), m.case_tab_keys["docs"]), check=self._in_case_docs),
            Step("4. Документы и «PDF дела»",
                 "Слева — <b>список документов</b> дела. Справа — <b>«PDF дела»</b>: один файл, в который "
                 "собираются все документы дела.<br><br>Дважды щёлкните по <b>«Исковое заявление»</b> — "
                 "оно попадёт в PDF дела.",
                 target=lambda: table_row_rect(m.cases_page.l_docs, self._doc_row("claim")),
                 check=lambda: self._in_pdf("claim"), enter=lambda: m.docs_seg.setCurrentIndex(0)),
            Step("5. Перетащите мышкой",
                 "Теперь <b>зажмите</b> «Договор поставки» левой кнопкой мыши и <b>перетащите вправо</b>, на "
                 "страницы. Отпустите — договор встанет туда, куда отпустили.<br><small>(Можно и двойным "
                 "щелчком.)</small>",
                 target=lambda: table_row_rect(m.cases_page.l_docs, self._doc_row("contract")),
                 check=lambda: self._in_pdf("contract")),
            Step("6. Файл с компьютера",
                 "Файлы с компьютера добавляет кнопка <b>«Добавить»</b>. Нажмите её, откройте папку "
                 "<b>«Файлы для обучения»</b> и выберите <b>«Квитанция госпошлины.png»</b>.",
                 target=lambda: tb(m.a_add), check=lambda: self._in_pdf("receipt")),
            Step("7. Страницы и просмотр",
                 "Это страницы PDF дела. <b>Щёлкните</b> по любой — справа она покажется крупно, чтобы "
                 "прочитать. Колёсико мыши — листать.",
                 target=lambda: wrect(m.pages), enter=pages_ready),
            Step("8. Удалите лишнюю страницу",
                 "В договоре есть страница с надписью <b>«ЛИШНЯЯ СТРАНИЦА»</b>. Щёлкните по ней и нажмите "
                 "<b>«Удалить»</b> над страницами (или клавишу Delete).",
                 target=lambda: self._page_rect(self._scroll_to(self._page_of(text=EXTRA))) or tb(m.a_del),
                 check=lambda: self._page_of(text=EXTRA) is None),
            Step("9. Поверните страницу",
                 "Квитанция лежит боком. Щёлкните по ней и нажмите <b>↻</b> (повернуть вправо) над страницами.",
                 target=lambda: self._page_rect(self._scroll_to(self._page_of("receipt"))) or tb(m.a_rr),
                 check=lambda: (lambda k: k is not None and m.doc[k].rotation % 360 != 0)(self._page_of("receipt"))),
            Step("10. Переставьте страницы",
                 "Порядок меняется мышкой: <b>зажмите страницу и перетащите</b> на новое место. Попробуйте "
                 "перетащить квитанцию в самое начало, перед иском.",
                 target=lambda: wrect(m.pages),
                 check=lambda: (lambda r, c: r is not None and c is not None and r < c)(
                     self._page_of("receipt"), self._page_of("claim"))),
            Step("11. Сверните файл",
                 "Документ из нескольких страниц можно <b>свернуть</b> в «стопку» с названием. Щёлкните "
                 "<b>правой кнопкой</b> по странице договора и выберите <b>«Свернуть файл»</b>.",
                 target=lambda: self._page_rect(self._scroll_to(self._page_of("contract"))),
                 check=lambda: bool(getattr(m, "_heads", {}))),
            Step("12. Меню «Вид»",
                 "<b>«Вид ▾»</b> — размер страниц (мини-значки, маленькие, средние, крупные) и крупный "
                 "просмотр (клавиша F3). Можете попробовать и нажать «Далее».",
                 target=lambda: wrect(getattr(m, "view_btn", None))),
            Step("13. Редактор страницы",
                 "Теперь впишем текст прямо в PDF. Щёлкните по странице <b>иска</b> и нажмите "
                 "<b>«✎ Редактировать»</b> (или дважды щёлкните по странице).",
                 target=lambda: tb(m.a_edit), check=lambda: self._ed() is not None),
            Step("14. Инструменты редактора",
                 "Слева — инструменты: <b>текст</b>, изменить текст, <b>маркер</b>, картинка, <b>подпись</b>, "
                 "фигуры, карандаш, заметка, ластик, скрыть данные… Сейчас выбран «Добавить текст».",
                 target=lambda: wrect(self._ed().btns["text"].parentWidget()) if self._ed() else None),
            Step("15. Впишите текст",
                 "Зажмите мышку на странице и <b>протяните рамку</b> — там, где нужен текст. В окошке напишите, "
                 "например, свою фамилию, и нажмите <b>ОК</b>.",
                 target=lambda: wrect(self._ed().scroll) if self._ed() else None,
                 check=lambda: bool(self._ed() and self._ed().changed)),
            Step("16. Готово — назад к страницам",
                 "Получилось! Ошиблись — «Отменить» (Ctrl+Z). Нажмите <b>«Готово»</b>, чтобы вернуться.",
                 target=lambda: wrect(self._ed().b_close) if self._ed() else None,
                 check=lambda: self._ed() is None),
            Step("17. Сохраните",
                 "Нажмите большую синюю кнопку <b>«Сохранить»</b>. PDF дела запишется в папку дела под "
                 "названием дела — ничего выбирать не нужно.",
                 target=lambda: tb(m.a_save),
                 check=lambda: not m.modified and m.path and os.path.exists(m.path)),
            Step("18. Комплект для подачи",
                 "<b>«Комплект для подачи»</b> — список того, что отправляете в суд: собирается в один PDF, "
                 "сверяется по пунктам, из него делается опись почты (ф. 107).",
                 target=lambda: tab_rect(m.docs_seg, 1)),
            Step("19. Таймер",
                 "Внизу справа — маленькая кнопка <b>⏱</b>: таймер и секундомер (например, на время "
                 "выступления).",
                 target=lambda: wrect(m.timer_btn)),
            Step("20. Если что-то забудете",
                 "<b>«Справка»</b> — энциклопедия по всем функциям, с картинками и поиском. Там же раздел "
                 "<b>«🎓 Обучение»</b> — это обучение можно пройти снова.",
                 target=lambda: wrect(getattr(m, "b_help_link", None))),
            Step("Поздравляем! 🎉",
                 "Вы прошли обучение: выбирать дело, собирать документы в PDF дела, добавлять файлы, удалять, "
                 "поворачивать и переставлять страницы, сворачивать файлы, вписывать текст и сохранять.<br><br>"
                 "Учебное дело больше не нужно — его можно удалить.",
                 next_text="Удалить учебное дело и закончить"),
        ]

    def _scroll_to(self, k):
        if k is not None:
            it = self.m.pages.item(k)
            if it is not None and not it.isHidden():
                vis = self.m.pages.viewport().rect()
                if not vis.contains(self.m.pages.visualItemRect(it)):
                    self.m.pages.scrollToItem(it)
        return k

    # ---- ход обучения
    def start(self):
        try:
            self.cid, self.files = create_training_case(self.m)
        except Exception as e:
            QMessageBox.warning(self.m, "Обучение", f"Не удалось подготовить учебное дело:\n{e}")
            return
        self.m.show_home() if hasattr(self.m, "show_home") else None
        self.i = 0
        self._enter()
        self.timer.start()

    def _enter(self):
        s = self.steps[self.i]
        self.passed = False
        if s.enter:
            try:
                s.enter()
            except Exception:
                pass
        self._fill()
        self.tick()

    def _fill(self):
        """Текст и кнопки подсказки для текущего шага."""
        s = self.steps[self.i]
        b = self.bub
        b.counter.setText(f"Шаг {self.i} из {len(self.steps) - 2}" if 0 < self.i < len(self.steps) - 1 else "")
        b.title.setText(s.title)
        b.text.setText(s.text)
        b.done.hide()
        b.b_back.setVisible(self.i > 0)
        b.b_skip.setVisible(s.check is not None)
        b.b_next.setVisible(s.check is None)
        b.b_next.setText(s.next_text or "Далее →")
        last = self.i == len(self.steps) - 1
        b.b_quit.setVisible(not last)
        while b.extra.count():
            w = b.extra.takeAt(0).widget()
            if w:
                w.deleteLater()
        if last:
            keep = QPushButton("Оставить учебное дело")
            keep.clicked.connect(lambda: self.finish(delete=False))
            b.extra.addStretch(1)
            b.extra.addWidget(keep)
        if self.passed:
            b.done.show()
        b.adjustSize()

    def next(self):
        if self.i == len(self.steps) - 1:
            return self.finish(delete=True)
        self.i += 1
        self._enter()

    def back(self):
        if self.i > 0:
            self.i -= 1
            self._enter()

    def quit(self):
        if QMessageBox.question(self.bub if _alive(self.bub) else self.m, "Обучение", "Закончить обучение? Его можно пройти снова: "
                                "«Справка → 🎓 Обучение».") != QMessageBox.Yes:
            return
        self.finish(delete=None)

    def finish(self, delete=True):
        self.timer.stop()
        for w in (self.spot, self.bub):
            if _alive(w):
                w.hide()
        P_of(self.m).settings().setValue("tutorial_done", "1")
        if delete is None:
            delete = QMessageBox.question(self.m, "Обучение", "Удалить учебное дело?") == QMessageBox.Yes
        if delete and self.cid:
            delete_training_case(self.m, self.cid, ask=False)
        self.m.tutor = None
        for w in (self.spot, self.bub):
            if _alive(w):
                w.deleteLater()

    # ---- на каком окне показываться (главное или открытое поверх него — редактор страницы и т. п.)
    SPOT_FLAGS = Qt.Tool | Qt.FramelessWindowHint | Qt.WindowTransparentForInput | Qt.WindowDoesNotAcceptFocus
    BUB_FLAGS = Qt.Tool | Qt.FramelessWindowHint

    def _attach(self, host):
        """Перевесить шторку и подсказку на окно host. Пока они «дети» окна, оно удалит их вместе с собой —
        поэтому при закрытии окна они заранее возвращаются на родительское (см. _release)."""
        self.host = host
        for w, fl in ((self.spot, self.SPOT_FLAGS), (self.bub, self.BUB_FLAGS)):
            vis = w.isVisible()
            w.setParent(host, fl)
            if vis:
                w.show()
        if host is not self.m:
            try:
                host.finished.connect(lambda *_a, h=host: self._release(h))
            except (AttributeError, RuntimeError):
                pass

    def _release(self, dlg):
        """Окно (редактор, диалог) закрывается — вернуть подсказку на окно под ним, пока оно не удалилось."""
        if self.host is not dlg or not _alive(self.bub):
            return
        par = dlg.parentWidget() if _alive(dlg) else None
        par = par.window() if par is not None and _alive(par) else self.m
        self._attach(par if _alive(par) else self.m)

    def _ensure_widgets(self):
        """Если подсказку всё-таки удалили вместе с чужим окном — создать заново."""
        if not _alive(self.spot):
            self.spot = Spotlight()
            self.host = None
        if not _alive(self.bub):
            self.bub = Bubble(self)
            self.host = None
            self._restyle()
            self._fill()
        if self.host is not None and not _alive(self.host):
            self.host = None

    def tick(self):
        try:
            self._tick()
        except Exception as e:                    # обучение не должно ронять программу окнами ошибок
            if repr(e) != getattr(self, "_last_err", None):      # в журнал — один раз, а не 8 раз в секунду
                self._last_err = repr(e)
                try:
                    P_of(self.m).log_error("Обучение", e)
                except Exception:
                    pass

    def _tick(self):
        self._ensure_widgets()
        s = self.steps[self.i]
        host = QApplication.activeModalWidget()
        if host is None or not host.isVisible() or not _alive(host):
            host = self.m
        if host is not self.host:
            self._attach(host)
        try:
            target = s.target() if s.target else None
        except Exception:
            target = None
        # QWidget.size(...) явно: у некоторых окон (ввод текста) есть своё поле «size» — счётчик кегля
        hg = QRect(QWidget.mapToGlobal(host, QPoint(0, 0)), QWidget.size(host))
        # подсказка: рядом с целью, не вылезая за окно
        b = self.bub
        b.adjustSize()
        bw, bh = b.width(), b.height()
        if target is None:
            pos = QPoint(hg.center().x() - bw // 2, hg.center().y() - bh // 2)
        else:
            gap = 28
            cands = [QPoint(target.right() + gap, target.center().y() - bh // 2),
                     QPoint(target.left() - gap - bw, target.center().y() - bh // 2),
                     QPoint(target.center().x() - bw // 2, target.bottom() + gap),
                     QPoint(target.center().x() - bw // 2, target.top() - gap - bh)]
            pos = None
            for c in cands:
                r = QRect(c, b.size())
                if hg.adjusted(8, 8, -8, -8).contains(r) and not r.intersects(target.adjusted(-8, -8, 8, 8)):
                    pos = c
                    break
            if pos is None:                        # цель большая — в угол окна
                pos = QPoint(hg.right() - bw - 24, hg.bottom() - bh - 40)
            pos.setX(max(hg.left() + 8, min(pos.x(), hg.right() - bw - 8)))
            pos.setY(max(hg.top() + 8, min(pos.y(), hg.bottom() - bh - 8)))
        if b.pos() != pos:
            b.move(pos)
        if not b.isVisible():
            b.show()
        # шторка — только когда наше окно активно и нет выпадающего меню
        show_spot = QApplication.activePopupWidget() is None and QApplication.activeWindow() in (host, b, None)
        if show_spot:
            if self.spot.geometry() != hg:
                self.spot.setGeometry(hg)
            self.phase += 1
            hole = QRect(target.topLeft() - hg.topLeft(), target.size()) if target is not None else None
            self.spot.set_state(hole, QRect(pos - hg.topLeft(), b.size()), self.phase)
            if not self.spot.isVisible():
                self.spot.show()
                b.raise_()
        elif self.spot.isVisible():
            self.spot.hide()
        # шаг выполнен?
        if s.check and not self.passed:
            try:
                ok = bool(s.check())
            except Exception:
                ok = False
            if ok:
                self.passed = True
                b.done.show()
                b.adjustSize()
                idx = self.i
                QTimer.singleShot(900, lambda: self.i == idx and self.next())


def offer(main):
    """Первый запуск: предложить обучение."""
    if os.environ.get("QT_QPA_PLATFORM") == "offscreen":      # проверки и снимки для справки — без вопроса
        return
    st = P_of(main).settings()
    if str(st.value("tutorial_done", "")) == "1" or str(st.value("tutorial_offered", "")) == "1":
        return
    st.setValue("tutorial_offered", "1")
    box = QMessageBox(main)
    box.setWindowTitle("Обучение")
    box.setIcon(QMessageBox.Question)
    box.setText("<b>Пройти короткое обучение?</b>")
    box.setInformativeText("Минут десять: программа стрелками покажет, как собирать документы дела в один PDF, "
                           "добавлять файлы, удалять и поворачивать страницы, вписывать текст и сохранять. "
                           "Всё — на учебном деле, ваши дела не пострадают.\n\nЕго можно пройти в любой момент: "
                           "«Справка → 🎓 Обучение».")
    go = box.addButton("Начать обучение", QMessageBox.AcceptRole)
    box.addButton("Не сейчас", QMessageBox.RejectRole)
    box.exec()
    if box.clickedButton() is go:
        start(main)


def start(main):
    if getattr(main, "tutor", None):
        return
    if not main.save_all_ws():
        return
    main.tutor = Tutor(main)
    main.tutor.start()
