# -*- coding: utf-8 -*-
"""
Сроки и заседания в Яндекс Календаре: подключить один раз (логин + пароль приложения), дальше программа
сама отправляет новые события, исправляет изменённые и убирает удалённые и выполненные — раз в минуту
сверяет, что поменялось. Календарь на телефоне напомнит о заседании, даже если компьютер выключен.
И запасной путь — «Выгрузить в файл календаря (.ics)» для Google, Outlook, iPhone.
"""
import base64
import datetime as dt
import json
import os
import threading
from pathlib import Path

from PySide6.QtCore import Qt, QObject, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QComboBox,
                               QFormLayout, QFrame, QApplication, QFileDialog, QMessageBox)

import yacal as Y

K = "yacal/"
APP_PASSWORDS = "https://id.yandex.ru/security/app-passwords"


def _settings():
    import legal_ui as U
    return U.M.settings()


def _db():
    import legal_ui as U
    return U.db()


# ----------------------------------------------------------------------------- пароль: шифруем средствами Windows
def _protect(s):
    try:
        import win32crypt
        return "dpapi:" + base64.b64encode(win32crypt.CryptProtectData(s.encode("utf-8"), "LegalHelper", None, None,
                                                                       None, 0)).decode("ascii")
    except Exception:
        return "b64:" + base64.b64encode(s.encode("utf-8")).decode("ascii")


def _unprotect(v):
    v = str(v or "")
    try:
        if v.startswith("dpapi:"):
            import win32crypt
            return win32crypt.CryptUnprotectData(base64.b64decode(v[6:]), None, None, None, 0)[1].decode("utf-8")
        if v.startswith("b64:"):
            return base64.b64decode(v[4:]).decode("utf-8")
    except Exception:
        return ""
    return v


def config():
    s = _settings()
    return dict(login=str(s.value(K + "login", "") or ""), password=_unprotect(s.value(K + "password", "")),
                cal=str(s.value(K + "cal", "") or ""), cal_name=str(s.value(K + "cal_name", "") or ""),
                on=str(s.value(K + "on", "0")) == "1")


def load_state():
    try:
        return json.loads(str(_settings().value(K + "state", "") or "{}"))
    except ValueError:
        return {}


def save_state(st):
    _settings().setValue(K + "state", json.dumps(st))


def all_events():
    return _db().events()


# ----------------------------------------------------------------------------- фоновая сверка
class Syncer(QObject):
    finished = Signal(object)                     # (состояние, отправлено, убрано, ошибка)

    def __init__(self, main):
        super().__init__(main)
        self.main = main
        self.busy = False
        self.last = None                          # (когда, отправлено, убрано, ошибка)
        self._shown_error = None
        self.finished.connect(self._done)
        self.timer = QTimer(self)
        self.timer.timeout.connect(lambda: self.run(quiet=True))
        self.timer.start(60_000)
        QTimer.singleShot(20_000, lambda: self.run(quiet=True))
        self._callbacks = []

    def run(self, quiet=False, callback=None):
        cfg = config()
        if not cfg["on"] or not cfg["cal"] or not cfg["password"]:
            return callback and callback(None)
        if callback:
            self._callbacks.append(callback)
        if self.busy:
            return
        state = load_state()
        try:
            events = all_events()
        except Exception:
            return
        put, drop = Y.plan(events, state)
        if not put and not drop:
            self.last = (dt.datetime.now(), 0, 0, None)
            return self._flush_callbacks()
        self.busy = True

        def work():
            err, p, d = None, 0, 0
            try:
                _st, p, d = Y.sync(Y.Client(cfg["login"], cfg["password"]), cfg["cal"], events, state)
            except Y.CalError as e:
                err = str(e)
            except Exception as e:                  # не роняем программу из-за календаря
                err = f"Ошибка синхронизации: {e}"
            self.finished.emit((state, p, d, err))
        threading.Thread(target=work, daemon=True).start()

    def _done(self, res):
        state, p, d, err = res
        self.busy = False
        save_state(state)                         # даже при ошибке — то, что успели, запоминаем
        self.last = (dt.datetime.now(), p, d, err)
        if err and err != self._shown_error:
            self._shown_error = err
            try:
                self.main.statusBar().showMessage("📆 Яндекс Календарь: " + err, 15000)
            except Exception:
                pass
        elif not err:
            self._shown_error = None
        self._flush_callbacks()

    def _flush_callbacks(self):
        cbs, self._callbacks = self._callbacks, []
        for cb in cbs:
            try:
                cb(self.last)
            except Exception:
                pass


