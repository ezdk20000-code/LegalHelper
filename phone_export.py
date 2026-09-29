# -*- coding: utf-8 -*-
"""
Дела на телефоне через Яндекс Диск.

Для каждого дела программа собирает один PDF «под телефон» и кладёт его в папку Яндекс Диска на компьютере
(«<Яндекс Диск>/LegalHelper — дела/<Название дела>.pdf»). Программа Яндекс Диска сама переносит файл в облако,
а на телефоне его открывают в приложении «Яндекс Диск». Логин и пароль Яндекса LegalHelper не нужны и не
хранятся: вход делается один раз в самой программе Яндекс Диска.

Что внутри файла:
    1. Памятка к заседанию — ближайшее заседание, данные дела, «Главное к заседанию» (поле в «Обзоре»);
    2. Сроки, напоминания и выписки с номерами листов;
    3. Документы дела — оглавление: нажали на документ — открылась его первая страница;
    4. PDF дела целиком (страницы как есть).
Страницы 1–3 узкие, под экран телефона, — читаются без увеличения. Файл обновляется сам после сохранения
дела (и раз в несколько минут, если что-то поменялось), без лишних перезаписей.
"""
import datetime as dt
import hashlib
import html
import io
import os
import re
from pathlib import Path

import pymupdf as fitz

FOLDER_NAME = "LegalHelper — дела"
YANDEX_DOWNLOAD = "https://disk.yandex.ru/download"
PHONE_W, PHONE_H = 360, 640
WEEKDAYS = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]
MONTHS = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября",
          "ноября", "декабря"]

CSS = """
* { font-family: sans-serif; }
body { font-size: 11pt; color: #1c1c1e; }
h1 { font-size: 17pt; margin: 0 0 4px 0; }
h2 { font-size: 13pt; margin: 14px 0 4px 0; }
.sub { color: #8e8e93; font-size: 9.5pt; margin-bottom: 10px; }
.card { background-color: #f2f2f7; padding: 8px 10px; margin: 8px 0; }
.big { font-size: 14pt; font-weight: bold; color: #0a84ff; }
.lbl { color: #8e8e93; font-size: 9pt; }
.red { color: #ff3b30; font-weight: bold; }
.muted { color: #8e8e93; }
li { margin-bottom: 4px; }
"""


# --------------------------------------------------------------------------- где Яндекс Диск
def find_yandex_folder():
    """Папка Яндекс Диска на компьютере (её создаёт программа «Яндекс Диск» после входа) или None."""
    home = Path.home()
    cands = [home / "YandexDisk", home / "Yandex.Disk", home / "YandexDisk2", home / "Яндекс.Диск",
             home / "Яндекс Диск"]
    try:
        cands += sorted(p for p in home.iterdir() if p.is_dir() and p.name.lower().startswith(("yandex", "яндекс")))
    except OSError:
        pass
    for drive in "DEF":                                      # иногда Диск переносят на другой раздел
        cands.append(Path(f"{drive}:/YandexDisk"))
    for p in cands:
        try:
            if p.is_dir():
                return str(p)
        except OSError:
            continue
    return None


def export_dir(base):
    d = os.path.join(base, FOLDER_NAME)
    os.makedirs(d, exist_ok=True)
    return d


def clean_name(s):
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]', " ", s or "").strip(" .")
    return re.sub(r"\s+", " ", s)[:80] or "Дело"


# --------------------------------------------------------------------------- содержимое
def _esc(s):
    return html.escape(str(s or ""))


def _when(e):
    d = dt.date.fromisoformat(e["date"])
    s = f"{d.day} {MONTHS[d.month - 1]}, {WEEKDAYS[d.weekday()]}"
    return s + (f", {e['time']}" if e.get("time") else "")


