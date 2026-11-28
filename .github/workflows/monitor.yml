import json
import os
import re
import time
import urllib.parse
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

from playwright.sync_api import sync_playwright

URL = "https://portfolio.ncsa.ru/?tab=dashboard"
LOGIN = os.environ["PORTFOLIO_LOGIN"]
PASSWORD = os.environ["PORTFOLIO_PASSWORD"]
TG_TOKEN = os.environ["TG_TOKEN"]
TG_CHAT = os.environ["TG_CHAT_ID"]
STATE_FILE = "state.json"
RULES_FILE = "rules.json"

MSK = ZoneInfo("Europe/Moscow")
# check = обычная проверка (monitor), rush = утренний рывок (sprint)
MODE = os.environ.get("MODE", "check")
# Окно рывка по московскому времени
LOGIN_AT = (7, 57, 0)      # во столько бот входит в портфолио
RUSH_AT = (7, 59, 59)      # во столько первый раз жмёт «Отработки»
RUSH_END = (8, 4, 0)       # до сюда крутит цикл
WINDOW_START = (7, 30, 0)  # с этого времени работает только рывок (sprint)
RETRY_PAUSE_MS = 400       # пауза между заходами меню -> «Отработки»
MAX_ATTEMPTS = 3           # попыток записи на одну карточку

JS = """
() => {
  const has = t => /Записано\\s*\\d+\\s*из\\s*\\d+/.test(t) && /\\d{2}\\.\\d{2}\\.\\d{4}/.test(t);
  const out = [];
  let i = 0;
  for (const el of document.querySelectorAll('div, section, article, li')) {
    if (!has(el.innerText || '')) continue;
    let inner = false;
    for (const c of el.children) {
      if (has(c.innerText || '')) { inner = true; break; }
    }
    if (!inner) {
      el.setAttribute('data-cardidx', String(i));
      out.push([i, el.innerText]);
      i++;
    }
  }
  return out;
}
"""


# ---------- время ----------

def now():
    return datetime.now(MSK)


def at(hms):
    h, m, s = hms
    return now().replace(hour=h, minute=m, second=s, microsecond=0)


def wait_until(t):
    while True:
        d = (t - now()).total_seconds()
        if d <= 0:
            return
        time.sleep(min(d - 1, 30) if d > 2 else 0.005)


# ---------- telegram / файлы ----------

def tg_api(method, **params):
    data = urllib.parse.urlencode(params).encode()
    with urllib.request.urlopen(
        f"https://api.telegram.org/bot{TG_TOKEN}/{method}", data, timeout=40
    ) as r:
        return json.loads(r.read().decode())


def tg(text, buttons=None):
    params = {"chat_id": TG_CHAT, "text": text}
    if buttons:
        params["reply_markup"] = json.dumps({"inline_keyboard": [buttons]})
    tg_api("sendMessage", **params)


def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


# ---------- разбор карточек ----------

def parse(text):
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    name = lines[0]
    date = re.search(r"\d{2}\.\d{2}\.\d{4}", text).group()
    tm = re.search(r"\d{1,2}:\d{2}\s*[–-]\s*\d{1,2}:\d{2}", text)
    tm = tm.group() if tm else ""
    room = lines[lines.index("Аудитория") + 1] if "Аудитория" in lines else ""
    m = re.search(r"Записано\s*(\d+)\s*из\s*(\d+)", text)
    booked, total = int(m.group(1)), int(m.group(2))
    free = total - booked
    m2 = re.search(r"ещ[её]\s*(\d+)\s*мест", text, re.I)
    if m2:
        free = int(m2.group(1))
    elif "Мест нет" in text:
        free = 0
    return {
        "key": f"{name}|{date}|{tm}",
        "name": name,
        "date": date,
        "time": tm,
        "room": room,
        "free": max(free, 0),
        "total": total,
        "text": text,
    }


def collect(page):
    cards = {}
    for idx, t in page.evaluate(JS):
        try:
            c = parse(t)
            c["idx"] = idx
            cards[c["key"]] = c
        except Exception as e:
            print("  ошибка разбора:", e)
    return cards


def match_rule(c, rules):
    for r in rules:
        if r.get("date", "*") not in ("*", c["date"]):
            continue
        if r.get("discipline") and r["discipline"].lower() not in c["text"].lower():
            continue
        if r.get("teacher") and r["teacher"].lower() not in c["name"].lower():
            continue
        return r
    return None


def date_key(label):
    m = re.findall(r"(\d{2})\.(\d{2})\.(\d{4})", label)
    if not m:
        return None
    dd, mm, yy = m[-1]
    return (int(yy), int(mm), int(dd))


