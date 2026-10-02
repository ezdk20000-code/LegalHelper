# -*- coding: utf-8 -*-
"""
Нормы права без ручного набора.

* parse(text) — разбирает ссылки на нормы, написанные как в иске: «п. 1 ст. 395 ГК РФ», «ст. 309, 310 ГК»,
  «статьей 395 Гражданского кодекса Российской Федерации», «ч. 1 ст. 110 АПК РФ»,
  «постановление Пленума ВС РФ от 24.03.2016 № 7», «Федеральный закон от 26.10.2002 № 127-ФЗ».
  Каждая ссылка — акт (кодекс, закон, постановление) и статья с пунктом/частью.
* find_in_text(pages) — все ссылки в тексте документов дела с номерами страниц.
* library(db) — «мои нормы»: всё, что юрист уже добавлял в любые дела (текст и комментарий берутся оттуда),
  плюс короткий стартовый набор самых частых статей.
* url_for(...) — ссылка на поиск нормы в КонсультантПлюс.
"""
import re
import urllib.parse

# Кодексы и законы: (ключ, официальное короткое название, шаблон полного названия в любом падеже, сокращения)
ACTS = [
    ("ГК", "Гражданский кодекс РФ", r"гражданск\w*\s+кодекс\w*", ["ГК РФ", "ГК"]),
    ("АПК", "Арбитражный процессуальный кодекс РФ", r"арбитражн\w*\s+процессуальн\w*\s+кодекс\w*", ["АПК РФ", "АПК"]),
    ("ГПК", "Гражданский процессуальный кодекс РФ", r"гражданск\w*\s+процессуальн\w*\s+кодекс\w*", ["ГПК РФ", "ГПК"]),
    ("КАС", "Кодекс административного судопроизводства РФ", r"кодекс\w*\s+административн\w*\s+судопроизводств\w*",
     ["КАС РФ", "КАС"]),
    ("НК", "Налоговый кодекс РФ", r"налогов\w*\s+кодекс\w*", ["НК РФ", "НК"]),
    ("ТК", "Трудовой кодекс РФ", r"трудов\w*\s+кодекс\w*", ["ТК РФ", "ТК"]),
    ("ЖК", "Жилищный кодекс РФ", r"жилищн\w*\s+кодекс\w*", ["ЖК РФ", "ЖК"]),
    ("СК", "Семейный кодекс РФ", r"семейн\w*\s+кодекс\w*", ["СК РФ"]),
    ("ЗК", "Земельный кодекс РФ", r"земельн\w*\s+кодекс\w*", ["ЗК РФ"]),
    ("БК", "Бюджетный кодекс РФ", r"бюджетн\w*\s+кодекс\w*", ["БК РФ"]),
    ("УК", "Уголовный кодекс РФ", r"уголовн\w*\s+кодекс\w*", ["УК РФ"]),
    ("УПК", "Уголовно-процессуальный кодекс РФ", r"уголовно-процессуальн\w*\s+кодекс\w*", ["УПК РФ"]),
    ("КоАП", "Кодекс РФ об административных правонарушениях",
     r"кодекс\w*\s+(?:российской федерации\s+|рф\s+)?об\s+административн\w*\s+правонарушени\w*", ["КоАП РФ", "КоАП"]),
    ("ЗоЗПП", "Закон РФ от 07.02.1992 № 2300-1 «О защите прав потребителей»",
     r"закон\w*\s+(?:рф\s+|российской федерации\s+)?(?:от 07\.02\.1992\s*(?:г\.)?\s*№\s*2300-1\s*)?«?\"?о защите прав потребителей",
     ["ЗоЗПП", "Закона о защите прав потребителей", "Закон о защите прав потребителей"]),
]
ACT_BY_KEY = {a[0]: a for a in ACTS}

_ART = r"(?:ст(?:ат\w*|\.\s*ст)?\.?)"
_NUM = r"\d+(?:\.\d+)*"
_NUMS = rf"{_NUM}(?:\s*(?:,|и|-|–)\s*{_NUM})*"
_SUB = r"(?:(?:п(?:ункт\w*)?|пп|подп(?:ункт\w*)?|ч(?:аст\w*)?|абз(?:ац\w*)?)\.?\s*\d+(?:\.\d+)?(?:\s*,\s*\d+)*\s*)"


def _act_alternatives():
    alts = []
    for key, title, full, abbr in ACTS:
        parts = [full] + [re.escape(a).replace(r"\ ", r"\s+") for a in sorted(abbr, key=len, reverse=True)]
        alts.append((key, "(?:" + "|".join(parts) + r")(?:\s+(?:российской федерации|рф))?"))
    return alts


_ACT_ALTS = _act_alternatives()
_ACT_RE = "|".join(f"(?P<{k}>{p})" for k, p in _ACT_ALTS)
CITE_RE = re.compile(rf"(?P<sub>(?:{_SUB}(?:,\s*|и\s+)?)*)\b{_ART}\s*(?P<arts>{_NUMS})\s*(?:{_ACT_RE})(?![а-яё])",
                     re.I)