def memo_html(db, cid, now=None):
    """HTML памятки (страницы 1–2). Возвращает (html, есть_ли_содержимое)."""
    now = now or dt.datetime.now()
    c = db.case(cid) or {}
    today = now.date().isoformat()
    evs = [e for e in db.events(cid, include_done=False)]
    hearings = [e for e in evs if e["kind"] == "Заседание" and e["date"] >= today]
    parts = [f"<h1>{_esc(c.get('title'))}</h1>",
             f"<div class='sub'>Памятка к заседанию · обновлено {now:%d.%m.%Y %H:%M}</div>"]
    if hearings:
        h = hearings[0]
        parts.append("<div class='card'><div class='lbl'>БЛИЖАЙШЕЕ ЗАСЕДАНИЕ</div>"
                     f"<div class='big'>{_esc(_when(h))}</div>"
                     + (_esc(c.get("court")) + "<br>" if c.get("court") else "")
                     + (f"Зал / место: {_esc(h['place'])}<br>" if h.get("place") else "")
                     + (_esc(h["title"]) if h.get("title") else "") + "</div>")
    else:
        parts.append("<div class='card'><div class='lbl'>БЛИЖАЙШЕЕ ЗАСЕДАНИЕ</div>"
                     "<span class='muted'>не назначено</span></div>")
    rows = [("№", c.get("number")), ("Суд", c.get("court")), ("Судья", c.get("judge")),
            ("Доверитель", c.get("client")), ("Оппонент", c.get("opponent")), ("Третьи лица", c.get("third")),
            ("Стадия", c.get("stage")), ("Предмет / цена иска", c.get("claim"))]
    info = "<br>".join(f"<b>{a}:</b> {_esc(b)}" for a, b in rows if b)
    if info:
        parts.append(f"<div class='card'><div class='lbl'>ДЕЛО</div>{info}</div>")
    brief = (c.get("brief") or "").strip()
    if brief:
        items = [ln.strip(" -•*\t") for ln in brief.splitlines() if ln.strip()]
        lis = []
        for ln in items:
            red = ln.startswith("!")
            ln = ln.lstrip("! ")
            lis.append(f"<li class='red'>{_esc(ln)}</li>" if red else f"<li>{_esc(ln)}</li>")
        parts.append("<h2>Главное к заседанию</h2><ul>" + "".join(lis) + "</ul>")
    elif (c.get("notes") or "").strip():
        text = c["notes"].strip()
        if len(text) > 2500:
            text = text[:2500] + "…"
        parts.append("<h2>Заметки по делу</h2>" + "".join(f"<p>{_esc(p)}</p>" for p in text.splitlines() if p.strip()))
    # сроки и напоминания
    upcoming = [e for e in evs if e["kind"] != "Заседание" or e["date"] >= today][:15]
    if upcoming:
        lis = []
        for e in upcoming:
            late = e["date"] < today
            txt = f"<b>{_esc(_when(e))}</b> — {_esc(e['kind'])}" + (f": {_esc(e['title'])}" if e.get("title") else "")
            lis.append(f"<li class='red'>просрочено · {txt}</li>" if late else f"<li>{txt}</li>")
        parts.append("<h2>Сроки и заседания</h2><ul>" + "".join(lis) + "</ul>")
    quotes = db.quotes(cid)
    if quotes:
        parts.append("<h2>Выписки</h2><ul>" + "".join(
            f"<li>«{_esc(q['text'])}» — <i>{_esc(q.get('source'))}"
            + (f", л. {q['page']}" if q.get("page") else "") + "</i></li>" for q in quotes[:40]) + "</ul>")
    return "".join(parts)


def _story_pages(body, css=CSS):
    """HTML → PDF узкими страницами (сколько понадобится)."""
    buf = io.BytesIO()
    story = fitz.Story(html=body, user_css=css)
    writer = fitz.DocumentWriter(buf)
    rect = fitz.Rect(0, 0, PHONE_W, PHONE_H)
    where = rect + (16, 16, -16, -16)
    more = True
    while more:
        dev = writer.begin_page(rect)
        more, _ = story.place(where)
        story.draw(dev)
        writer.end_page()
    writer.close()
    return fitz.open("pdf", buf.getvalue())


def _groups(case_doc):
    """Документы внутри PDF дела: [(название, первая страница, число страниц)] по пометкам LegalHelper."""
    out, i, n = [], 0, case_doc.page_count

    def key(k, name):
        t, v = case_doc.xref_get_key(case_doc[k].xref, name)
        return v if t == "string" else None
    while i < n:
        g, name = key(i, "LHGroup"), key(i, "LHName")
        j = i
        while g and j + 1 < n and key(j + 1, "LHGroup") == g:
            j += 1
        out.append((os.path.splitext(name)[0] if name else f"Страницы {i + 1}–{j + 1}", i, j - i + 1))
        i = j + 1
    return out


