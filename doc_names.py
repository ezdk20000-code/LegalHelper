# -*- coding: utf-8 -*-
"""
Названия документов «как в суде»: «Scan_0042.pdf» → «2026-09-12 Определение о принятии искового заявления.pdf».

* suggest(path) — по тексту документа: тип (иск, отзыв, определение, решение, ходатайство…), уточнение
  («о взыскании задолженности») и дата (у судебных актов — в шапке, у своих бумаг — у подписи; если даты
  в тексте нет — дата изменения файла). Возвращает {"stem", "kind", "date", "needed"} или None.
  needed — в нынешнем имени нет типа документа, есть смысл предложить переименование.
* Текст берётся только там, где он уже есть: PDF с текстовым слоем, Word (docx), txt, либо готовая PDF-копия
  Word-файла. Сканы без распознанного текста не трогаем.
"""
import datetime as dt
import os
import re
from pathlib import Path

MONTHS = {"январ": 1, "феврал": 2, "март": 3, "апрел": 4, "ма": 5, "июн": 6, "июл": 7, "август": 8,
          "сентябр": 9, "октябр": 10, "ноябр": 11, "декабр": 12}
_MON_RE = r"(январ[яь]|феврал[яь]|марта?|апрел[яь]|ма[яй]|июн[яь]|июл[яь]|августа?|сентябр[яь]|октябр[яь]|ноябр[яь]|декабр[яь])"
DATE_RE = re.compile(rf"(?<!\d)(?:(\d{{1,2}})\.(\d{{1,2}})\.((?:19|20)\d\d)|«?(\d{{1,2}})»?\s+{_MON_RE}\s+((?:19|20)\d\d))(?!\d)",
                     re.I)

# (шаблон начала строки-заголовка, название, свой ли это документ, шаблон «уже назван» в имени файла, нужно ли «о …»)
# Свой — дата у подписи в конце; судебный акт — дата в шапке. Порядок важен: сначала более точные.
TYPES = [
    (r"отзыв\w*\s+на\s+апелляционн\w*", "Отзыв на апелляционную жалобу", True, r"отзыв", False),
    (r"отзыв\w*\s+на\s+кассационн\w*", "Отзыв на кассационную жалобу", True, r"отзыв", False),
    (r"отзыв\w*", "Отзыв на иск", True, r"отзыв", False),
    (r"возражени\w*", "Возражения", True, r"возраж", True),
    (r"письменн\w*\s+пояснени\w*|пояснени\w*", "Пояснения", True, r"пояснен", True),
    (r"дополнени\w*", "Дополнения", True, r"дополнен", True),
    (r"апелляционн\w*\s+жалоб\w*", "Апелляционная жалоба", True, r"жалоб|апелл", False),
    (r"кассационн\w*\s+жалоб\w*", "Кассационная жалоба", True, r"жалоб|кассац", False),
    (r"частн\w*\s+жалоб\w*", "Частная жалоба", True, r"жалоб", False),
    (r"жалоб\w*", "Жалоба", True, r"жалоб", True),
    (r"административн\w*\s+исков\w*\s+заявлени\w*", "Административное исковое заявление", True, r"\bиск|\bаи[сз]", True),
    (r"встречн\w*\s+исков\w*\s+заявлени\w*", "Встречное исковое заявление", True, r"\bиск|встречн", True),
    (r"(?:уточн\w*\s+)?исков\w*\s+заявлени\w*", "Исковое заявление", True, r"\bиск", True),
    (r"заявлени\w*\s+о\s+выдаче\s+судебн\w*\s+приказ\w*", "Заявление о выдаче судебного приказа", True, r"приказ|заявлен", False),
    (r"заявлени\w*", "Заявление", True, r"заявлен", True),
    (r"ходатайств\w*", "Ходатайство", True, r"ходатайств", True),
    (r"досудебн\w*\s+претензи\w*|претензи\w*", "Претензия", True, r"претенз", False),
    (r"мирово\w*\s+соглашени\w*", "Мировое соглашение", True, r"миров", False),
    (r"судебн\w*\s+приказ\w*", "Судебный приказ", False, r"приказ", False),
    (r"исполнительн\w*\s+лист\w*", "Исполнительный лист", False, r"исполнит|\bил\b", False),
    (r"протокол\w*\s+судебн\w*\s+заседани\w*|протокол\w*", "Протокол судебного заседания", False, r"протокол", False),
    (r"апелляционн\w*\s+определени\w*", "Апелляционное определение", False, r"определ", False),
    (r"кассационн\w*\s+определени\w*", "Кассационное определение", False, r"определ", False),
    (r"определени\w*", "Определение", False, r"определ", True),
    (r"резолютивн\w*\s+част\w*", "Решение (резолютивная часть)", False, r"решени|резолют", False),
    (r"(?:мотивированн\w*\s+)?решени\w*", "Решение", False, r"решени", False),
    (r"постановлени\w*", "Постановление", False, r"постановл", True),
    (r"договор\w*", "Договор", True, r"договор", True),
    (r"дополнительн\w*\s+соглашени\w*", "Дополнительное соглашение", True, r"соглашен", False),
    (r"доверенност\w*", "Доверенность", True, r"доверен", False),
    (r"платежн\w*\s+поручени\w*", "Платёжное поручение", True, r"платеж|платёж|п/?п", False),
    (r"акт\w*\s+сверки", "Акт сверки", True, r"сверк", False),
    (r"выписк\w*\s+из\s+(?:единого\s+государственного\s+реестра\s+юридических|егрюл)", "Выписка из ЕГРЮЛ", True,
     r"выписк|егрюл", False),
    (r"выписк\w*\s+из\s+(?:единого\s+государственного\s+реестра\s+недвижимости|егрн)", "Выписка из ЕГРН", True,
     r"выписк|егрн", False),
    (r"уведомлени\w*", "Уведомление", True, r"уведомл", True),
    (r"расписк\w*", "Расписка", True, r"расписк", False),
]
_TYPES = [(re.compile(rf"^\s*{p}(?![а-яё])", re.I), name, own, re.compile(k, re.I), about)
          for p, name, own, k, about in TYPES]
