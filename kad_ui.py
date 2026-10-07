# -*- coding: utf-8 -*-
"""
«Проверить дело на kad.arbitr.ru» — картотека открывается прямо в программе. Когда карточка дела загрузилась,
кнопка «📥 Забрать из карточки» находит в ней даты заседаний и судебные акты: заседания добавляются в
«Сроки и заседания», акты скачиваются в папку дела и попадают во вкладку «Документы».
Картотека иногда просит пройти проверку «я не робот» — её проходят один раз прямо в этом окне,
программа запоминает это так же, как обычный браузер.
"""
import json
import os
import re
from pathlib import Path

from PySide6.QtCore import Qt, QUrl, QTimer
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame, QApplication,
                               QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView, QDialogButtonBox,
                               QMessageBox)

import hearings as H

KAD = "https://kad.arbitr.ru/"

# Текст страницы и ссылки на акты (PDF) с подписью — что рядом со ссылкой написано.
JS_COLLECT = r"""
(function(){
  var links = [], seen = {};
  document.querySelectorAll('a[href]').forEach(function(a){
    var h = a.href || '';
    if (!/\/Document\/Pdf\/|\.pdf(\?|$)/i.test(h) || seen[h]) return;
    seen[h] = 1;
    var box = a.closest('li, tr, .b-chrono-item, .b-case-chrono-item, div') || a;
    links.push({href: h, text: (a.innerText || a.title || '').trim(),
                around: (box.innerText || '').replace(/\s+/g, ' ').trim().slice(0, 300)});
  });
  return JSON.stringify({url: location.href, title: document.title,
                         text: (document.body ? document.body.innerText : ''), links: links});
})()
"""

# Заполнить поиск по номеру дела на главной картотеки (если разметка сайта поменяется — номер уже в буфере).
JS_SEARCH = r"""
(function(num){
  var f = document.querySelector('#sug-cases input, #sug-cases textarea, input[placeholder*="А50"], textarea[placeholder*="А50"]');
  if (!f) return false;
  f.focus(); f.value = num;
  f.dispatchEvent(new Event('input', {bubbles: true}));
  var b = document.querySelector('#b-form-submit button, .b-form-submit button, button[type=submit]');
  if (b) setTimeout(function(){ b.click(); }, 400);
  return true;
})(%s)
"""

_profile = None


def _db():
    import legal_ui as U
    return U.db()


def is_card(url):
    return bool(re.search(r"kad\.arbitr\.ru/Card/", url or "", re.I))


def case_dir(cid):
    """Папка дела — та же, где PDF дела и созданные документы."""
    import legal_ui as U
    return U.case_output_dir(cid)


def act_name(link):
    """Имя файла для акта: «2026-10-01 Определение о принятии…» из подписи рядом со ссылкой."""
    import doc_names as N
    s = (link.get("text") or "") + " " + (link.get("around") or "")
    m = re.search(r"(\d{2})\.(\d{2})\.(\d{4})", s)
    date = f"{m.group(3)}-{m.group(2)}-{m.group(1)} " if m else ""
    around, text = link.get("around") or "", (link.get("text") or "").strip()
    if text and text in around:                     # подпись самой ссылки — в конце, она короче описания
        around = around[:around.rfind(text)]
    s = re.sub(r"(?:\s+от)?\s*\d{2}\.\d{2}\.\d{4}(?:\s*г\.)?", " ", around + " . " + text)
    k = re.search(r"(Определение|Решение|Постановление|Резолютивная часть[^,.;]{0,40}|Судебный приказ|"
                  r"Исполнительный лист)([^.;]{0,90})", s, re.I)
    title = re.sub(r"\s+", " ", k.group(1) + k.group(2)).strip(" ,-") if k else "Судебный акт"
    title = re.sub(r"\s+(?:от|и)$", "", title)
    title = re.sub(r"^(\S+\s+)(О|Об|По)\b", lambda m: m.group(1) + m.group(2).lower(), title)
    return N.safe_stem((date + title)[:110])


