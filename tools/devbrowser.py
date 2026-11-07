"""Library behind `tools/dev_run.py`: start the app, open a real browser, drive it like a user.

What it gives a scenario (see tools/scenarios/):
  * the app running on a free port with throwaway data (never your real data/ folder),
  * a browser window (visible by default) with a throwaway profile,
  * REAL input through the DevTools protocol: mouse moves along an eased path, clicks, double
    clicks, drags, wheel, keys and typing arrive in the page as trusted user events,
  * an on-page cursor dot, click ripples and a narration banner, so a person can follow along,
  * screenshots, console/JS error capture, PASS/FAIL checks.

It cannot move the operating system's own mouse pointer; the on-page dot shows where the
browser's pointer is. Everything stays on 127.0.0.1 and every process it starts is stopped on exit.
"""

import asyncio
import base64
import colorsys
import copy
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

import websockets
import yaml
from PIL import Image

REPO = Path(__file__).resolve().parent.parent
RUNS_DIR = REPO / "data" / "dev_runs"  # gitignored; screenshots of each run are kept here
KEEP_RUNS = 8
BROWSER_CANDIDATES = [
    os.environ.get("STUDIO_BROWSER", ""),
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
]
MOD = {"alt": 1, "ctrl": 2, "meta": 4, "shift": 8}
SPECIAL_KEYS = {  # name -> (key, code, windowsVirtualKeyCode, text)
    "tab": ("Tab", "Tab", 9, None),
    "enter": ("Enter", "Enter", 13, "\r"),
    "escape": ("Escape", "Escape", 27, None),
    "esc": ("Escape", "Escape", 27, None),
    "space": (" ", "Space", 32, " "),
    "backspace": ("Backspace", "Backspace", 8, None),
    "delete": ("Delete", "Delete", 46, None),
    "home": ("Home", "Home", 36, None),
    "end": ("End", "End", 35, None),
    "left": ("ArrowLeft", "ArrowLeft", 37, None),
    "up": ("ArrowUp", "ArrowUp", 38, None),
    "right": ("ArrowRight", "ArrowRight", 39, None),
    "down": ("ArrowDown", "ArrowDown", 40, None),
}

OVERLAY_JS = r"""
(() => {
  if (window.__devOverlay) return;
  window.__devOverlay = true;
  function init() {
    const style = document.createElement('style');
    style.textContent = `
      #__dev_cursor{position:fixed;left:0;top:0;width:24px;height:24px;z-index:2147483647;pointer-events:none}
      #__dev_cursor svg{filter:drop-shadow(0 1px 2px rgba(0,0,0,.6))}
      .__dev_ripple{position:fixed;width:14px;height:14px;border-radius:50%;border:3px solid #ff3b30;
        margin:-7px 0 0 -7px;z-index:2147483646;pointer-events:none;animation:__dev_r .55s ease-out forwards}
      @keyframes __dev_r{to{transform:scale(4.5);opacity:0}}
      #__dev_banner{position:fixed;left:50%;top:8px;transform:translateX(-50%);z-index:2147483647;
        background:rgba(20,20,20,.9);color:#fff;font:600 14px system-ui,sans-serif;padding:6px 16px;
        border-radius:999px;pointer-events:none;max-width:80vw;white-space:nowrap;overflow:hidden;
        text-overflow:ellipsis;display:none}`;
    document.head.append(style);
    const cursor = document.createElement('div');
    cursor.id = '__dev_cursor';
    cursor.innerHTML = '<svg width="24" height="24" viewBox="0 0 24 24"><path d="M3 2l7 19 3-8 8-3z" fill="#ff3b30" stroke="#fff" stroke-width="1.5" stroke-linejoin="round"/></svg>';
    const banner = document.createElement('div');
    banner.id = '__dev_banner';
    document.body.append(cursor, banner);
    const place = (x, y) => { cursor.style.transform = `translate(${x}px, ${y}px)`; };
    window.__devMove = place;
    window.__devSay = (text) => { banner.textContent = text; banner.style.display = text ? 'block' : 'none'; };
    document.addEventListener('mousemove', (e) => place(e.clientX, e.clientY), true);
    document.addEventListener('mousedown', (e) => {
      const r = document.createElement('div');
      r.className = '__dev_ripple';
      r.style.left = e.clientX + 'px'; r.style.top = e.clientY + 'px';
      document.body.append(r);
      setTimeout(() => r.remove(), 600);
    }, true);
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
})();
"""