PLENUM_RE = re.compile(r"(?:п\.\s*(?P<pt>\d+)\s+)?постановлени\w*\s+пленума\s+(?P<court>верховного\s+суда|вс|высшего\s+"
                       r"арбитражного\s+суда|вас)\s*(?:рф|российской\s+федерации)?\s*от\s*(?P<date>\d{1,2}\.\d{1,2}\."
                       r"\d{4})\s*(?:г\.?)?\s*№\s*(?P<no>\d+)", re.I)
FZ_RE = re.compile(r"(?:(?P<sub>(?:п|ч)\.\s*\d+\s+)?ст\.\s*(?P<art>\d+(?:\.\d+)*)\s+)?федеральн\w*\s+закон\w*\s+от\s*"
                   r"(?P<date>\d{1,2}\.\d{1,2}\.\d{4})\s*(?:г\.?)?\s*№\s*(?P<no>\d+-фз)(?:\s*[«\"](?P<name>[^»\"]{3,120})[»\"])?",
                   re.I)


def _split_nums(s):
    out = []
    for part in re.split(r"\s*(?:,|и)\s*", s.strip()):
        m = re.match(rf"^({_NUM})\s*[-–]\s*({_NUM})$", part)
        if m and m.group(1).isdigit() and m.group(2).isdigit() and 0 < int(m.group(2)) - int(m.group(1)) <= 20:
            out += [str(n) for n in range(int(m.group(1)), int(m.group(2)) + 1)]
        elif part:
            out.append(part)
    return out


def _sub_label(sub):
    sub = re.sub(r"\s+", " ", (sub or "").strip().rstrip(",")).strip()
    if not sub:
        return ""
    sub = re.sub(r"(?i)\bпункт\w*", "п.", sub)
    sub = re.sub(r"(?i)\bподпункт\w*|\bподп\.?", "пп.", sub)
    sub = re.sub(r"(?i)\bчаст\w*", "ч.", sub)
    sub = re.sub(r"(?i)\bабзац\w*", "абз.", sub)
    sub = re.sub(r"(?i)\b(пп|абз|п|ч)\.?\s*", lambda m: m.group(1).lower() + ". ", sub)
    return re.sub(r"\s+", " ", sub).strip()


def parse(text):
    """Ссылки на нормы в тексте → [{act_key, act, article, label, raw}] (без повторов, в порядке появления)."""
    out, seen = [], set()

    def add(act_key, act, article, label, raw):
        k = (act, label)
        if k not in seen:
            seen.add(k)
            out.append({"act_key": act_key, "act": act, "article": article, "label": label, "raw": raw.strip()})
    for m in CITE_RE.finditer(text or ""):
        key = next((k for k, _ in _ACT_ALTS if m.group(k)), None)
        if not key:
            continue
        arts = _split_nums(m.group("arts"))
        sub = _sub_label(m.group("sub"))
        for i, a in enumerate(arts):
            label = (f"{sub} ст. {a}" if sub and i == 0 else f"ст. {a}").strip()
            add(key, ACT_BY_KEY[key][1], a, label, m.group(0))
    for m in PLENUM_RE.finditer(text or ""):
        court = "ВС РФ" if m.group("court").lower().startswith(("верх", "вс")) else "ВАС РФ"
        act = f"Постановление Пленума {court} от {m.group('date')} № {m.group('no')}"
        label = f"п. {m.group('pt')}" if m.group("pt") else "Правовая позиция"
        add("PLENUM", act, m.group("pt") or "", label, m.group(0))
    for m in FZ_RE.finditer(text or ""):
        act = f"Федеральный закон от {m.group('date')} № {m.group('no').upper().replace('ФЗ', 'ФЗ')}"
        if m.group("name"):
            act += f" «{m.group('name').strip()}»"
        label = (f"{_sub_label(m.group('sub'))} ст. {m.group('art')}".strip() if m.group("art") else "")
        add("FZ", act, m.group("art") or "", label or "Закон в целом", m.group(0))
    return out


def find_in_pages(pages):
    """pages — [(название документа, номер страницы или None, текст)] → [{…ссылка, где: [(док, стр)]}]."""
    found = {}
    order = []
    for doc, page, text in pages:
        for c in parse(text):
            k = (c["act"], c["label"])
            if k not in found:
                found[k] = dict(c, where=[])
                order.append(k)
            w = (doc, page)
            if w not in found[k]["where"]:
                found[k]["where"].append(w)
    return [found[k] for k in order]


def url_for(act, label=""):
    """Поиск нормы в КонсультантПлюс (открывается в браузере)."""
    short = act
    for key, title, _f, abbr in ACTS:
        if title == act:
            short = abbr[0]
    q = f"{label} {short}".strip() if label and label not in ("Правовая позиция", "Закон в целом") else short
    return "https://www.consultant.ru/search/?q=" + urllib.parse.quote(q)