class KadWindow(QDialog):
    def __init__(self, main, cid):
        super().__init__(main)
        self.main, self.cid = main, cid
        c = _db().case(cid) or {}
        self.number = (c.get("number") or "").strip()
        self.setWindowTitle(f"Картотека арбитражных дел — {c.get('title') or self.number}")
        self.resize(1200, 820)
        self.setWindowFlag(Qt.WindowMaximizeButtonHint, True)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        bar = QFrame()
        bar.setObjectName("dlgfoot")
        h = QHBoxLayout(bar)
        h.setContentsMargins(14, 8, 14, 8)
        self.hint = QLabel()
        self.hint.setWordWrap(True)
        h.addWidget(self.hint, 1)
        self.b_back = QPushButton("←")
        self.b_back.setToolTip("Назад")
        self.b_take = QPushButton("📥  Забрать из карточки")
        self.b_take.setObjectName("primary")
        self.b_take.setToolTip("Найти на открытой странице даты заседаний и судебные акты и добавить их в дело")
        self.b_take.clicked.connect(self.collect)
        b_ext = QPushButton("Открыть в браузере")
        b_ext.clicked.connect(lambda: QDesktopServices.openUrl(self.view.url()) if self.view else None)
        for b in (self.b_back, b_ext, self.b_take):
            h.addWidget(b)
        v.addWidget(bar)
        self.view = None
        try:
            from PySide6.QtWebEngineWidgets import QWebEngineView
            from PySide6.QtWebEngineCore import QWebEngineProfile, QWebEnginePage
        except Exception as e:
            lab = QLabel(f"Встроенный браузер недоступен в этой сборке ({e}).\nОткройте картотеку в обычном браузере.")
            lab.setAlignment(Qt.AlignCenter)
            v.addWidget(lab, 1)
            self.b_take.setEnabled(False)
            return
        global _profile
        if _profile is None:                       # один профиль на всё время работы — «я не робот» проходят раз
            _profile = QWebEngineProfile("legalhelper-kad", QApplication.instance())
            _profile.setHttpUserAgent(re.sub(r"\s*QtWebEngine/\S+", "", _profile.httpUserAgent()))
        self.page = QWebEnginePage(_profile, self)
        self.view = QWebEngineView(self)
        self.view.setPage(self.page)
        self.b_back.clicked.connect(self.view.back)
        _profile.downloadRequested.connect(self.on_download)
        self.view.loadFinished.connect(self.on_loaded)
        self.view.urlChanged.connect(lambda _u: self.update_hint())
        v.addWidget(self.view, 1)
        self._pending = {}                         # url → (имя файла)
        self._got = []
        url = (c.get("court_url") or "").strip()
        self._searched = False
        self.view.load(QUrl(url if is_card(url) else KAD))
        if self.number:
            QApplication.clipboard().setText(self.number)
        self.update_hint()

    def closeEvent(self, e):
        try:
            _profile.downloadRequested.disconnect(self.on_download)
        except Exception:
            pass
        super().closeEvent(e)

    def done(self, r):
        try:
            _profile.downloadRequested.disconnect(self.on_download)
        except Exception:
            pass
        super().done(r)

    def update_hint(self):
        url = self.view.url().toString() if self.view else ""
        if is_card(url):
            self.hint.setText("<b>Карточка дела открыта.</b> Нажмите «Забрать из карточки» — программа найдёт "
                              "даты заседаний и судебные акты и предложит добавить их в дело.")
        else:
            self.hint.setText("Найдите дело" + (f" № <b>{self.number}</b> (номер уже скопирован — Ctrl+V в поиск)"
                                                if self.number else " по номеру") +
                              " и откройте его карточку. Если сайт попросит подтвердить, что вы не робот, — "
                              "сделайте это здесь, это нужно один раз.")

    def on_loaded(self, ok):
        url = self.view.url().toString()
        if ok and self.number and not self._searched and not is_card(url) and "kad.arbitr.ru" in url:
            self._searched = True
            QTimer.singleShot(1200, lambda: self.page.runJavaScript(JS_SEARCH % json.dumps(self.number)))
        if ok and is_card(url):
            c = _db().case(self.cid) or {}
            if (c.get("court_url") or "").strip() != url.split("#")[0]:
                _db().update_case(self.cid, court_url=url.split("#")[0])   # кнопка «Дело на сайте суда» поведёт сюда

    # ---------------------------------------------------------------- забрать из карточки
    def collect(self):
        if self.view:
            self.page.runJavaScript(JS_COLLECT, 0, self.on_collected)

    def on_collected(self, res):
        try:
            data = json.loads(res or "{}")
        except (TypeError, ValueError):
            data = {}
        self.take(data)

    def take(self, data):
        text = data.get("text") or ""
        existing = _db().events(self.cid)
        evs = [e for e in H.parse_kad(text) if not H.is_known(e, existing)]
        have = {Path(d["path"]).stem.lower() for d in _db().docs(self.cid) if d["path"]}
        acts = []
        for link in data.get("links") or []:
            name = act_name(link)
            acts.append(dict(link, name=name, have=name.lower() in have))
        if not evs and not acts:
            msg = ("На странице не нашлось дат заседаний и ссылок на акты. Откройте именно карточку дела "
                   "(страницу с хронологией) и нажмите кнопку ещё раз." if not is_card(data.get("url")) else
                   "Новых заседаний и актов нет — в деле уже всё есть.")
            return QMessageBox.information(self, "Картотека", msg)
        d = TakeDialog(self, evs, acts)
        if d.exec() != QDialog.Accepted:
            return
        evs, acts = d.chosen()
        if evs:
            import hearings_ui
            hearings_ui.add(self.main, [(self.cid, e, "kad.arbitr.ru") for e in evs])
        if acts:
            self.download(acts)

    def download(self, acts):
        folder = case_dir(self.cid)
        for a in acts:
            self._pending[a["href"]] = (folder, a["name"])
            self.page.download(QUrl(a["href"]), a["name"] + ".pdf")
        self.hint.setText(f"Скачиваю актов: {len(acts)}…")

    def on_download(self, item):
        url = item.url().toString()
        if url not in self._pending:
            return
        folder, name = self._pending.pop(url)
        import doc_names as N
        target = N.unique_path(folder, name, ".pdf")
        item.setDownloadDirectory(os.path.dirname(target))
        item.setDownloadFileName(os.path.basename(target))
        item.isFinishedChanged.connect(lambda it=item, p=target: self.on_finished(it, p))
        item.accept()

    def on_finished(self, item, path):
        try:
            self._finished(item, path)
        except RuntimeError:                        # окно уже закрыли — файл всё равно скачан в папку дела
            pass

    def _finished(self, item, path):
        from PySide6.QtWebEngineCore import QWebEngineDownloadRequest as R
        if item.state() != R.DownloadCompleted or not os.path.isfile(path):
            return self.main.toast(f"Не удалось скачать «{Path(path).name}» — откройте акт в карточке и сохраните "
                                   "его вручную", 6000)
        with open(path, "rb") as f:
            ok = f.read(5) == b"%PDF-"
        if not ok:                                  # вместо файла пришла страница (проверка «не робот» и т. п.)
            os.remove(path)
            return self.main.toast("Картотека не отдала файл акта — пройдите проверку на сайте и нажмите "
                                   "«Забрать из карточки» ещё раз", 7000)
        self.main._rename_busy = True               # имя уже как в суде — не предлагать переименовать
        try:
            _db().add_doc(self.cid, path)
        finally:
            self.main._rename_busy = False
        self._got.append(path)
        try:
            self.main.cases_page.refresh_docs_if(self.cid)
        except Exception:
            pass
        self.hint.setText(f"✓  Скачано и добавлено в «Документы»: {len(self._got)}. Папка: {Path(path).parent}")