class DevRunError(Exception):
    """Raised for setup problems and for steps that cannot be performed like a user would."""


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def find_browser(explicit: str | None = None) -> str:
    for candidate in [explicit or "", *BROWSER_CANDIDATES]:
        if candidate and Path(candidate).exists():
            return candidate
    raise DevRunError("No Edge/Chrome found. Pass --browser PATH or set STUDIO_BROWSER.")


def deep_merge(base: dict, extra: dict) -> dict:
    for key, value in extra.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            deep_merge(base[key], value)
        else:
            base[key] = value
    return base


def make_images(folder: Path, count: int, prefix: str, size: tuple[int, int] = (800, 600)) -> Path:
    """Write ``count`` distinct JPEGs (distinct content, so none are duplicates)."""
    folder.mkdir(parents=True, exist_ok=True)
    for i in range(count):
        hue = (i % 70) / 70
        r, g, b = (int(255 * c) for c in colorsys.hsv_to_rgb(hue, 0.5, 0.9))
        Image.new("RGB", size, (r, g, (b + i) % 256)).save(
            folder / f"{prefix}_{i:03d}.jpg", quality=90
        )
    return folder


class Api:
    """Plain HTTP calls to the app (for setup and for asserting what was really stored)."""

    def __init__(self, base: str) -> None:
        self.base = base

    def call(self, method: str, path: str, body=None):
        data = None if body is None else json.dumps(body).encode()
        request = urllib.request.Request(
            self.base + path, data=data, method=method, headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(request) as response:
                raw = response.read()
                return response.status, (json.loads(raw) if raw else None)
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read() or b"null")

    def wait_job(self, job_id: str, seconds: float = 120):
        deadline = time.time() + seconds
        while time.time() < deadline:
            _, job = self.call("GET", f"/api/jobs/{job_id}")
            if job["state"] in ("done", "failed"):
                return job
            time.sleep(0.1)
        raise DevRunError("job did not finish in time")

    def make_project(self, name: str, images: Path | None = None) -> dict:
        _, project = self.call("POST", "/api/projects", {"name": name})
        if images is not None:
            _, job = self.call("POST", f"/api/projects/{project['id']}/imports", {"path": str(images)})
            self.wait_job(job["job_id"])
        return project


def _kill_tree(process: subprocess.Popen) -> None:
    """Stop a process we started, including its children (browsers spawn several)."""
    if process.poll() is not None:
        return
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True)
    else:
        process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()