def pick_option(options, how):
    real = [(i, l) for i, l in options if l.strip() and "Выберите" not in l]
    if not real:
        return None
    how = (how or "oldest").strip()
    if how.lower() in ("oldest", "newest"):
        dated = [(date_key(l), i, l) for i, l in real if date_key(l)]
        if dated:
            dated.sort(reverse=(how.lower() == "newest"))
            return dated[0][1], dated[0][2]
        return real[0]
    for i, l in real:
        if how.lower() in l.lower():
            return i, l
    return None


# ---------- вход, меню, всплывающие окна ----------

def login(page):
    page.goto(URL, wait_until="networkidle")
    page.locator("input[type=password]").first.fill(PASSWORD)
    page.locator(
        "input:not([type=password]):not([type=hidden]):not([type=checkbox])"
    ).first.fill(LOGIN)
    page.get_by_role("button", name="Войти").first.click()
    page.wait_for_timeout(5000)


def dismiss(page):
    """Убирает любое всплывающее окно, если оно мешает."""
    try:
        page.keyboard.press("Escape")
        b = page.get_by_role(
            "button", name=re.compile(r"^(Закрыть|Понятно|Ок|OK|Хорошо|Да)$", re.I)
        )
        if b.count():
            b.first.click(timeout=500)
    except Exception:
        pass


def open_otrabotki(page):
    """Выход в главное меню и заход в «Отработки» (так сайт обновляет данные)."""
    try:
        page.goto(URL, wait_until="domcontentloaded", timeout=4000)
    except Exception:
        pass  # сайт тормозит, пробуем жать кнопку на том, что успело загрузиться
    dismiss(page)
    page.get_by_text("Отработки", exact=True).first.click(timeout=3000)


def wait_cards(page, limit=2.5):
    end = time.time() + limit
    while time.time() < end:
        try:
            cards = collect(page)
            if cards:
                return cards
        except Exception:
            pass
        page.wait_for_timeout(150)
    return {}


# ---------- запись ----------

def try_register(page, c, rule, live):
    card = page.locator(f'[data-cardidx="{c["idx"]}"]')
    sel = card.locator("select").first
    opts = sel.evaluate(
        "s => [...s.options].map((o, i) => [i, o.text.trim()])", timeout=3000
    )
    choice = pick_option(opts, rule.get("debt"))
    if not choice:
        return False, "⚠️ Не нашёл подходящую задолженность, запишись сам."
    idx, label = choice
    if not live:
        return False, f"🧪 Пробный режим: записал бы на задолженность «{label}»."
    before = page.get_by_text("Отменить запись").count()
    sel.select_option(index=idx, timeout=3000)
    page.wait_for_timeout(100)
    dismiss(page)
    card.get_by_role("button", name=re.compile("Записаться", re.I)).first.click(
        timeout=3000
    )
    end = time.time() + 4
    while time.time() < end:
        if page.get_by_text("Отменить запись").count() > before:
            return True, f"✅ Записал тебя на «{label}»."
        page.wait_for_timeout(150)
    return False, "⚠️ Нажал «Записаться», но подтверждения не вижу. Проверь на сайте."


def rush(page, rules, live, armed):
    """В 7:59:59 жмёт меню -> «Отработки» по кругу, пока не запишется."""
    wait_until(at(RUSH_AT))
    deadline = at(RUSH_END)
    attempts = {}
    loops = 0
    while now() < deadline:
        loops += 1
        try:
            open_otrabotki(page)
            cards = wait_cards(page)
        except Exception as e:
            print(f"  заход {loops}: {type(e).__name__}")
            page.wait_for_timeout(RETRY_PAUSE_MS)
            continue
        for key, c in cards.items():
            if c["free"] <= 0 or "Отменить запись" in c["text"]:
                continue
            is_armed = key in armed
            rule = {} if is_armed else match_rule(c, rules)
            if rule is None or attempts.get(key, 0) >= MAX_ATTEMPTS:
                continue
            attempts[key] = attempts.get(key, 0) + 1
            real = live or is_armed
            try:
                done, note = try_register(page, c, rule, real)
            except Exception as e:
                done, note = False, (
                    f"⚠️ Автозапись не удалась ({type(e).__name__}). Запишись сам."
                )
            tg(
                f"{c['name']}\n{c['date']}, {c['time']}\nауд. {c['room']}\n\n{note}"
            )
            if done and is_armed:
                armed.remove(key)
            if done and not armed:
                print(f"Рывок завершён, заходов: {loops}")
                return
            if not real:
                print(f"Рывок (пробный) завершён, заходов: {loops}")
                return
        page.wait_for_timeout(RETRY_PAUSE_MS)
    print(f"Рывок закончился по времени, заходов: {loops}")


# ---------- кнопка «Записаться» в Telegram (очередь) ----------

