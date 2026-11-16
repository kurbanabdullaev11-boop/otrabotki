import json
import os
import re
import urllib.parse
import urllib.request

from playwright.sync_api import sync_playwright

URL = "https://portfolio.ncsa.ru/?tab=dashboard"
LOGIN = os.environ["PORTFOLIO_LOGIN"]
PASSWORD = os.environ["PORTFOLIO_PASSWORD"]
TG_TOKEN = os.environ["TG_TOKEN"]
TG_CHAT = os.environ["TG_CHAT_ID"]
STATE_FILE = "state.json"
TABS = ["Главная", "Задания", "Работы", "Моё портфолио"]

# Ищем самые мелкие блоки, где есть и "Записано X из Y", и дата
JS = """
() => {
  const has = t => /Записано\\s*\\d+\\s*из\\s*\\d+/.test(t) && /\\d{2}\\.\\d{2}\\.\\d{4}/.test(t);
  const out = [];
  for (const el of document.querySelectorAll('div, section, article, li')) {
    if (!has(el.innerText || '')) continue;
    let inner = false;
    for (const c of el.children) {
      if (has(c.innerText || '')) { inner = true; break; }
    }
    if (!inner) out.push(el.innerText);
  }
  return out;
}
"""


def tg(text):
    data = urllib.parse.urlencode({"chat_id": TG_CHAT, "text": text}).encode()
    urllib.request.urlopen(
        f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage", data, timeout=30
    )


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
    }


def main():
    cards = {}
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.goto(URL, wait_until="networkidle")
        page.locator("input[type=password]").first.fill(PASSWORD)
        page.locator(
            "input:not([type=password]):not([type=hidden]):not([type=checkbox])"
        ).first.fill(LOGIN)
        page.get_by_role("button", name="Войти").first.click()
        page.wait_for_timeout(4000)

        debug = []
        for tab in TABS:
            try:
                page.get_by_text(tab, exact=True).first.click(timeout=5000)
                page.wait_for_timeout(3000)
            except Exception:
                debug.append(f"[нет вкладки {tab}]")
                continue
            debug.append(f"=== {tab} ===\n" + page.inner_text("body")[:3000])
            for t in page.evaluate(JS):
                try:
                    c = parse(t)
                    cards[c["key"]] = c
                except Exception as e:
                    debug.append(f"[ошибка разбора: {e}]")
        browser.close()

    with open("debug.txt", "w", encoding="utf-8") as f:
        f.write("\n\n".join(debug))

    if not cards:
        print("Карточки не найдены, состояние не меняю")
        return

    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            old = json.load(f)
    except Exception:
        old = {}

    for key, c in cards.items():
        if c["free"] > 0 and old.get(key, 0) == 0:
            tg(
                f"🔔 Есть место!\n{c['name']}\n{c['date']}, {c['time']}\n"
                f"ауд. {c['room']}\nСвободно: {c['free']} из {c['total']}\n{URL}"
            )

    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump({k: c["free"] for k, c in cards.items()}, f, ensure_ascii=False, indent=1)
    print(f"Найдено карточек: {len(cards)}")


if __name__ == "__main__":
    main()