class TakeDialog(QDialog):
    def __init__(self, parent, evs, acts):
        super().__init__(parent)
        self.setWindowTitle("Что добавить в дело")
        self.resize(860, 520)
        self.evs, self.acts = evs, acts
        v = QVBoxLayout(self)
        v.addWidget(QLabel(f"<b>Заседания</b> — в «Сроки и заседания» ({len(evs)})" if evs else
                           "<b>Новых заседаний нет</b>"))
        self.te = self._table([H.describe(e) for e in evs], [True] * len(evs))
        if evs:
            v.addWidget(self.te, 1)
        v.addWidget(QLabel(f"<b>Судебные акты</b> — скачать в папку дела и добавить в «Документы» ({len(acts)})"
                           if acts else "<b>Ссылок на акты на странице нет</b>"))
        self.ta = self._table([a["name"] + ("   — уже есть в деле" if a["have"] else "") for a in acts],
                              [not a["have"] for a in acts])
        if acts:
            v.addWidget(self.ta, 2)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Добавить отмеченное")
        bb.button(QDialogButtonBox.Cancel).setText("Отмена")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def _table(self, rows, checks):
        t = QTableWidget(len(rows), 1)
        t.horizontalHeader().hide()
        t.verticalHeader().hide()
        t.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        t.setSelectionMode(QAbstractItemView.NoSelection)
        t.setEditTriggers(QAbstractItemView.NoEditTriggers)
        for i, (text, on) in enumerate(zip(rows, checks)):
            it = QTableWidgetItem(text)
            it.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked if on else Qt.Unchecked)
            t.setItem(i, 0, it)
        return t

    def chosen(self):
        ev = [e for i, e in enumerate(self.evs) if self.te.item(i, 0).checkState() == Qt.Checked]
        ac = [a for i, a in enumerate(self.acts) if self.ta.item(i, 0).checkState() == Qt.Checked]
        return ev, ac


def open_window(main, cid):
    if not cid:
        return
    w = KadWindow(main, cid)
    w.setAttribute(Qt.WA_DeleteOnClose)
    w.show()
    main._kad_window = w
