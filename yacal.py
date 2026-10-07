# -*- coding: utf-8 -*-
"""
Сроки и заседания — в Яндекс Календарь (CalDAV) и в файл календаря (.ics). Без Qt.

Синхронизация — «сравнить и выровнять»: программа помнит, какие события уже отправила (номер события → отпечаток
его содержимого). Новое или изменённое — отправить (PUT), удалённое, выполненное, ушедшее в архив — убрать
из календаря (DELETE). Трогаем только свои события: их адреса начинаются с «legalhelper-».
"""
import base64
import datetime as dt
import hashlib
import json
import re
import urllib.error
import urllib.parse
import urllib.request

SERVER = "https://caldav.yandex.ru"
PREFIX = "legalhelper-"
DAV = "DAV:"
CAL = "urn:ietf:params:xml:ns:caldav"
KIND_ICON = {"Заседание": "⚖️", "Срок": "⏳", "Задача": "✅", "Встреча": "🤝", "Напоминание": "⏰"}


class CalError(Exception):
    pass


# ============================================================================ события → iCalendar
def _esc(s):
    return (str(s or "").replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
            .replace("\r\n", "\\n").replace("\n", "\\n"))


def _fold(line):
    """Строки iCalendar не длиннее 75 байт: длинные переносятся с пробелом в начале."""
    b = line.encode("utf-8")
    if len(b) <= 75:
        return line
    out, cur = [], b""
    for ch in line:
        e = ch.encode("utf-8")
        if len(cur) + len(e) > (75 if not out else 74):
            out.append(cur.decode("utf-8"))
            cur = b""
        cur += e
    out.append(cur.decode("utf-8"))
    return "\r\n ".join(out)


def summary(e):
    """«⚖️ Предварительное судебное заседание — ООО Ромашка», «⏳ Срок: отзыв — ООО Ромашка»."""
    case = e.get("case_title") or ""
    title = (e.get("title") or "").strip()
    icon = KIND_ICON.get(e["kind"], "")
    if not title:
        s = e["kind"]
    elif e["kind"] == "Заседание" and re.search(r"заседани|беседа|слушани", title, re.I) or e["kind"] in title:
        s = title
    else:
        s = f"{e['kind']}: {title}"
    s = f"{icon} {s}".strip()
    return f"{s} — {case}" if case else s


def vevent(e, stamp=None):
    stamp = stamp or dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    d = dt.date.fromisoformat(e["date"])
    lines = ["BEGIN:VEVENT", f"UID:{PREFIX}{e['id']}@legalhelper", f"DTSTAMP:{stamp}"]
    t = (e.get("time") or "").strip()
    m = re.match(r"^(\d{1,2}):(\d{2})$", t)
    if m:                                             # местное время компьютера → UTC
        start = dt.datetime(d.year, d.month, d.day, int(m.group(1)), int(m.group(2))).astimezone()
        hours = 2 if e["kind"] == "Заседание" else 1
        utc = start.astimezone(dt.timezone.utc)
        lines += [f"DTSTART:{utc:%Y%m%dT%H%M%SZ}", f"DTEND:{utc + dt.timedelta(hours=hours):%Y%m%dT%H%M%SZ}"]
    else:
        lines += [f"DTSTART;VALUE=DATE:{d:%Y%m%d}", f"DTEND;VALUE=DATE:{d + dt.timedelta(days=1):%Y%m%d}",
                  "TRANSP:TRANSPARENT"]
    lines.append("SUMMARY:" + _esc(summary(e)))
    if e.get("place"):
        lines.append("LOCATION:" + _esc(e["place"]))
    desc = [x for x in (f"Дело: {e.get('case_title')}" if e.get("case_title") else "",
                        f"№ {e.get('case_number')}" if e.get("case_number") else "",
                        f"Место: {e.get('place')}" if e.get("place") else "", "Из программы LegalHelper") if x]
    lines.append("DESCRIPTION:" + _esc("\n".join(desc)))
    lines.append("CATEGORIES:" + _esc(e["kind"]))
    for trig, text in (("-P1D", "Завтра"), ("-PT2H" if m else "-PT15H", "Скоро")):
        lines += ["BEGIN:VALARM", "ACTION:DISPLAY", f"TRIGGER:{trig}", "DESCRIPTION:" + _esc(f"{text}: {summary(e)}"),
                  "END:VALARM"]
    lines.append("END:VEVENT")
    return lines


def calendar(events, name="LegalHelper — сроки и заседания"):
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//LegalHelper//RU", "CALSCALE:GREGORIAN",
             "X-WR-CALNAME:" + _esc(name)]
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    for e in events:
        lines += vevent(e, stamp)
    lines.append("END:VCALENDAR")
    return "\r\n".join(_fold(x) for x in lines) + "\r\n"


def fingerprint(e):
    key = json.dumps([e["date"], e.get("time"), e["kind"], e.get("title"), e.get("place"), e.get("case_title"),
                      e.get("case_number")], ensure_ascii=False)
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


def wanted(events, today=None, past_days=30):
    """Что должно быть в календаре: невыполненные события действующих дел, не старше месяца."""
    today = today or dt.date.today()
    since = (today - dt.timedelta(days=past_days)).isoformat()
    out = {}
    for e in events:
        if e.get("done") or not e.get("date") or e["date"] < since or e.get("archived"):
            continue
        if e.get("case_id") and e.get("case_title") is None:   # дело удалено
            continue
        out[str(e["id"])] = e
    return out