def process_taps(meta):
    """Читает нажатия кнопок (Telegram хранит их до суток) и ставит отработки в очередь."""
    try:
        updates = tg_api(
            "getUpdates", timeout=0, allowed_updates=json.dumps(["callback_query"])
        ).get("result", [])
    except Exception:
        return
    last = None
    for u in updates:
        last = u["update_id"]
        cq = u.get("callback_query") or {}
        data = cq.get("data", "")
        if not data.startswith("reg:"):
            continue
        if str(cq.get("from", {}).get("id")) != str(TG_CHAT):
            continue
        key = meta["buttons"].get(data[4:])
        try:
            tg_api(
                "answerCallbackQuery",
                callback_query_id=cq["id"],
                text="В очереди" if key else "Кнопка устарела",
            )
        except Exception:
            pass
        if not key or key in meta["armed"]:
            continue
        meta["armed"].append(key)
        name, date, tm = (key.split("|") + ["", ""])[:3]
        tg(
            f"📌 В очереди: {name}\n{date}, {tm}\n"
            "Запишу, как только откроется запись (в 7:59:59)."
        )
    if last is not None:
        try:
            tg_api("getUpdates", offset=last + 1, timeout=0)
        except Exception:
            pass


def wait_with_taps(t, meta):
    """Ждёт до времени t и всё это время принимает нажатия кнопок."""
    while now() < t:
        process_taps(meta)
        d = (t - now()).total_seconds()
        if d > 0:
            time.sleep(min(d, 15))


# ---------- основной запуск ----------

def main():
    cfg = load_json(RULES_FILE, {})
    rules = cfg.get("rules", [])
    live = True  # пробный режим убран: бот всегда записывает по-настоящему
    old = load_json(STATE_FILE, {})
    tried = old.get("__tried__", [])
    suffix = "|live"
    meta = {
        "buttons": old.get("__buttons__", {}),
        "armed": old.get("__armed__", []),
    }
    armed = meta["armed"]

    t0 = now()
    in_window = False
    if MODE == "rush":
        if not (at(WINDOW_START) <= t0 < at(RUSH_END)):
            print("Рывок: сейчас не время, выхожу")
            return
        in_window = True
    elif at(WINDOW_START) <= t0 < at(RUSH_END):
        print("Окно рывка: обычную проверку пропускаю")
        return

    process_taps(meta)
    if in_window and now() < at(LOGIN_AT):
        wait_with_taps(at(LOGIN_AT), meta)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        login(page)
        process_taps(meta)

        if MODE == "rush" and (rules or armed):
            rush(page, rules, live, armed)
        else:
            try:
                page.get_by_text("Отработки", exact=True).first.click(timeout=5000)
                page.wait_for_timeout(3000)
            except Exception:
                print("Вкладка «Отработки» не нажалась")

        cards = collect(page)
        print(f"Найдено карточек: {len(cards)}")
        if not cards:
            print("Карточки не найдены, состояние не меняю")
            browser.close()
            return

        stamp = str(int(time.time()) % 100000)
        n = 0
        for key, c in list(cards.items()):
            if c["free"] <= 0:
                continue
            transition = old.get(key, 0) == 0
            armed_now = key in armed and now() >= at(RUSH_AT)
            rule = {} if armed_now else match_rule(c, rules)
            tkey = key + ("|armed" if armed_now else suffix)
            note, done = "", False
            if (
                rule is not None
                and tkey not in tried
                and "Отменить запись" not in c["text"]
            ):
                tried.append(tkey)
                try:
                    fresh = collect(page).get(key, c)
                    done, note = try_register(page, fresh, rule, live or armed_now)
                except Exception as e:
                    note = (
                        f"⚠️ Автозапись не удалась ({type(e).__name__}). "
                        "Запишись сам."
                    )
                if done and key in armed:
                    armed.remove(key)
            if not (transition or note):
                continue
            msg = (
                f"🔔 Есть место!\n{c['name']}\n{c['date']}, {c['time']}\n"
                f"ауд. {c['room']}\nСвободно: {c['free']} из {c['total']}\n{URL}"
            )
            if note:
                msg += "\n\n" + note
            buttons = None
            if not done and "Отменить запись" not in c["text"] and key not in armed:
                tid = f"{stamp}_{n}"
                n += 1
                meta["buttons"][tid] = key
                buttons = [{"text": "✅ Записаться", "callback_data": f"reg:{tid}"}]
            for i in range(1 if done else 5):
                tg(msg, buttons)
                time.sleep(5)
        browser.close()

    tried = [t for t in tried if t.rsplit("|", 1)[0] in cards]
    data = {k: c["free"] for k, c in cards.items()}
    data["__tried__"] = tried
    data["__armed__"] = [k for k in armed if k in cards]
    data["__buttons__"] = {
        t: k for t, k in meta["buttons"].items() if k in cards
    }
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