def build_phone_pdf(db, cid, case_pdf=None, now=None):
    """Собрать PDF для телефона. Возвращает fitz.Document."""
    memo = _story_pages(memo_html(db, cid, now))
    case_doc = None
    if case_pdf and os.path.exists(case_pdf):
        try:
            case_doc = fitz.open("pdf", Path(case_pdf).read_bytes())
        except Exception:
            case_doc = None
    out = fitz.open()
    out.insert_pdf(memo)
    toc = [[1, "Памятка к заседанию", 1]]
    if case_doc is not None and case_doc.page_count:
        groups = _groups(case_doc)
        per = 8                                             # карточек на странице оглавления
        toc_pages = (len(groups) + per - 1) // per
        first_doc_page = out.page_count + toc_pages         # номер (с 0) первой страницы PDF дела
        toc_start = out.page_count
        for k in range(toc_pages):
            chunk = groups[k * per:(k + 1) * per]
            cards = "".join(
                f"<div class='card'>📄 <b>{_esc(name)}</b><br><span class='lbl'>стр. {first_doc_page + s + 1}"
                + (f"–{first_doc_page + s + cnt}" if cnt > 1 else "") + " · нажмите, чтобы открыть</span></div>"
                for name, s, cnt in chunk)
            p = out.new_page(width=PHONE_W, height=PHONE_H)
            p.insert_htmlbox(fitz.Rect(16, 16, PHONE_W - 16, PHONE_H - 16),
                             ("<h2>Документы дела</h2>" if k == 0 else "") + cards, css=CSS)
        toc.append([1, "Документы дела", toc_start + 1])
        out.insert_pdf(case_doc)
        # ссылки с карточек оглавления на документы: ищем карточки по тексту «нажмите, чтобы открыть»
        for k in range(toc_pages):
            page = out[toc_start + k]
            chunk = groups[k * per:(k + 1) * per]
            hits = page.search_for("нажмите, чтобы открыть")
            for (name, s, cnt), r in zip(chunk, hits):
                area = fitz.Rect(16, r.y0 - 22, PHONE_W - 16, r.y1 + 6)
                page.insert_link({"kind": fitz.LINK_GOTO, "from": area, "page": first_doc_page + s})
        for name, s, cnt in groups:
            toc.append([2, name, first_doc_page + s + 1])
    out.set_toc(toc)
    c = db.case(cid) or {}
    out.set_metadata({"title": f"{c.get('title', '')} — к заседанию", "creator": "LegalHelper"})
    return out


# --------------------------------------------------------------------------- выгрузка
def export_case(db, cid, base, case_pdf=None, settings=None, force=False):
    """Положить файл дела в папку Яндекс Диска. Возвращает путь, или None — если ничего не поменялось."""
    c = db.case(cid)
    if not c:
        return None
    folder = export_dir(base)
    name = clean_name(c["title"]) + ".pdf"
    path = os.path.join(folder, name)
    # не переписывать без изменений (иначе Яндекс Диск гонял бы один и тот же файл туда-сюда)
    stamp = ""
    if case_pdf and os.path.exists(case_pdf):
        st = os.stat(case_pdf)
        stamp = f"{st.st_size}:{st.st_mtime}"
    digest = hashlib.sha1((memo_html(db, cid, dt.datetime(2000, 1, 1)) + stamp).encode("utf-8")).hexdigest()
    key = f"phone/hash/{c.get('uid') or cid}"
    oldname_key = f"phone/name/{c.get('uid') or cid}"
    if settings is not None and not force and settings.value(key, "") == digest and os.path.exists(path):
        return None
    doc = build_phone_pdf(db, cid, case_pdf)
    tmp = path + ".part"
    doc.save(tmp, garbage=3, deflate=True)
    os.replace(tmp, path)
    if settings is not None:
        settings.setValue(key, digest)
        old = settings.value(oldname_key, "")
        if old and old != name:                           # дело переименовали — старый файл убрать
            try:
                os.remove(os.path.join(folder, old))
            except OSError:
                pass
        settings.setValue(oldname_key, name)
    return path


def remove_case_file(db, cid, base, settings=None):
    c = db.case(cid)
    if not c or not base:
        return
    name = (settings.value(f"phone/name/{c.get('uid') or cid}", "") if settings is not None else "") or \
        clean_name(c["title"]) + ".pdf"
    try:
        os.remove(os.path.join(base, FOLDER_NAME, name))
    except OSError:
        pass
