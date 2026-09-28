# -*- coding: utf-8 -*-
"""
Снимки экрана для справки (help/img) на демонстрационных данных.

    python tools/screenshots.py ПАПКА_ДЛЯ_СНИМКОВ [light|dark]

Запускать в чистом профиле: скрипт подменяет HOME/LOCALAPPDATA на временную папку
и заполняет базу примерами дел. На Linux без экрана: QT_QPA_PLATFORM=offscreen.
"""
import datetime as dt
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
OUT = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "help", "img"))
THEME = sys.argv[2] if len(sys.argv) > 2 else "light"
HOME = tempfile.mkdtemp(prefix="lh_demo_")
os.environ["HOME"] = HOME
os.environ["USERPROFILE"] = HOME
os.environ["LOCALAPPDATA"] = os.path.join(HOME, "AppData")
os.makedirs(os.environ["LOCALAPPDATA"], exist_ok=True)
os.makedirs(OUT, exist_ok=True)

import updater
updater.fetch_info = lambda timeout=10: (_ for _ in ()).throw(OSError("offline"))

import pymupdf as fitz
from PySide6.QtCore import Qt, QTimer, QRect
from PySide6.QtWidgets import QApplication, QDialog, QWidget

import pdf_master as P
import legal_ui as U

TODAY = dt.date.today()


def d(days):
    return (TODAY + dt.timedelta(days=days)).isoformat()