def install(main):
    main.yacal = Syncer(main)


# ----------------------------------------------------------------------------- окно настройки
class CalendarDialog(QDialog):
    def __init__(self, main):
        super().__init__(main)
        self.main = main
        self.setObjectName("tooldlg")
        self.setWindowTitle("Яндекс Календарь")
        self.setMinimumWidth(680)
        cfg = config()
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        body = QVBoxLayout()
        body.setContentsMargins(24, 20, 24, 16)
        body.setSpacing(10)
        t = QLabel("📆  Сроки и заседания — в Яндекс Календарь")
        t.setObjectName("dlgtitle")
        body.addWidget(t)
        sub = QLabel("Все сроки и заседания из программы появятся в Яндекс Календаре — на телефоне и в браузере, "
                     "с напоминанием за день и за 2 часа. Изменили или удалили событие в программе — в календаре "
                     "оно тоже изменится. Настраивается один раз.")
        sub.setObjectName("dlgsub")
        sub.setWordWrap(True)
        body.addWidget(sub)
        steps = QLabel(
            "<b>1.</b> Откройте <a href='%s'>Яндекс ID → Пароли приложений</a> и создайте пароль "
            "для «Календаря CalDAV» (любое название, например LegalHelper).<br>"
            "<b>2.</b> Впишите ниже логин Яндекса и этот пароль — <i>не</i> обычный пароль от почты.<br>"
            "<b>3.</b> Нажмите «Подключить»." % APP_PASSWORDS)
        steps.setOpenExternalLinks(True)
        steps.setWordWrap(True)
        body.addWidget(steps)
        f = QFormLayout()
        self.login = QLineEdit(cfg["login"])
        self.login.setPlaceholderText("например, ivanov@yandex.ru")
        self.pw = QLineEdit(cfg["password"])
        self.pw.setEchoMode(QLineEdit.Password)
        self.pw.setPlaceholderText("пароль приложения — 16 букв")
        f.addRow("Логин Яндекса", self.login)
        f.addRow("Пароль приложения", self.pw)
        self.cal = QComboBox()
        if cfg["cal"]:
            self.cal.addItem(cfg["cal_name"] or "Календарь", cfg["cal"])
        f.addRow("Календарь", self.cal)
        body.addLayout(f)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.RichText)
        body.addWidget(self.status)
        v.addLayout(body)
        foot = QFrame()
        foot.setObjectName("dlgfoot")
        fh = QHBoxLayout(foot)
        fh.setContentsMargins(24, 12, 24, 12)
        self.b_off = QPushButton("Отключить")
        self.b_off.clicked.connect(self.turn_off)
        b_ics = QPushButton("Выгрузить в файл (.ics)…")
        b_ics.setToolTip("Один файл со всеми сроками — для Google Календаря, Outlook, iPhone")
        b_ics.clicked.connect(lambda: export_ics(self.main, parent=self))
        fh.addWidget(self.b_off)
        fh.addWidget(b_ics)
        fh.addStretch(1)
        close = QPushButton("Закрыть")
        close.clicked.connect(self.accept)
        self.b_on = QPushButton("Подключить")
        self.b_on.setObjectName("primary")
        self.b_on.setDefault(True)
        self.b_on.clicked.connect(self.connect_)
        fh.addWidget(close)
        fh.addWidget(self.b_on)
        v.addWidget(foot)
        self.update_status()

    def update_status(self):
        cfg = config()
        self.b_off.setVisible(cfg["on"])
        if not cfg["on"]:
            self.status.setText("")
            self.b_on.setText("Подключить")
            return
        self.b_on.setText("Обновить сейчас")
        n = len(load_state())
        last = getattr(getattr(self.main, "yacal", None), "last", None)
        when = ""
        if last:
            t, p, d, err = last
            if err:
                when = f"<br><span style='color:#c0392b'>Последняя попытка {t:%H:%M}: {err}</span>"
            else:
                when = f"<br>Проверено в {t:%H:%M}" + (f": отправлено {p}, убрано {d}" if p or d else
                                                       " — всё уже в календаре")
        self.status.setText(f"✅ <b>Подключено</b>: {cfg['login']}, календарь «{cfg['cal_name']}». "
                            f"Событий в календаре от программы: {n}.{when}")

    def connect_(self):
        login, pw = self.login.text().strip(), self.pw.text().strip().replace(" ", "")
        if not login or not pw:
            return self.status.setText("Впишите логин и пароль приложения.")
        if "@" not in login:
            login += "@yandex.ru"
            self.login.setText(login)
        cfg = config()
        if cfg["on"] and cfg["login"] == login and cfg["password"] == pw and self.cal.currentData():
            return self.sync_now(self.cal.currentData(), self.cal.currentText())
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            cals = Y.Client(login, pw).calendars()
        except Y.CalError as e:
            return self.status.setText(f"<span style='color:#c0392b'>{e}</span>")
        finally:
            QApplication.restoreOverrideCursor()
        cur = self.cal.currentData()
        self.cal.clear()
        for href, name in cals:
            self.cal.addItem(name, href)
        if cur:
            i = self.cal.findData(cur)
            if i >= 0:
                self.cal.setCurrentIndex(i)
        s = _settings()
        if cfg["login"] != login or cfg["cal"] != self.cal.currentData():
            save_state({})                       # другой календарь — отправить всё заново
        s.setValue(K + "login", login)
        s.setValue(K + "password", _protect(pw))
        s.setValue(K + "cal", self.cal.currentData())
        s.setValue(K + "cal_name", self.cal.currentText())
        s.setValue(K + "on", "1")
        if not getattr(self, "_cal_hooked", False):
            self._cal_hooked = True
            self.cal.currentIndexChanged.connect(self._cal_changed)
        self.sync_now(self.cal.currentData(), self.cal.currentText())

    def _cal_changed(self, _i):
        s = _settings()
        if self.cal.currentData() and self.cal.currentData() != config()["cal"]:
            s.setValue(K + "cal", self.cal.currentData())
            s.setValue(K + "cal_name", self.cal.currentText())
            save_state({})
            self.sync_now(self.cal.currentData(), self.cal.currentText())

    def sync_now(self, href, name):
        self.status.setText("Отправляю сроки и заседания в календарь…")
        syncer = getattr(self.main, "yacal", None)
        if syncer is None:
            install(self.main)
            syncer = self.main.yacal
        syncer.run(callback=lambda _last: self.update_status() if self.isVisible() else None)

    def turn_off(self):
        n = len(load_state())
        box = QMessageBox(self)
        box.setWindowTitle("Яндекс Календарь")
        box.setText("Отключить календарь?")
        box.setInformativeText(f"Событий, которые программа отправила в календарь: {n}. Их можно убрать из "
                               "календаря или оставить там.")
        b_rm = box.addButton("Убрать из календаря и отключить", QMessageBox.AcceptRole)
        b_keep = box.addButton("Оставить и отключить", QMessageBox.AcceptRole)
        box.addButton("Отмена", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() not in (b_rm, b_keep):
            return
        cfg = config()
        if box.clickedButton() is b_rm and n:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            try:
                c = Y.Client(cfg["login"], cfg["password"])
                st = load_state()
                for k in list(st):
                    c.delete(cfg["cal"], k)
                    st.pop(k)
            except Y.CalError as e:
                QMessageBox.warning(self, "Яндекс Календарь", str(e))
            finally:
                QApplication.restoreOverrideCursor()
        save_state({})
        _settings().setValue(K + "on", "0")
        self.update_status()
        self.main.toast("Яндекс Календарь отключён")


def open_dialog(main):
    CalendarDialog(main).exec()


# ----------------------------------------------------------------------------- файл .ics
def export_ics(main, cid=None, parent=None):
    events = list(Y.wanted(_db().events(cid)).values())
    if not events:
        return main.toast("Нет предстоящих сроков и заседаний для выгрузки")
    name = "Сроки LegalHelper.ics"
    if cid:
        import doc_names as N
        c = _db().case(cid) or {}
        name = N.safe_stem("Сроки — " + (c.get("title") or "дело")) + ".ics"
    p, _ = QFileDialog.getSaveFileName(parent or main, "Файл календаря",
                                       os.path.join(str(Path.home() / "Documents"), name), "Календарь (*.ics)")
    if not p:
        return
    if not p.lower().endswith(".ics"):
        p += ".ics"
    Path(p).write_text(Y.calendar(events), encoding="utf-8")
    main.toast_actions(f"✓  Выгружено событий: {len(events)}. Откройте файл — календарь (Outlook, Google, iPhone) "
                       "предложит их добавить.", [("Открыть файл", lambda: QDesktopServices.openUrl(
                           QUrl.fromLocalFile(p)))], ms=9000)