# Короткий стартовый набор частых статей: только номер и о чём статья (текст юрист вставляет сам —
# дальше он подставится из «моих норм»)
STARTER = [
    ("ГК", "ст. 15", "Возмещение убытков"), ("ГК", "ст. 151", "Компенсация морального вреда"),
    ("ГК", "ст. 309", "Общие положения об исполнении обязательств"), ("ГК", "ст. 310", "Недопустимость одностороннего отказа"),
    ("ГК", "ст. 330", "Понятие неустойки"), ("ГК", "ст. 333", "Уменьшение неустойки"),
    ("ГК", "ст. 395", "Ответственность за неисполнение денежного обязательства"),
    ("ГК", "ст. 1064", "Общие основания ответственности за причинение вреда"),
    ("ГК", "ст. 1102", "Обязанность возвратить неосновательное обогащение"),
    ("АПК", "ст. 65", "Обязанность доказывания"), ("АПК", "ст. 110", "Распределение судебных расходов"),
    ("АПК", "ст. 125", "Форма и содержание искового заявления"), ("АПК", "ст. 126", "Документы, прилагаемые к иску"),
    ("ГПК", "ст. 56", "Обязанность доказывания"), ("ГПК", "ст. 98", "Распределение судебных расходов"),
    ("ГПК", "ст. 100", "Возмещение расходов на оплату услуг представителя"),
    ("ГПК", "ст. 131", "Форма и содержание искового заявления"), ("ГПК", "ст. 132", "Документы, прилагаемые к иску"),
    ("НК", "ст. 333.19", "Госпошлина в судах общей юрисдикции"), ("НК", "ст. 333.21", "Госпошлина в арбитражных судах"),
    ("ЗоЗПП", "ст. 13", "Ответственность продавца, штраф 50%"), ("ЗоЗПП", "ст. 15", "Компенсация морального вреда"),
]


def library(db):
    """Мои нормы: [{act, label, body, note, url, uses, source}] — из всех дел (самая свежая запись нормы
    с текстом) и стартовый набор. Сначала самые частые."""
    by = {}
    try:
        cases = db.cases(False) + db.cases(True)
    except Exception:
        cases = []
    for c in cases:
        rows = db.laws(c["id"])
        ids = {r["id"]: r for r in rows}
        for r in rows:
            if r["kind"] != "norm" or not (r["title"] or "").strip():
                continue
            parent = ids.get(r["parent_id"])
            act = (parent["title"] if parent and parent["kind"] == "act" else "").strip()
            k = norm_key(act, r["title"])
            e = by.setdefault(k, {"act": canon_act(act), "label": canon_label(r["title"]), "body": "", "note": "", "url": "",
                                  "uses": 0, "source": "mine"})
            e["uses"] += 1
            if (r["body"] or "").strip() and len(r["body"]) >= len(e["body"]):
                e["body"], e["url"] = r["body"], r["url"] or e["url"]
            if (r["note"] or "").strip() and not e["note"]:
                e["note"] = r["note"]
    for key, label, about in STARTER:
        act = ACT_BY_KEY[key][1]
        e = by.get(norm_key(act, label))
        if e is None:
            by[norm_key(act, label)] = {"act": act, "label": label, "about": about, "body": "", "note": "",
                                "url": url_for(act, label), "uses": 0, "source": "starter"}
        else:
            e.setdefault("about", about)
    return sorted(by.values(), key=lambda e: (-e["uses"], e["act"], _art_sort(e["label"])))


def _art_sort(label):
    m = re.search(r"ст\.\s*(\d+)(?:\.(\d+))?", label or "")
    return (int(m.group(1)), int(m.group(2) or 0)) if m else (10 ** 6, 0)


_ACT_FULL = [(re.compile(rf"^\s*(?:{p})\s*\.?\s*$", re.I), ACT_BY_KEY[k][1]) for k, p in _ACT_ALTS]


def canon_act(title):
    """«Гражданский кодекс Российской Федерации», «ГК», «ГК РФ» → «Гражданский кодекс РФ»; прочее — как есть."""
    t = re.sub(r"\s+", " ", (title or "").strip())
    for rx, name in _ACT_FULL:
        if rx.match(t):
            return name
    return t


def canon_label(label):
    """«п.1  ст.395» → «п. 1 ст. 395» — чтобы одну статью, записанную по-разному, считать одной."""
    t = re.sub(r"\s+", " ", (label or "").strip())
    return re.sub(r"(?<=[а-яё])\.\s*(?=[\dа-яё])", ". ", t, flags=re.I)


def norm_key(act, label):
    return canon_act(act).lower(), canon_label(label).lower()


def short_act(act):
    for key, title, _f, abbr in ACTS:
        if title == act:
            return abbr[0]
    return act