def plan(events, state, today=None):
    """(отправить [событие], убрать [номер]) — разница между тем, что есть в программе, и тем, что уже отправлено."""
    want = wanted(events, today)
    put = [e for k, e in want.items() if state.get(k) != fingerprint(e)]
    drop = [k for k in state if k not in want]
    return put, drop


# ============================================================================ CalDAV
class Client:
    def __init__(self, login, password, server=None, timeout=20):
        self.server = (server or SERVER).rstrip("/")
        self.timeout = timeout
        self.auth = "Basic " + base64.b64encode(f"{login}:{password}".encode("utf-8")).decode("ascii")

    def request(self, method, url, body=None, headers=None, ok=(200, 201, 204, 207)):
        if not url.startswith("http"):
            url = self.server + url
        h = {"Authorization": self.auth, "User-Agent": "LegalHelper"}
        h.update(headers or {})
        data = body.encode("utf-8") if isinstance(body, str) else body
        req = urllib.request.Request(url, data=data, method=method, headers=h)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return r.status, r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            if e.code in ok:
                return e.code, e.read().decode("utf-8", "replace")
            if e.code in (401, 403):
                raise CalError("Яндекс не принял логин или пароль приложения. Проверьте их в настройках календаря: "
                               "нужен именно пароль приложения (id.yandex.ru → Безопасность → Пароли приложений → "
                               "«Календарь CalDAV»), а не обычный пароль от почты.") from None
            raise CalError(f"Календарь ответил ошибкой {e.code} на {method}") from None
        except urllib.error.URLError as e:
            raise CalError(f"Нет связи с Яндекс Календарём: {e.reason}") from None
        except OSError as e:
            raise CalError(f"Нет связи с Яндекс Календарём: {e}") from None

    def propfind(self, url, props, depth="0"):
        body = ('<?xml version="1.0" encoding="utf-8"?><d:propfind xmlns:d="DAV:" '
                'xmlns:c="urn:ietf:params:xml:ns:caldav"><d:prop>' + props + "</d:prop></d:propfind>")
        _st, text = self.request("PROPFIND", url, body, {"Depth": depth,
                                                         "Content-Type": "application/xml; charset=utf-8"})
        return text

    @staticmethod
    def _hrefs(xml, prop):
        """Ссылки внутри свойства, например current-user-principal → [/principals/…]."""
        out = []
        for m in re.finditer(rf"<(?:\w+:)?{prop}[^>]*>(.*?)</(?:\w+:)?{prop}>", xml, re.S):
            out += re.findall(r"<(?:\w+:)?href[^>]*>\s*([^<\s]+)\s*</(?:\w+:)?href>", m.group(1))
        return [urllib.parse.unquote(h) for h in out]

    def calendars(self):
        """[(адрес, название)] календарей с событиями (VEVENT)."""
        principal = self._hrefs(self.propfind("/", "<d:current-user-principal/>"), "current-user-principal")
        if not principal:
            raise CalError("Не удалось найти календарь в учётной записи Яндекса")
        home = self._hrefs(self.propfind(principal[0], "<c:calendar-home-set/>"), "calendar-home-set")
        if not home:
            raise CalError("Не удалось найти календари в учётной записи Яндекса")
        xml = self.propfind(home[0], "<d:resourcetype/><d:displayname/><c:supported-calendar-component-set/>", "1")
        out = []
        for resp in re.findall(r"<(?:\w+:)?response[^>]*>(.*?)</(?:\w+:)?response>", xml, re.S):
            href = re.search(r"<(?:\w+:)?href[^>]*>\s*([^<\s]+)\s*<", resp)
            if not href or not re.search(r"<(?:\w+:)?calendar\s*/>", resp):
                continue
            comps = re.findall(r'name="(\w+)"', resp)
            if comps and "VEVENT" not in comps:
                continue
            name = re.search(r"<(?:\w+:)?displayname[^>]*>(.*?)</", resp, re.S)
            out.append((urllib.parse.unquote(href.group(1)), (name.group(1).strip() if name else "") or "Календарь"))
        if not out:
            raise CalError("В Яндекс Календаре нет ни одного календаря для событий")
        return out

    def put(self, cal, e):
        body = calendar([e])
        self.request("PUT", self._url(cal, e["id"]), body, {"Content-Type": "text/calendar; charset=utf-8"})

    def delete(self, cal, eid):
        self.request("DELETE", self._url(cal, eid), ok=(200, 204, 404, 410))

    @staticmethod
    def _url(cal, eid):
        return cal.rstrip("/") + f"/{PREFIX}{eid}.ics"


def sync(client, cal, events, state, today=None, progress=None):
    """Выровнять календарь. Возвращает (новое состояние, отправлено, убрано). Ошибка на полпути — CalError,
    но уже сделанное сохраняется в state (передаётся тот же словарь)."""
    put, drop = plan(events, state, today)
    for e in put:
        client.put(cal, e)
        state[str(e["id"])] = fingerprint(e)
        if progress:
            progress()
    for k in drop:
        client.delete(cal, k)
        state.pop(k, None)
        if progress:
            progress()
    return state, len(put), len(drop)