FONT = next((f for f in ("C:/Windows/Fonts/arial.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
             if os.path.exists(f)), None)
BODY = ("Истец и ответчик заключили договор поставки, по которому истец передал товар, а ответчик "
        "обязался его оплатить в течение тридцати дней. Обязательство по оплате не исполнено.")


def make_pdf(path, title, pages=2):
    doc = fitz.open()
    kw = dict(fontname="demo", fontfile=FONT) if FONT else dict(fontname="helv")
    for i in range(pages):
        pg = doc.new_page()
        pg.insert_text((72, 90), title, fontsize=16, **kw)
        pg.insert_textbox(fitz.Rect(72, 120, 523, 760), (BODY + " ") * 8, fontsize=11, lineheight=1.5,
                          color=(0.2, 0.2, 0.2), **kw)
        pg.insert_text((290, 800), f"{i + 1}", fontsize=9, **kw)
    doc.save(path)
    return path


def seed():
    db = U.db()
    folder = os.path.join(HOME, "Документы")
    os.makedirs(folder, exist_ok=True)
    c1 = db.add_case(title="ООО Ромашка — взыскание долга", number="А40-12345/2026",
                     court="Арбитражный суд города Москвы", judge="Иванова И.И.", client="ООО «Ромашка»",
                     opponent="ООО «Лютик»", stage="Первая инстанция", claim="о взыскании 1 500 000 руб.",
                     rate=5000)
    db.add_case(title="Петров — раздел имущества", number="2-555/2026", court="Пресненский районный суд",
                client="Петров П.П.", stage="Первая инстанция")
    db.add_case(title="ИП Сидоров — оспаривание штрафа", number="А40-777/2026", client="ИП Сидоров С.С.")
    db.add_event(c1, d(1), "Заседание", "Предварительное заседание", "10:30", "зал 5012")
    db.add_event(c1, d(9), "Срок", "Отзыв на встречный иск")
    db.add_event(2, d(4), "Задача", "Запросить выписку ЕГРН")
    db.add_event(c1, d(2), "Напоминание", "Позвонить доверителю: уточнить даты оплат", "11:00")
    db.update_case(c1, notes="Позиция: долг подтверждён актом сверки, ответчик его подписал.\n"
                             "Спросить у доверителя переписку о переносе сроков поставки.")
    for name, t in (("Исковое заявление.pdf", "Исковое заявление"), ("Договор поставки № 12.pdf", "Договор поставки"),
                    ("Акт сверки.pdf", "Акт сверки")):
        did = db.add_doc(c1, make_pdf(os.path.join(folder, name), t), name[:-4])
        if t == "Исковое заявление":
            db.update_doc(did, icon="⚖️", sent=f"{d(-5)}T14:35")
        elif t == "Договор поставки":
            db.update_doc(did, icon="🤝")
    db.add_time(c1, d(-6), 2.5, "Подготовка искового заявления", 5000, 12500)
    db.add_time(c1, d(-2), 1.0, "Консультация доверителя", 5000, 5000)
    db.add_payment(c1, d(-3), 10000, "Аванс")
    pack = db.add_pack(c1, "Исковое заявление", "Мой арбитр")
    for i, (title, name, done) in enumerate((
            ("Исковое заявление", "Исковое заявление.pdf", 1), ("Договор поставки № 12", "Договор поставки № 12.pdf", 1),
            ("Акт сверки", "Акт сверки.pdf", 1), ("Документ об уплате госпошлины", "", 0),
            ("Доверенность представителя", "", 0))):
        db.add_pack_item(pack, title, os.path.join(folder, name) if name else "", 1, done)
    return c1


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    f = app.font()
    fams = set(P.QFontDatabase.families())
    for fam in ("Segoe UI Variable Text", "SF Pro Text", "Segoe UI", "Inter"):
        if fam in fams:
            f.setFamily(fam)
            break
    f.setPointSize(10)
    app.setFont(f)
    P.apply_theme(app, THEME)
    U.bind(vars(P))
    cid = seed()
    w = P.MainWindow()
    w.resize(1180, 860)
    w.show()
    shots = []

    def pump(ms=250):
        end = dt.datetime.now() + dt.timedelta(milliseconds=ms)
        while dt.datetime.now() < end:
            app.processEvents()

    def grab(name, widget=None, rect=None):
        pump()
        pm = (widget or w).grab(rect) if rect else (widget or w).grab()
        pm.save(os.path.join(OUT, name + ".png"))
        shots.append(name)

    def dialog_shot(name, opener, size=None):
        """Открыть диалог, снять и закрыть (exec подменяется на show)."""
        orig = QDialog.exec
        box = []

        def fake_exec(dlg, *a):
            box.append(dlg)
            if size:
                dlg.resize(*size)
            dlg.show()
            pump(400)
            grab(name, dlg)
            dlg.hide()
            return 0
        QDialog.exec = fake_exec
        try:
            opener()
        except Exception as e:
            print("не удалось снять", name, e)
        finally:
            QDialog.exec = orig

    pump(800)
    P.settings().setValue("profile/Представитель", "Петров Пётр Петрович")
    w.show_home()
    grab("00_home")
    w.enter_case(cid)
    w.open_case_tab("overview")
    w.reminders.check()
    grab("01_main")
    side = w.centralWidget().layout().itemAt(0).widget()
    grab("02_sidebar", side)
    if w.banner.isVisible():
        grab("13_banner", w.banner)
    for key, name in (("prepare", "16_prepare"), ("events", "14_events"), ("info", "12_case"),
                      ("laws", "17_laws"), ("money", "18_money"), ("board", "19_board")):
        w.open_case_tab(key)
        pump(1500 if key == "board" else 300)
        grab(name)
    grab("06_package", w.cases_page.sub_tab)
    w.open_case_tab("docs")
    pump(300)
    grab("15_docs")
    w.enter_loose()
    grab("03_loose")
    w.open_paths([os.path.join(HOME, "Документы", "Исковое заявление.pdf")], replace=True)
    pump(600)
    tb = w.findChild(P.QToolBar)
    if tb and tb.isVisible():
        grab("04_toolbar", tb)
    dialog_shot("05_editor", lambda: w.open_editor(0), (1000, 680))
    for name, opener, size in (
            ("07_f107", lambda: U.tool_f107(w), None),
            ("08_anonymize", lambda: U.tool_anonymize(w), None),
            ("09_preflight", lambda: U.tool_preflight(w), None),
            ("10_templates", lambda: U.tool_template(w, cid, "Исковое заявление (АПК)"), (1040, 760)),
            ("11_profile", lambda: U.tool_profile(w), None)):
        dialog_shot(name, opener, size)
    w.show_calc(0)
    calc = w.findChildren(U.CalcPage)[0]
    for i, name in enumerate(("20_deadline", "21_duty", "22_interest")):
        calc.tabs.setCurrentIndex(i)
        pump(300)
        grab(name)
    print("готово:", ", ".join(shots))
    QTimer.singleShot(0, app.quit)


if __name__ == "__main__":
    main()
