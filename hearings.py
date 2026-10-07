# -*- coding: utf-8 -*-
"""
Даты из судебных актов: «назначить предварительное судебное заседание на 12 ноября 2026 года в 10 час. 30 мин.,
зал № 5», «отложить рассмотрение дела на 03.12.2026 на 14:15», «объявить перерыв до 15.11.2026 до 9 час. 30 мин.»,
«представить отзыв в срок до 01.11.2026». Возвращает готовые события для календаря дела. Без Qt — проверяется тестами.
"""
import datetime as dt
import re

MONTHS = {"января": 1, "февраля": 2, "марта": 3, "апреля": 4, "мая": 5, "июня": 6, "июля": 7, "августа": 8,
          "сентября": 9, "октября": 10, "ноября": 11, "декабря": 12}
_MON = "|".join(MONTHS)
DATE_RX = re.compile(rf"«?(\d{{1,2}})»?\s+({_MON})\s+(\d{{4}})\s*(?:года|г\.)?|"
                     r"\b(\d{1,2})\.(\d{1,2})\.(\d{4})(?:\s*(?:года|г\.))?", re.I)
TIME_RX = re.compile(r"^[\s,]*(?:в|на|до|с)?\s*(?:"
                     r"(\d{1,2})\s*(?:час(?:а|ов)?\.?|ч\.)\s*(\d{1,2})\s*мин(?:ут[аы]?|\.)?|"
                     r"(\d{1,2})\s*(?:час(?:а|ов)?\.?|ч\.)(?!\s*\d)|"
                     r"(\d{1,2})[:\-](\d{2})(?!\d))", re.I)
HALL_RX = re.compile(r"(?:в\s+)?(зал[а-я]*\s*(?:судебн\w+\s+заседани\w+\s*)?(?:№\s*)?[\w/-]*\d[\w/-]*|"
                     r"(?:каб(?:инет[а-я]*)?\.?)\s*№?\s*\d[\w/-]*)", re.I)
ADDR_RX = re.compile(r"по\s+адресу:?\s*([^;]{6,140}?)(?=,?\s*(?:в\s+)?(?:зал|каб)|\.\s+\d{1,2}\.\s|;|$)", re.I)

_HEAR = re.compile(r"заседани|разбирательств|рассмотрени|отлож|перерыв|бесед|слушани", re.I)
_DEADLINE_PREFIX = re.compile(r"(?:в\s+срок\s+)?(?:до|не\s+позднее|не\s+позже|по)\s*$", re.I)
_ON_PREFIX = re.compile(r"\bна\s*$|заседани\w*[:\s]*$", re.I)


def _norm(text):
    text = re.sub(r"-\s*\n\s*", "", text or "")              # перенос слова в PDF
    return re.sub(r"\s+", " ", text)


def _date(m):
    try:
        if m.group(1):
            return dt.date(int(m.group(3)), MONTHS[m.group(2).lower()], int(m.group(1)))
        return dt.date(int(m.group(6)), int(m.group(5)), int(m.group(4)))
    except (ValueError, KeyError):
        return None


def _time(after):
    m = TIME_RX.match(after)
    if not m:
        return ""
    h, mi = (m.group(1), m.group(2)) if m.group(1) else (m.group(3), "0") if m.group(3) else (m.group(4), m.group(5))
    h, mi = int(h), int(mi)
    return f"{h:02d}:{mi:02d}" if 7 <= h <= 21 and 0 <= mi < 60 else ""


def _place(after):
    """Зал и адрес — только в ближайших словах после даты (до следующего предложения о другом)."""
    after = re.split(r"(?<=[^.])\.\s+(?=[А-ЯЁ][а-яё]+\s+(?:представить|направить|предложить|обязать|вызвать|"
                     r"известить|разъяснить|лиц))", after[:260])[0]
    after = re.split(r"\b\d{1,2}\.\d{1,2}\.\d{4}\b", after)[0]       # до следующей даты — уже другое событие
    out = []
    a = ADDR_RX.search(after)
    if a:
        out.append(a.group(1).strip(" ,"))
    for h in list(HALL_RX.finditer(after))[:2]:
        t = re.sub(r"\s+", " ", h.group(1)).strip(" ,.")
        t = re.sub(r"^зал[а-я]*(?:\s+судебн\w+\s+заседани\w+)?", "зал", t, flags=re.I)
        if t not in out:
            out.append(t)
    return ", ".join(out)