_ABOUT_RE = re.compile(r"^\s*(об?|по\s+вопросу|к\s+(?:исковому|апелляционной|отзыву))\s+[а-яё]", re.I)
_STOP_RE = re.compile(r"\s+(?:по\s+делу|дело\s*№|№|от\s+\d|в\s+рамках|к\s+ответчику|к\s+ООО|к\s+АО|к\s+ПАО|"
                      r"к\s+ИП|в\s+отношении|с\s+ООО)(?![а-яё]).*$", re.I)
_TAIL_STOP = {"и", "в", "на", "по", "о", "об", "с", "к", "от", "за", "для", "из", "при", "а", "или"}
_COURT_HINT = re.compile(r"суд|именем\s+российской", re.I)
HEADER_LINES = 45
_TITLE_REST = re.compile(r"^\s*(?:$|об?\s|на\s|к\s|№|от\s|по\s|в\s|\(|[«\"]|ответчика|истца|"
                         r"стороны|третьего|заинтересованного)", re.I)


def _date(m):
    try:
        if m.group(1):
            return dt.date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        mon = m.group(5).lower()
        n = next(v for k, v in sorted(MONTHS.items(), key=lambda kv: -len(kv[0])) if mon.startswith(k))
        return dt.date(int(m.group(6)), n, int(m.group(4)))
    except (ValueError, StopIteration):
        return None


def _dates(text):
    out = []
    for m in DATE_RE.finditer(text or ""):
        d = _date(m)
        if d and dt.date(1990, 1, 1) <= d <= dt.date.today() + dt.timedelta(days=60):
            out.append(d)
    return out


def _clean(s):
    s = re.sub(r"\s+", " ", (s or "").replace("\u00ad", "")).strip(" .,;:-–—\"«»")
    # «Р Е Ш Е Н И Е» — заголовок вразрядку
    return re.sub(r"(?<![А-ЯЁа-яё])(?:[А-ЯЁ] ){3,}[А-ЯЁ](?![А-ЯЁа-яё])", lambda m: m.group(0).replace(" ", ""), s)


def _about(lines):
    """«о взыскании задолженности по договору поставки» — уточнение после названия, коротко."""
    for s in lines:
        if not s.strip():
            continue
        if not _ABOUT_RE.match(s):
            continue
        s = _STOP_RE.sub("", _clean(s))
        words = s.split()[:7]
        while words and words[-1].lower() in _TAIL_STOP:
            words.pop()
        if len(words) >= 2:
            return " ".join(words).lower()
    return ""


