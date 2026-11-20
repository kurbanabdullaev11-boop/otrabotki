import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from playwright.sync_api import sync_playwright

import monitor as m

MSK = ZoneInfo("Europe/Moscow")


def login(page):
    page.goto(m.URL, wait_until="networkidle")
    page.locator("input[type=password]").first.fill(m.PASSWORD)
    page.locator(
        "input:not([type=password]):not([type=hidden]):not([type=checkbox])"
    ).first.fill(m.LOGIN)
    page.get_by_role("button", name="Войти").first.click()
    page.wait_for_timeout(4000)


def open_tab(page):
    page.get_by_text("Отработки", exact=True).first.click(timeout=5000)
    page.wait_for_timeout(1500)


def head(c):
    return (
        f"🔔 Есть место!\n{c['name']}\n{c['date']}, {c['time']}\n"
        f"ауд. {c['room']}\nСвободно: {c['free']} из {c['total']}\n{m.URL}"
    )


def main():
    cfg = m.load_json(m.RULES_FILE, {})
    rules = cfg.get("rules", [])
    live = cfg.get("mode", "dry") == "live"
    sp = cfg.get("sprint", {})
    at = sp.get("at", "08:00")
    hh, mm = map(int, at.split(":"))
    stop_min = int(sp.get("stop_after_min", 10))
    if not rules:
        print("Нет правил, рывок не нужен")
        return

    now = datetime.now(MSK)
    start = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    end = start + timedelta(minutes=stop_min)
    if now > end:
        print("Окно рывка уже прошло")
        return

    while datetime.now(MSK) < start - timedelta(seconds=60):
        time.sleep(1)

    done = set()
    checks = 0
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        login(page)
        open_tab(page)
        while datetime.now(MSK) < start - timedelta(seconds=1):
            time.sleep(0.3)

        while datetime.now(MSK) < end:
            try:
                if page.locator("input[type=password]:visible").count():
                    login(page)
                page.get_by_text("Главная", exact=True).first.click(timeout=5000)
                page.wait_for_timeout(500)
                open_tab(page)
                checks += 1
                cards = m.collect(page)
                for key, c in cards.items():
                    if c["free"] <= 0 or key in done:
                        continue
                    if "Отменить запись" in c["text"]:
                        continue
                    rule = m.match_rule(c, rules)
                    if not rule:
                        continue
                    done.add(key)
                    try:
                        ok, note = m.try_register(page, c, rule, live)
                    except Exception as e:
                        ok = False
                        note = (
                            f"⚠️ Автозапись не удалась ({type(e).__name__}). "
                            "Запишись сам!"
                        )
                    loud = live and not ok
                    for i in range(3 if loud else 1):
                        m.tg(head(c) + "\n\n" + note)
                        if loud:
                            time.sleep(3)
                    break
            except Exception as e:
                print("Ошибка проверки:", type(e).__name__, e)
                time.sleep(2)
        browser.close()

    m.tg(f"Рывок {at} завершён: проверок {checks}, подходящих мест {len(done)}.")


if __name__ == "__main__":
    main()