def _hear_title(ctx):
    c = ctx.lower()
    if "перерыв" in c:
        return "Судебное заседание (после перерыва)"
    if "бесед" in c:
        return "Беседа (подготовка дела)"
    if "предварительн" in c:
        return "Предварительное судебное заседание"
    if "апелляц" in c:
        return "Заседание апелляции"
    if "кассац" in c:
        return "Заседание кассации"
    return "Судебное заседание"


def _deadline_title(ctx):
    """«Истцу представить письменные пояснения в срок до» → «Истцу представить письменные пояснения»."""
    s = _DEADLINE_PREFIX.sub("", ctx).strip(" ,:;")
    s = re.split(r"[;:]|(?<![№\d])\.\s+|\b\d{1,2}\)\s|\s\d\.\s", s)[-1].strip(" ,")
    if len(s) > 90:
        s = s[-90:]
        s = s[s.find(" ") + 1:]
    s = re.sub(r"^\d{1,2}[.)]\s*", "", s)
    s = s[:1].upper() + s[1:]
    return s or "Срок по определению суда"


def parse(text, today=None):
    """[{kind, title, date (ГГГГ-ММ-ДД), time, place, snippet}] — заседания и сроки не раньше сегодняшнего дня."""
    text = _norm(text)
    today = today or dt.date.today()
    out, prev_end, seen = [], 0, set()
    for m in DATE_RX.finditer(text):
        d = _date(m)
        start, end = m.start(), m.end()
        ctx = text[max(prev_end, start - 220):start]
        prev_end = end
        if not d or d < today or d.year > today.year + 3:
            continue
        after = text[end:end + 300]
        tail = ctx[-40:]
        ev = None
        if _DEADLINE_PREFIX.search(tail):
            if re.search(r"перерыв", ctx, re.I):
                ev = dict(kind="Заседание", title=_hear_title(ctx), time=_time(after), place=_place(after))
            elif re.search(r"\bпо\s*$", tail, re.I) and not re.search(r"срок", ctx[-80:], re.I):
                continue                                     # «с 01.01 по 31.03» — период, не срок
            else:
                ev = dict(kind="Срок", title=_deadline_title(ctx), time="", place="")
        elif _ON_PREFIX.search(tail) and _HEAR.search(ctx):
            ev = dict(kind="Заседание", title=_hear_title(ctx), time=_time(after), place=_place(after))
        if not ev:
            continue
        key = (ev["kind"], d, ev["time"])
        if key in seen:
            continue
        seen.add(key)
        snip = text[max(0, start - 120):end + 60].strip()
        ev.update(date=d.isoformat(), snippet=("…" if start > 120 else "") + snip + "…")
        out.append(ev)
    return out


def describe(ev):
    """«12 ноября 2026, 10:30 — Судебное заседание, зал № 5»."""
    d = dt.date.fromisoformat(ev["date"])
    months = list(MONTHS)
    s = f"{d.day} {months[d.month - 1]} {d.year}"
    if ev.get("time"):
        s += f", {ev['time']}"
    s += f" — {ev['title']}"
    if ev.get("place"):
        s += f", {ev['place']}"
    return s


def is_known(ev, existing):
    """Такое событие уже есть в деле (та же дата и вид; время — если указано у обоих)."""
    for e in existing:
        if e["date"] == ev["date"] and e["kind"] == ev["kind"] and (
                not ev["time"] or not e.get("time") or e["time"] == ev["time"]):
            return True
    return False


_KAD_DT = re.compile(r"\b(\d{2})\.(\d{2})\.(\d{4})[,\s]+(?:в\s+)?(\d{1,2}):(\d{2})\b")


def parse_kad(text, today=None):
    """Карточка дела на kad.arbitr.ru: «Дата и время судебного заседания 03.12.2026, 14:15, Зал № 5012»,
    «Судебное заседание назначено на 12.11.2026 10:30» — плюс всё, что понимает parse()."""
    text = _norm(text)
    today = today or dt.date.today()
    out = parse(text, today)
    for m in _KAD_DT.finditer(text):
        try:
            d = dt.date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except ValueError:
            continue
        if d < today or not re.search(r"заседани|назнач|отлож", text[max(0, m.start() - 200):m.start()], re.I):
            continue
        ev = dict(kind="Заседание", title=_hear_title(text[max(0, m.start() - 200):m.start()]),
                  date=d.isoformat(), time=f"{int(m.group(4)):02d}:{m.group(5)}", place=_place(text[m.end():]),
                  snippet=text[max(0, m.start() - 120):m.end() + 60])
        if not is_known(ev, out):
            out.append(ev)
    return sorted(out, key=lambda e: (e["date"], e["time"]))