def classify(text):
    """Тип документа по шапке: (название, свой, шаблон-уже-назван, строка-заголовка, номер строки) или None."""
    lines = [l for l in (text or "").splitlines()]
    lines = [l for l in lines if l.strip()][:HEADER_LINES]
    best = None
    for i, line in enumerate(lines):
        s = _clean(line)
        if not s or len(s) > 140:
            continue
        for rx, name, own, key, about in _TYPES:
            m = rx.match(s)
            if not m:
                continue
            # заголовок — короткая строка или строка ЗАГЛАВНЫМИ; «Заявление получено…» в тексте не в счёт
            caps = s[:m.end()].isupper()
            # заголовок обычными буквами — только в самом начале документа (дальше это уже текст или приложения)
            # и продолжение — как у заголовка («об отложении», «на иск», «№ 5»), а не как у фразы («направлена…»)
            title_like = caps or i < 20 and s[:1].isupper() and len(s) <= 90 and (
                name == "Договор" or _TITLE_REST.match(s[m.end():]))
            if not title_like:
                continue
            rest = s[m.end():]
            extra = ""
            if name == "Договор":
                w = re.match(r"^\s*((?:[а-яё]+\s*){1,4})", rest, re.I)
                extra = _clean(w.group(1)).lower() if w else ""
                extra = " ".join(x for x in extra.split() if x not in _TAIL_STOP or x != extra.split()[-1])
            elif about:
                extra = _about([rest] + lines[i + 1:i + 6])
            cand = (name, own, key, extra, i, caps)
            if best is None or (cand[5] and not best[5] and i - best[4] < 25):
                best = cand
            break
        if best and best[5]:
            break
    return best


def suggest(path, text=None):
    """Предложение имени (без расширения) или None, если тип документа не понять."""
    if text is None:
        text = read_text(path)
    if not text or len(text.strip()) < 40:
        return None
    c = classify(text)
    if not c:
        return None
    name, own, key, extra, line_no, _caps = c
    lines = [l for l in text.splitlines() if l.strip()]
    if own:
        tail = "\n".join(lines[-25:])
        ds = _dates(tail)
        d = ds[-1] if ds else None
        if d is None:                       # у своих бумаг дата в шапке бывает датой договора — не берём её
            d = _mtime_date(path)
    else:
        head = "\n".join(lines[:line_no + 15])
        ds = _dates(head)
        d = ds[0] if ds else (_dates(text)[:1] or [None])[0] or _mtime_date(path)
    if name in ("Отзыв на иск",) and re.search(r"отзыв\w*\s+на\s+(?:исков|иск)", text[:3000], re.I) is None:
        name = "Отзыв"
    title = name + (f" {extra}" if extra else "")
    if len(title) > 90:
        title = title[:90].rsplit(" ", 1)[0]
    stem = (d.isoformat() + " " if d else "") + title
    stem = safe_stem(stem)
    cur = Path(path).stem
    needed = not key.search(cur)
    return {"stem": stem, "kind": name, "date": d, "needed": needed, "same": stem.lower() == cur.lower()}


def _mtime_date(path):
    try:
        return dt.date.fromtimestamp(os.path.getmtime(path))
    except OSError:
        return None


def safe_stem(s):
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]', " ", s)
    s = re.sub(r"\s+", " ", s).strip(" .")
    return s[:120] or "Документ"


def read_text(path, pages=3):
    """Текст начала и конца документа — только если он уже есть (без распознавания и конвертации)."""
    try:
        ext = Path(path).suffix.lower()
        if not os.path.isfile(path):
            return ""
        if ext in (".docx",):
            import docx
            d = docx.Document(path)
            return "\n".join(p.text for p in d.paragraphs)
        if ext in (".txt", ".md"):
            return Path(path).read_text(encoding="utf-8", errors="replace")[:20000]
        src = path
        if ext != ".pdf":
            try:
                import pdf_core as C
                src = C.cached_pdf(path) if ext in C.OFFICE_EXT or ext in C.HTML_EXT else None
            except Exception:
                src = None
            if not src or not os.path.exists(src):
                return ""
        import pymupdf as fitz
        with fitz.open(src) as doc:
            n = doc.page_count
            idx = list(range(min(pages, n)))
            if n > pages:
                idx.append(n - 1)
            return "\n".join(doc[i].get_text() for i in idx)
    except Exception:
        return ""


def unique_path(folder, stem, ext, skip=None):
    p, n = os.path.join(folder, stem + ext), 2
    while os.path.exists(p) and not (skip and os.path.normcase(os.path.abspath(p)) == os.path.normcase(os.path.abspath(skip))):
        p, n = os.path.join(folder, f"{stem} ({n}){ext}"), n + 1
    return p
