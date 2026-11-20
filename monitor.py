import json
import os
import re
import time
import urllib.parse
import urllib.request

from playwright.sync_api import sync_playwright

URL = "https://portfolio.ncsa.ru/?tab=dashboard"
LOGIN = os.environ["PORTFOLIO_LOGIN"]
PASSWORD = os.environ["PORTFOLIO_PASSWORD"]
TG_TOKEN = os.environ["TG_TOKEN"]
TG_CHAT = os.environ["TG_CHAT_ID"]
STATE_FILE = "state.json"
RULES_FILE = "rules.json"

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


def tg(text):
    data = urllib.parse.urlencode({"chat_id": TG_CHAT, "text": text}).encode()
    urllib.request.urlopen(
        f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage", data, timeout=30
    )


def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


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


def try_register(page, c, rule, live):
    card = page.locator(f'[data-cardidx="{c["idx"]}"]')
    sel = card.locator("select").first
    opts = sel.evaluate(
        "s => [...s.options].map((o, i) => [i, o.text.trim()])", timeout=5000
    )
    choice = pick_option(opts, rule.get("debt"))
    if not choice:
        return False, "⚠️ Не нашёл подходящую задолженность, запишись сам."
    idx, label = choice
    if not live:
        return False, f"🧪 Пробный режим: записал бы на задолженность «{label}»."
    before = page.get_by_text("Отменить запись").count()
    sel.select_option(index=idx, timeout=5000)
    page.wait_for_timeout(500)
    card.get_by_role("button", name=re.compile("Записаться", re.I)).first.click(
        timeout=5000
    )
    page.wait_for_timeout(3000)
    after = page.get_by_text("Отменить запись").count()
    if after > before:
        return True, f"✅ Записал тебя на «{label}»."
    return False, "⚠️ Нажал «Записаться», но подтверждения не вижу. Проверь на сайте."


def main():
    cfg = load_json(RULES_FILE, {})
    rules = cfg.get("rules", [])
    live = cfg.get("mode", "dry") == "live"
    old = load_json(STATE_FILE, {})
    tried = old.get("__tried__", [])
    suffix = "|live" if live else "|dry"

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.goto(URL, wait_until="networkidle")
        page.locator("input[type=password]").first.fill(PASSWORD)
        page.locator(
            "input:not([type=password]):not([type=hidden]):not([type=checkbox])"
        ).first.fill(LOGIN)
        page.get_by_role("button", name="Войти").first.click()
        page.wait_for_timeout(5000)
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

        for key, c in list(cards.items()):
            if c["free"] <= 0:
                continue
            transition = old.get(key, 0) == 0
            rule = match_rule(c, rules)
            note, done = "", False
            if (
                rule
                and (key + suffix) not in tried
                and "Отменить запись" not in c["text"]
            ):
                tried.append(key + suffix)
                try:
                    fresh = collect(page).get(key, c)
                    done, note = try_register(page, fresh, rule, live)
                except Exception as e:
                    note = (
                        f"⚠️ Автозапись не удалась ({type(e).__name__}). "
                        "Запишись сам."
                    )
            if not (transition or note):
                continue
            msg = (
                f"🔔 Есть место!\n{c['name']}\n{c['date']}, {c['time']}\n"
                f"ауд. {c['room']}\nСвободно: {c['free']} из {c['total']}\n{URL}"
            )
            if note:
                msg += "\n\n" + note
            for i in range(1 if done else 5):
                tg(msg)
                time.sleep(5)
        browser.close()

    tried = [t for t in tried if t.rsplit("|", 1)[0] in cards]
    data = {k: c["free"] for k, c in cards.items()}
    data["__tried__"] = tried
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
