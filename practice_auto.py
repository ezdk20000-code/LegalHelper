# -*- coding: utf-8 -*-
"""
Судебная практика: реквизиты судебного акта из вставленного текста.

parse(text) понимает ссылки так, как их пишут в иске и отзыве:
  «Определение ВС РФ от 12.03.2024 № 305-ЭС23-1234»,
  «постановление Арбитражного суда Московского округа от 01.02.2024 по делу № А40-12345/2023»,
  «Определение Судебной коллегии по экономическим спорам Верховного Суда РФ от 5 апреля 2023 г. № 307-ЭС22-…»,
  «п. 7 Обзора судебной практики ВС РФ № 2 (2023), утв. Президиумом ВС РФ 19.07.2023»,
а также ссылки на kad.arbitr.ru (из имени PDF-файла акта берутся номер дела, дата и вид акта).
Несколько ссылок в одном тексте — несколько актов.
"""
import datetime as dt
import re
import urllib.parse

KINDS = ["Определение", "Постановление", "Решение", "Апелляционное определение", "Кассационное определение",
         "Обзор судебной практики", "Постановление Пленума", "Информационное письмо"]
COURTS = ["Верховного Суда РФ", "Судебной коллегии по экономическим спорам Верховного Суда РФ",
          "Судебной коллегии по гражданским делам Верховного Суда РФ", "Конституционного Суда РФ",
          "Президиума ВАС РФ", "Арбитражного суда Московского округа", "Арбитражного суда Северо-Западного округа",
          "Арбитражного суда Поволжского округа", "Арбитражного суда Уральского округа",
          "Девятого арбитражного апелляционного суда", "Второго кассационного суда общей юрисдикции",
          "Московского городского суда"]

_MON = {"январ": 1, "феврал": 2, "март": 3, "апрел": 4, "мая": 5, "май": 5, "июн": 6, "июл": 7, "август": 8,
        "сентябр": 9, "октябр": 10, "ноябр": 11, "декабр": 12}
_MON_RE = r"(?:январ[яь]|феврал[яь]|марта?|апрел[яь]|ма[яй]|июн[яь]|июл[яь]|августа?|сентябр[яь]|октябр[яь]|ноябр[яь]|декабр[яь])"
_DATE = rf"(\d{{1,2}}\.\d{{1,2}}\.(?:19|20)\d\d|\d{{1,2}}\s+{_MON_RE}\s+(?:19|20)\d\d)(?:\s*г(?:ода|\.)?)?"
_KIND = (r"(?P<kind>апелляционн\w*\s+определени\w*|кассационн\w*\s+определени\w*|"
         r"постановлени\w*\s+пленума|определени\w*|постановлени\w*|решени\w*|обзор\w*(?:\s+судебной\s+практики)?|"
         r"информационн\w*\s+письм\w*)")
CITE_RE = re.compile(_KIND + r"(?P<court>(?:\s+(?!от\s)[^\s,;]+){0,14}?)\s*,?\s*от\s+" + _DATE +
                     r"(?P<tail>[^\n;]{0,160})", re.I)
REVIEW_RE = re.compile(r"(?:п(?:ункт)?\.?\s*(?P<pt>\d+)\s+)?обзор\w*\s+(?P<name>судебной\s+практики[^,\n;]{0,120}?)"
                       r"(?:,\s*)?утв(?:ержд\w*|\.)?\s+(?P<who>президиум\w*\s+(?:верховного\s+суда|вс)\s*(?:рф|российской\s+федерации)?)"
                       r"\s*(?:от\s+)?" + _DATE, re.I)
NUM_RE = re.compile(r"^\s*(?:,\s*)?(?:№|N|No\.?)\s*(?P<num>[0-9A-ZА-ЯЁ][\w\-–/.()]*(?:\s*\(\d+\))?)", re.I)
CASE_RE = re.compile(r"по\s+делу\s+(?:№|N)\s*(?P<case>[\wА-ЯЁа-яё][\w\-–/.]*)", re.I)
URL_RE = re.compile(r"https?://\S+", re.I)
KAD_PDF_RE = re.compile(r"/([AА]\d{1,3}-\d+-\d{4})_(\d{8})_([A-Za-z_]+)\.pdf", re.I)
_KAD_KINDS = {"opredelenie": "Определение", "postanovlenie": "Постановление", "reshenie": "Решение",
              "resheniya": "Решение", "postanovleniya": "Постановление"}