class Session:
    """One run: app server + browser + input helpers. Use as ``async with Session(...) as s``."""

    def __init__(self, *, headed: bool = True, pace: float | None = None, browser: str | None = None,
                 config: dict | None = None, label: str = "run", window=(1400, 900)) -> None:
        self.headed = headed
        self.pace = pace if pace is not None else (1.0 if headed else 0.0)
        self.browser_path = find_browser(browser)
        self.config_overrides = config or {}
        self.label = label
        self.window = window
        self.results: list[tuple[str, bool]] = []
        self.problems: list[str] = []
        self.expected_console: list[str] = []  # substrings of console errors a scenario causes on purpose
        self.cursor = (60.0, 60.0)
        self.work = Path(tempfile.mkdtemp(prefix="studio_dev_run_"))
        stamp = time.strftime("%Y%m%d-%H%M%S")
        self.shots = RUNS_DIR / f"{label}-{stamp}"
        self.shots.mkdir(parents=True, exist_ok=True)
        self._server: subprocess.Popen | None = None
        self._browser: subprocess.Popen | None = None
        self._ws = None
        self._counter = 0
        self.base = ""
        self.api: Api | None = None

    # ---- lifecycle ----------------------------------------------------------------------------
    async def __aenter__(self) -> "Session":
        try:
            self._start_server()
            await self._start_browser()
        except BaseException:
            await self.__aexit__(None, None, None)
            raise
        return self

    async def __aexit__(self, *exc) -> None:
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:
                pass
        for process in (self._browser, self._server):
            if process is not None:
                _kill_tree(process)
        shutil.rmtree(self.work, ignore_errors=True)
        self._prune_old_runs()

    def _prune_old_runs(self) -> None:
        runs = sorted((p for p in RUNS_DIR.glob("*") if p.is_dir()), key=lambda p: p.stat().st_mtime)
        for old in runs[:-KEEP_RUNS]:
            shutil.rmtree(old, ignore_errors=True)

    def _start_server(self) -> None:
        config = copy.deepcopy(yaml.safe_load((REPO / "config.yaml").read_text(encoding="utf-8")))
        port = free_port()
        config["app"].update({"data_dir": str(self.work / "data"), "port": port})
        deep_merge(config, self.config_overrides)
        config_path = self.work / "dev.yaml"
        config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
        self._server_log = self.work / "server.log"
        with self._server_log.open("wb") as log:  # kept so a start-up failure can be explained
            self._server = subprocess.Popen(
                [sys.executable, "-m", "studio", "--config", str(config_path)], cwd=REPO,
                stdout=log, stderr=log,
            )
        self.base = f"http://127.0.0.1:{port}"
        for _ in range(80):
            if self._server.poll() is not None:
                tail = self._server_log.read_text(errors="replace")[-800:]
                raise DevRunError(f"The app server exited during start-up:\n{tail}")
            try:
                urllib.request.urlopen(f"{self.base}/api/health", timeout=1)
                break
            except Exception:
                time.sleep(0.25)
        else:
            raise DevRunError("The app server did not become healthy.")
        self.api = Api(self.base)

    async def _start_browser(self) -> None:
        debug_port = free_port()
        args = [
            self.browser_path, f"--remote-debugging-port={debug_port}",
            f"--user-data-dir={self.work / 'browser-profile'}", "--no-first-run",
            "--no-default-browser-check", "--disable-extensions", "about:blank",
        ]
        if not self.headed:
            args.insert(1, "--headless=new")
            args.insert(2, "--disable-gpu")
        self._browser = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        version = None
        for _ in range(80):
            try:
                version = json.load(urllib.request.urlopen(
                    f"http://127.0.0.1:{debug_port}/json/version", timeout=1))
                break
            except Exception:
                await asyncio.sleep(0.25)
        if version is None:
            raise DevRunError("Could not connect to the browser's debugging port.")

        # Open our own dedicated window instead of reusing whatever tab the browser starts with:
        # Edge may replace its first tab, which would drop our connection to it.
        async with websockets.connect(version["webSocketDebuggerUrl"], max_size=None) as control:
            counter = 0

            async def browser_call(method: str, **params) -> dict:
                nonlocal counter
                counter += 1
                await control.send(json.dumps({"id": counter, "method": method, "params": params}))
                while True:
                    reply = json.loads(await control.recv())
                    if reply.get("id") == counter:
                        if "error" in reply:
                            raise DevRunError(f"{method}: {reply['error'].get('message')}")
                        return reply.get("result", {})

            target_id = (await browser_call("Target.createTarget", url="about:blank", newWindow=True))["targetId"]
            if self.headed:
                await self._resize_window(browser_call, target_id)
            for tab in json.load(urllib.request.urlopen(f"http://127.0.0.1:{debug_port}/json", timeout=2)):
                if tab["type"] == "page" and tab["id"] != target_id:
                    await browser_call("Target.closeTarget", targetId=tab["id"])

        page = None
        for _ in range(40):
            tabs = json.load(urllib.request.urlopen(f"http://127.0.0.1:{debug_port}/json", timeout=2))
            page = next((t for t in tabs if t["id"] == target_id), None)
            if page:
                break
            await asyncio.sleep(0.25)
        if page is None:
            raise DevRunError("The browser window we opened disappeared.")
        self._ws = await websockets.connect(page["webSocketDebuggerUrl"], max_size=None)
        await self.send("Page.enable")
        await self.send("Runtime.enable")
        await self.send("Log.enable")
        await self.send("Page.addScriptToEvaluateOnNewDocument", source=OVERLAY_JS)
        if not self.headed:  # headless has no real window: fix the viewport for repeatable layout
            await self.send("Emulation.setDeviceMetricsOverride", width=self.window[0],
                            height=self.window[1], deviceScaleFactor=1, mobile=False)
        else:
            await self.send("Page.bringToFront")
        size = await self.js("[window.innerWidth, window.innerHeight]")
        print(f"  Browser viewport: {size[0]}x{size[1]} px ({'visible window' if self.headed else 'headless'})")

    async def _resize_window(self, browser_call, target_id: str) -> None:
        """Place and size the visible window (the command-line size flag is ignored by new profiles)."""
        window_id = None
        error = ""
        for _ in range(30):  # the window may take a moment to exist
            try:
                window_id = (await browser_call("Browser.getWindowForTarget", targetId=target_id))["windowId"]
                break
            except DevRunError as caught:
                error = str(caught)
                await asyncio.sleep(0.3)
        if window_id is None:
            print(f"  WARNING: could not resize the browser window ({error}); using its default size.")
            return
        await browser_call("Browser.setWindowBounds", windowId=window_id, bounds={
            "left": 30, "top": 30, "width": self.window[0], "height": self.window[1],
            "windowState": "normal"})
        await asyncio.sleep(0.5)  # let the window settle before the first layout

    # ---- protocol -----------------------------------------------------------------------------
    async def send(self, method: str, **params):
        self._counter += 1
        mid = self._counter
        await self._ws.send(json.dumps({"id": mid, "method": method, "params": params}))
        while True:
            message = json.loads(await self._ws.recv())
            kind = message.get("method")
            if kind == "Runtime.exceptionThrown":
                details = message["params"]["exceptionDetails"]
                text = details.get("exception", {}).get("description", details.get("text", ""))
                self.problems.append("exception: " + str(text)[:300])
            elif kind == "Log.entryAdded" and message["params"]["entry"]["level"] == "error":
                entry = message["params"]["entry"]
                # 409 is part of the API contract (save conflict, "class is in use"); the browser
                # logs it as an error but the app handles it, so it is not a problem.
                expected = any(pattern in entry["text"] for pattern in self.expected_console)
                if "status of 409" not in entry["text"] and not expected:
                    self.problems.append("console: " + entry["text"] + " " + entry.get("url", ""))
            if message.get("id") == mid:
                if "error" in message:
                    raise DevRunError(f"{method} failed: {message['error']}")
                return message.get("result", {})

    async def js(self, expression: str):
        result = await self.send("Runtime.evaluate", expression=expression, awaitPromise=True,
                                 returnByValue=True)
        if "exceptionDetails" in result:
            self.problems.append("eval: " + expression[:70] + " -> " + str(result["exceptionDetails"])[:200])
            return None
        return result.get("result", {}).get("value")

    def expect_console(self, *patterns: str) -> None:
        """Declare console errors this scenario causes on purpose (for example a deliberate 400)."""
        self.expected_console.extend(patterns)

    # ---- narration, pacing, checks ------------------------------------------------------------
    async def pause(self, seconds: float) -> None:
        if self.pace > 0:
            await asyncio.sleep(seconds * self.pace)

    async def say(self, text: str) -> None:
        print(f"  > {text}")
        await self.js(f"window.__devSay && window.__devSay({json.dumps(text)})")
        await self.pause(0.6)

    def check(self, name: str, ok: bool, detail: str = "") -> bool:
        ok = bool(ok)
        self.results.append((name, ok))
        print(("  PASS " if ok else "  FAIL ") + name + (f"  [{detail}]" if detail and not ok else ""))
        return ok

    async def shot(self, name: str) -> Path:
        result = await self.send("Page.captureScreenshot", format="png")
        path = self.shots / f"{name}.png"
        path.write_bytes(base64.b64decode(result["data"]))
        return path

    # ---- navigation and waiting ---------------------------------------------------------------
    async def goto(self, path: str) -> None:
        await self.send("Page.navigate", url=self.base + path)
        await self.wait_for("document.readyState === 'complete'")
        await self.js(f"window.__devMove && window.__devMove({self.cursor[0]}, {self.cursor[1]})")

    async def wait_for(self, expression: str, seconds: float = 15) -> bool:
        for _ in range(int(seconds / 0.1)):
            if await self.js(f"!!({expression})"):
                return True
            await asyncio.sleep(0.1)
        self.problems.append("timeout waiting for: " + expression[:100])
        return False

    # ---- element lookup -----------------------------------------------------------------------
    @staticmethod
    def by_text(css: str, text: str, exact: bool = True) -> str:
        """Target expression: the first element matching ``css`` whose text equals/contains ``text``."""
        test = "e.textContent.trim() === t" if exact else "e.textContent.includes(t)"
        return f"js:[...document.querySelectorAll({json.dumps(css)})].find(e => {{ const t = {json.dumps(text)}; return {test}; }})"

    @staticmethod
    def _resolver(target: str) -> str:
        return target[3:] if target.startswith("js:") else f"document.querySelector({json.dumps(target)})"

    async def locate(self, target) -> tuple[float, float]:
        """Centre of a CSS selector, a ``js:`` expression, or an ``(x, y)`` pair, scrolled into view."""
        if isinstance(target, tuple):
            return float(target[0]), float(target[1])
        # Wait until the element stops moving (images loading, panels sliding in) before aiming,
        # as a person would; clicking a spot that is about to shift is a test bug, not an app bug.
        # The element is looked up again on every frame: the app may legitimately replace it while
        # we wait (for example, tiles are re-rendered after a split change).
        script = f"""(async () => {{
          const find = () => {self._resolver(target)};
          if (!find()) return null;
          find().scrollIntoView({{block: 'center', inline: 'center'}});
          const frame = () => new Promise(done => {{
            requestAnimationFrame(() => requestAnimationFrame(done));
            setTimeout(done, 120);
          }});
          let last = null;
          for (let i = 0; i < 30; i++) {{
            await frame();
            const current = find();
            if (!current) {{ last = null; continue; }}
            const b = current.getBoundingClientRect();
            const now = [b.left, b.top, b.width, b.height].map(v => Math.round(v * 2) / 2);
            if (last && now.every((v, j) => v === last[j])) break;
            last = now;
          }}
          const el = find();
          if (!el) return null;
          const r = el.getBoundingClientRect();
          const x = r.left + r.width / 2, y = r.top + r.height / 2;
          const top = document.elementFromPoint(x, y);
          return {{x, y, w: r.width, h: r.height,
                  hit: !!top && (el === top || el.contains(top) || top.contains(el)),
                  covered_by: top ? (top.id ? '#' + top.id : top.tagName.toLowerCase() + '.' + top.className) : 'nothing'}};
        }})()"""
        info = await self.js(script)
        if info is None:
            raise DevRunError(f"element not found: {target}")
        if info["w"] == 0 or info["h"] == 0:
            raise DevRunError(f"element has no size (hidden?): {target}")
        if not info["hit"]:
            raise DevRunError(f"element is covered, so a user could not click it: {target} "
                              f"(covered by {info['covered_by']})")
        return info["x"], info["y"]

    # ---- mouse --------------------------------------------------------------------------------
    async def _mouse(self, kind: str, x: float, y: float, button: str = "none", buttons: int = 0,
                     clicks: int = 0, modifiers: int = 0) -> None:
        await self.send("Input.dispatchMouseEvent", type=kind, x=x, y=y, button=button,
                        buttons=buttons, clickCount=clicks, modifiers=modifiers)

    async def move_to(self, target, buttons: int = 0, duration: float = 0.5) -> None:
        """Move the pointer along an eased path (instant when pace is 0)."""
        x1, y1 = await self.locate(target)
        x0, y0 = self.cursor
        steps = max(1, int(duration * self.pace * 45)) if self.pace > 0 else 1
        for i in range(1, steps + 1):
            t = i / steps
            eased = t * t * (3 - 2 * t)
            await self._mouse("mouseMoved", x0 + (x1 - x0) * eased, y0 + (y1 - y0) * eased,
                              button="left" if buttons else "none", buttons=buttons)
            if self.pace > 0:
                await asyncio.sleep(duration * self.pace / steps)
        self.cursor = (x1, y1)

    async def click(self, target, *, double: bool = False, button: str = "left",
                    modifiers: str = "") -> None:
        mods = sum(MOD[m] for m in modifiers.lower().split("+") if m)
        await self.move_to(target)
        x, y = self.cursor
        bits = {"left": 1, "right": 2, "middle": 4}[button]
        for count in (1, 2) if double else (1,):
            await self._mouse("mousePressed", x, y, button, bits, count, mods)
            await self._mouse("mouseReleased", x, y, button, 0, count, mods)
        await self.pause(0.25)

    async def drag(self, source, destination, *, duration: float = 0.6, modifiers: str = "") -> None:
        mods = sum(MOD[m] for m in modifiers.lower().split("+") if m)
        await self.move_to(source)
        x, y = self.cursor
        await self._mouse("mousePressed", x, y, "left", 1, 1, mods)
        await self.move_to(destination, buttons=1, duration=duration)
        x, y = self.cursor
        await self._mouse("mouseReleased", x, y, "left", 0, 1, mods)
        await self.pause(0.25)

    async def wheel(self, target, delta_y: float, modifiers: str = "") -> None:
        mods = sum(MOD[m] for m in modifiers.lower().split("+") if m)
        await self.move_to(target)
        x, y = self.cursor
        await self.send("Input.dispatchMouseEvent", type="mouseWheel", x=x, y=y, deltaX=0,
                        deltaY=delta_y, modifiers=mods)
        await self.pause(0.25)

    # ---- keyboard -----------------------------------------------------------------------------
    async def press(self, combo: str) -> None:
        """Press a key or combination, e.g. ``press("Tab")``, ``press("Ctrl+Z")``, ``press("b")``."""
        *mod_names, name = combo.split("+") if combo != "+" else ["+"]
        mods = sum(MOD[m.lower()] for m in mod_names)
        lowered = name.lower()
        if lowered in SPECIAL_KEYS:
            key, code, vk, text = SPECIAL_KEYS[lowered]
        elif len(name) == 1:
            key, vk = name, ord(name.upper())
            code = f"Key{name.upper()}" if name.isalpha() else (f"Digit{name}" if name.isdigit() else "")
            text = name
        else:
            raise DevRunError(f"unknown key: {combo}")
        if mods & (MOD["ctrl"] | MOD["alt"] | MOD["meta"]):
            text = None  # shortcuts do not produce text
        extra = {"text": text} if text else {}
        await self.send("Input.dispatchKeyEvent", type="keyDown", key=key, code=code, modifiers=mods,
                        windowsVirtualKeyCode=vk, **extra)
        await self.send("Input.dispatchKeyEvent", type="keyUp", key=key, code=code, modifiers=mods,
                        windowsVirtualKeyCode=vk)
        await self.pause(0.15)

    async def type_text(self, text: str) -> None:
        for char in text:
            await self.press(char)

    # ---- data helpers -------------------------------------------------------------------------
    def make_images(self, name: str, count: int, size: tuple[int, int] = (800, 600)) -> Path:
        return make_images(self.work / name, count, name, size)

    def summary(self) -> bool:
        if self.problems:
            self.check("no JavaScript or console errors during the run", False, f"{len(self.problems)} problem(s), listed below")
            for problem in self.problems:
                print("    - " + problem[:400])
        else:
            self.check("no JavaScript or console errors during the run", True)
        failed = [name for name, ok in self.results if not ok]
        print(f"\n{len(self.results) - len(failed)}/{len(self.results)} checks passed. "
              f"Screenshots: {self.shots}")
        return not failed
