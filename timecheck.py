# -*- coding: utf-8 -*-
"""
Проверка часов компьютера по точному времени из интернета (без интерфейса).

Сроки, заседания и напоминания считаются по часам компьютера. Если они сбились (села батарейка,
неверный часовой пояс, отключена синхронизация Windows), программа предупреждает и сама
вносит поправку в напоминания (M.CLOCK_OFFSET).
"""
import datetime as dt
import email.utils
import time
import urllib.error
import urllib.request

# сайты, которые отдают точное время в заголовке Date; берётся первый ответивший
SOURCES = ("https://ya.ru", "https://www.google.com",
           "https://raw.githubusercontent.com/ezdk20000-code/LegalHelper/main/version.json")
WARN_SECONDS = 120


def clock_offset(timeout=6):
    """Насколько точное время впереди часов компьютера, в секундах (отрицательное — часы спешат).
    None — нет интернета."""
    for url in SOURCES:
        try:
            req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "LegalHelper-clock"})
            t0 = time.time()
            try:
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    date = r.headers.get("Date")
            except urllib.error.HTTPError as e:      # ответ с ошибкой тоже несёт точное время
                date = e.headers.get("Date") if e.headers else None
            t1 = time.time()
            if not date:
                continue
            server = email.utils.parsedate_to_datetime(date).timestamp()
            # заголовок Date точен до секунды — сравниваем с серединой запроса
            return server - (t0 + t1) / 2
        except Exception:
            continue
    return None


def describe(offset):
    """'спешат на 5 мин' / 'отстают на 2 ч 3 мин'."""
    sec = abs(int(round(offset)))
    h, m = sec // 3600, (sec % 3600) // 60
    parts = ([f"{h} ч"] if h else []) + ([f"{m} мин"] if m or not h else [])
    return ("отстают" if offset > 0 else "спешат") + " на " + " ".join(parts)


def utc_offset_text():
    """Часовой пояс компьютера, например 'UTC+3'."""
    off = dt.datetime.now().astimezone().utcoffset() or dt.timedelta(0)
    mins = int(off.total_seconds() // 60)
    sign = "+" if mins >= 0 else "−"
    mins = abs(mins)
    return f"UTC{sign}{mins // 60}" + (f":{mins % 60:02d}" if mins % 60 else "")