def _date(s):
    s = (s or "").strip()
    m = re.match(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", s)
    try:
        if m:
            return dt.date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        m = re.match(rf"(\d{{1,2}})\s+({_MON_RE})\s+(\d{{4}})", s, re.I)
        if m:
            mon = next(v for k, v in sorted(_MON.items(), key=lambda kv: -len(kv[0])) if m.group(2).lower().startswith(k))
            return dt.date(int(m.group(3)), mon, int(m.group(1)))
    except (ValueError, StopIteration):
        pass
    return None


def fmt_date(d):
    return d.strftime("%d.%m.%Y") if isinstance(d, dt.date) else (d or "")


def _kind(word):
    w = word.lower()
    if w.startswith("апелляц"):
        return "Апелляционное определение"
    if w.startswith("кассац"):
        return "Кассационное определение"
    if "пленум" in w:
        return "Постановление Пленума"
    if w.startswith("определ"):
        return "Определение"
    if w.startswith("постанов"):
        return "Постановление"
    if w.startswith("решени"):
        return "Решение"
    if w.startswith("обзор"):
        return "Обзор судебной практики"
    if w.startswith("информ"):
        return "Информационное письмо"
    return word.strip().capitalize()


_COURT_FIX = [(r"^(?:верховн\w*\s+суд\w*|вс)\s*(?:рф|российской\s+федерации)$", "Верховного Суда РФ"),
              (r"^(?:конституционн\w*\s+суд\w*|кс)\s*(?:рф|российской\s+федерации)$", "Конституционного Суда РФ"),
              (r"^(?:скэс|судебн\w*\s+коллеги\w*\s+по\s+экономическим\s+спорам)\s+(?:верховного\s+суда|вс)\s*(?:рф|российской\s+федерации)$",
               "Судебной коллегии по экономическим спорам Верховного Суда РФ"),
              (r"^(?:скгд|судебн\w*\s+коллеги\w*\s+по\s+гражданским\s+делам)\s+(?:верховного\s+суда|вс)\s*(?:рф|российской\s+федерации)$",
               "Судебной коллегии по гражданским делам Верховного Суда РФ"),
              (r"^президиум\w*\s+(?:вас|высшего\s+арбитражного\s+суда)\s*(?:рф|российской\s+федерации)$", "Президиума ВАС РФ"),
              (r"^(?:ас|арбитражн\w*\s+суд\w*)\s+(\w+)\s+округа$", None)]


def norm_court(s):
    s = re.sub(r"\s+", " ", (s or "").strip(" ,.")).strip()
    for rx, name in _COURT_FIX:
        m = re.match(rx, s, re.I)
        if m:
            if name is None:
                return f"Арбитражного суда {m.group(1)} округа"
            return name
    return s


def label(r):
    """«Определение Верховного Суда РФ от 12.03.2024 № 305-ЭС23-1234 (дело № А40-1/2023)»."""
    if (r.get("title") or "").strip():
        return r["title"].strip()
    parts = [r.get("act_kind") or "Судебный акт"]
    if r.get("court"):
        parts.append(r["court"])
    if r.get("act_date"):
        parts.append(f"от {r['act_date']}")
    if r.get("number"):
        parts.append(f"№ {r['number']}")
    s = " ".join(parts)
    if r.get("case_no") and r.get("case_no") != r.get("number"):
        s += (f" по делу № {r['case_no']}" if not r.get("number") else f" (дело № {r['case_no']})")
    return s


_SHORT = [(r"^Апелляционное определение\b", "Апелл. опр."), (r"^Кассационное определение\b", "Касс. опр."),
          (r"^Определение\b", "Опр."), (r"^Постановление Пленума\b", "Пост. Пленума"), (r"^Постановление\b", "Пост."),
          (r"^Решение\b", "Реш."),
          (r"Судебной коллегии по экономическим спорам Верховного Суда РФ", "СКЭС ВС РФ"),
          (r"Судебной коллегии по гражданским делам Верховного Суда РФ", "СКГД ВС РФ"),
          (r"Верховного Суда (?:РФ|Российской Федерации)", "ВС РФ"),
          (r"Конституционного Суда (?:РФ|Российской Федерации)", "КС РФ"),
          (r"Арбитражного суда (\S+) округа", r"АС \1 округа"),
          (r"арбитражного апелляционного суда", "ААС"), (r"кассационного суда общей юрисдикции", "КСОЮ"),
          (r"Обзора судебной практики", "Обзора практики")]


def short_label(r):
    """Коротко для списка: «Опр. ВС РФ от 12.03.2024 № 305-ЭС23-1234»."""
    s = label(r)
    for rx, rep in _SHORT:
        s = re.sub(rx, rep, s)
    return s


def _clean_num(n):
    return (n or "").strip().rstrip(".,;:)").strip()


def parse(text):
    """Судебные акты из текста: [{act_kind, court, act_date, number, case_no, url, raw}]."""
    text = (text or "").replace(" ", " ")
    out, used = [], []
    for m in REVIEW_RE.finditer(text):
        d = _date(m.groups()[-1])
        name = re.sub(r"\s+", " ", m.group("name")).strip()
        title = (f"п. {m.group('pt')} " if m.group("pt") else "") + "Обзора " + name + \
            f", утв. Президиумом Верховного Суда РФ {fmt_date(d)}"
        out.append(dict(act_kind="Обзор судебной практики", court="Верховного Суда РФ", act_date=fmt_date(d),
                        number="", case_no="", url="", raw=m.group(0), title=title))
        used.append(m.span())
    for m in CITE_RE.finditer(text):
        if any(a <= m.start() < b for a, b in used):
            continue
        kind = _kind(m.group("kind"))
        if kind == "Обзор судебной практики":
            continue
        court = norm_court(m.group("court"))
        d = _date(m.group(3))
        tail = m.group("tail") or ""
        num = NUM_RE.match(tail)
        case = CASE_RE.search(tail)
        number = _clean_num(num.group("num")) if num else ""
        case_no = _clean_num(case.group("case")) if case else ""
        if number and case_no and number == case_no:
            number = ""
        if not (number or case_no) and re.fullmatch(r"(?:суда?|судом|первой\s+инстанции|по\s+делу)?", court, re.I):
            continue                       # «решение от 01.02.2024» без суда и номера — это не ссылка на практику
        out.append(dict(act_kind=kind, court=court, act_date=fmt_date(d), number=number, case_no=case_no,
                        url="", raw=m.group(0).strip()))
    urls = URL_RE.findall(text)
    for u in urls:
        u = u.rstrip(").,;»\"'")
        k = KAD_PDF_RE.search(urllib.parse.unquote(u))
        if k:
            case_no = k.group(1).replace("A", "А", 1)
            case_no = re.sub(r"^(А\d+-\d+)-(\d{4})$", r"\1/\2", case_no)
            d = dt.datetime.strptime(k.group(2), "%Y%m%d").date()
            kind = _KAD_KINDS.get(k.group(3).split("_")[0].lower(), "Судебный акт")
            out.append(dict(act_kind=kind, court="", act_date=fmt_date(d), number="", case_no=case_no, url=u, raw=u))
        elif len(out) == 1 and not out[0]["url"]:
            out[0]["url"] = u                # одна ссылка на акт + адрес — адрес к нему
        elif not out:
            out.append(dict(act_kind="Судебный акт", court="", act_date="", number="", case_no="", url=u, raw=u,
                            title=f"Судебный акт ({_host(u)})"))
    return out


def _host(u):
    try:
        return urllib.parse.urlparse(u).netloc.replace("www.", "")
    except Exception:
        return u


def key(r):
    """Для поиска повторов: номер акта или номер дела + дата."""
    n = re.sub(r"[\s–]", "", (r.get("number") or "")).lower().replace("-", "")
    if n:
        return "n:" + n
    c = re.sub(r"\s", "", (r.get("case_no") or "")).lower()
    if c:
        return f"c:{c}:{r.get('act_date', '')}:{(r.get('act_kind') or '')[:5].lower()}"
    if r.get("url"):
        return "u:" + r["url"].strip().lower()
    if (r.get("title") or "").strip():
        return "t:" + re.sub(r"\s+", " ", r["title"].strip().lower())
    return ""


def search_url(r):
    """Найти текст акта: поиск по номеру на КонсультантПлюс (или карточка дела на kad.arbitr.ru)."""
    q = " ".join(x for x in (r.get("act_kind"), r.get("court"), ("от " + r["act_date"]) if r.get("act_date") else "",
                             ("№ " + r["number"]) if r.get("number") else "",
                             ("по делу № " + r["case_no"]) if r.get("case_no") else "") if x)
    return "https://www.consultant.ru/search/?q=" + urllib.parse.quote(q)
