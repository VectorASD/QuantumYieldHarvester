from playwright.async_api import async_playwright
import psutil

from pathlib import Path
import asyncio
import fnmatch
from inspect import iscoroutinefunction
from pprint import pprint
from typing import Callable

if __name__ == "__main__":
    import sys
    sys.path = [str(Path(__file__).parent.parent), *sys.path]
from secrets import Storage


def find_yandex_browser_path():
    for proc in psutil.process_iter(['pid', 'name', 'exe']):
        try:
            if proc.info['name'] and "browser" in proc.info['name'].lower():
                exe_path = proc.info['exe']
                if exe_path and "yandex" in exe_path.lower():
                    return exe_path
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return None

# C:\Program Files (x86)\Yandex\YandexBrowser\Application\browser.exe
browser_path = find_yandex_browser_path()


storage = Storage("token.asd")
COOKIE_LOG = False

INIT_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', {
    get: () => false
});

Object.defineProperty(screen, 'availTop', { get: () => 0 });
Object.defineProperty(screen, 'availLeft', { get: () => 0 });

Object.defineProperty(screen, 'width', { get: () => 1920 });
Object.defineProperty(screen, 'availWidth', { get: () => 1920 });

Object.defineProperty(screen, 'height', { get: () => 1080 });
Object.defineProperty(screen, 'availHeight', { get: () => 1080-50 });
"""

async def run_v2(url: str, e_path: str|Path, e_name: str, cb_factory: Callable|None = None):
    # --- cookie handling ---

    if COOKIE_LOG:
        file = open("log.txt", "w", encoding="utf-8")
        def log(*a, **b):
            print(*a, **b)
            print(*a, **b, file=file, flush=True)

    def cookie_key(cookie):
        # Take only stable fields (ignore "expires")
        return (
            cookie["domain"],
            cookie["path"],
            cookie["name"],
            cookie["value"],
            cookie.get("httpOnly", False),
            cookie.get("secure", False),
            cookie.get("sameSite", "None"),
        )

    prev_cookies = []
    prev = set()
    async def check_cookies(ctx):
        nonlocal prev_cookies, prev

        cookies = await ctx.cookies()
        if cookies == prev_cookies: return

        prev_cookies = cookies
        storage.store(cookies, None, e_path, e_name)

        if COOKIE_LOG:
            log("Cookies changed!")
            prev_upd = set()
            for cookie in cookies:
                key = cookie_key(cookie)
                if key in prev: prev.discard(key)
                else: log("+", key)
                prev_upd.add(key)
            for cookie in prev:
                log("-", cookie)
            prev = prev_upd

    async def monitor_cookies(ctx, interval=5):
        nonlocal prev

        prev = set(cookie_key(cookie) for cookie in prev_cookies)
        while True:
            await check_cookies(ctx)
            await asyncio.sleep(interval)

    cookies = storage.load(e_path, e_name)
    if cookies is None:
        cookies = []
    if False:
        pprint(sorted((cookie["name"], cookie["domain"]) for cookie in cookies))
        exit()

    # --- dispatch handling ---

    request_cbs = []
    response_cbs = []

    def add_cb(event_type: str, pattern: str, cb):
        if event_type == "request":
            cbs = request_cbs
        elif event_type == "response":
            cbs = response_cbs
        else:
            raise ValueError(f"Unknown event type: {event_type}")
        cbs.append((pattern, cb, iscoroutinefunction(cb)))

    def dispatch(cbs: list[tuple[str, Callable, bool]], event, page):
        for pattern, cb, iscoroutine in cbs:
            if fnmatch.fnmatch(event.url, pattern):
                if iscoroutine:
                    asyncio.create_task(cb(event, page))
                else:
                    cb(event, page)

    if cb_factory:
        cb_factory(add_cb)

    # --- page event handlers ---

    def on_close(page):
        if not ctx.pages and not stop_future.done():
            stop_future.set_result(True)

    def on_page(page):
        # print("New page:", page.url)
        page.on("close", on_close)
        page.on("request",  lambda req:  dispatch(request_cbs,  req,  page))
        page.on("response", lambda resp: dispatch(response_cbs, resp, page))

    def on_browser_disconnected():
        if not stop_future.done():
            stop_future.set_result(True)

    # --- main async browser loop ---

    stop_future = asyncio.Future()

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless        = False,
            executable_path = browser_path,
            args=["--window-position=0,0", "--window-size=1920,1080"],
        )
        browser.on("disconnected", lambda: stop_future.set_result(True))

        ctx = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            screen={"width": 1920, "height": 1080},
            locale="ru",
        )
        ctx.on("page", on_page)
        await ctx.add_init_script(INIT_SCRIPT)

        if cookies:
            await ctx.add_cookies(cookies)
            prev_cookies = cookies
        monitor_task = asyncio.create_task(monitor_cookies(ctx))

        page = await ctx.new_page()  # this adds the first context to browser.contexts
        # ctx = browser.contexts[0]  # equivalent to browser.new_context()

        # print(ctx.pages)  # [<Page url='about:blank'>]
        asyncio.create_task(page.goto(url))
        # print(ctx.pages)  # [<Page url='https://mail.ru/'>]  (when using await for page.goto)

        await stop_future

        monitor_task.cancel()
        try:
            await monitor_task
        except asyncio.CancelledError:
            pass

        await check_cookies(ctx)

    if COOKIE_LOG:
        file.close()


if __name__ == "__main__":
    def cb_factory(add_cb: Callable):
        pass
      # add_cb("request", "https://e.mail.ru/api/v*/*", lambda req: print("REQ:", req.url))
      # add_cb("response", "*vk.*/*", lambda resp: print("RESP:", resp.url, resp.status))
    asyncio.run(run_v2("http://127.0.0.1:8000/", Path("bases") / "cookies.asd", "cookies", cb_factory))
