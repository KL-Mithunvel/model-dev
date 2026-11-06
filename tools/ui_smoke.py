"""Browser smoke test for the web UI (dev tool, not part of the app).

Starts its own throwaway server on a free port with a temporary data folder and generated
images, drives headless Edge/Chrome through the DevTools protocol, prints PASS/FAIL per check,
then cleans everything up. Needs: Edge or Chrome installed, `websockets` (in requirements.txt).

    python tools/ui_smoke.py            # exit code 0 = all checks passed
    python tools/ui_smoke.py --keep     # keep the temp folder (screenshots) and print its path

It exists because the unit tests cannot see browser behaviour (focus, keyboard, routing) and
that is where the v0.1 review found its bugs. Add a check here whenever a UI bug is fixed.
"""

import argparse
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
BROWSER_CANDIDATES = [
    os.environ.get("STUDIO_BROWSER", ""),
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
]
PAGE_SIZE = 20  # small, so "load more" is easy to trigger
GALLERY_IMAGES = 70
CANCEL_IMAGES = 500

results: list[tuple[str, bool]] = []
problems: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, bool(ok)))
    print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail and not ok else ""))


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def make_images(folder: Path, count: int, prefix: str) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    for i in range(count):
        r, g, b = (int(255 * c) for c in colorsys.hsv_to_rgb((i % 70) / 70, 0.5, 0.9))
        Image.new("RGB", (800, 600), (r, g, (b + i) % 256)).save(
            folder / f"{prefix}_{i:03d}.jpg", quality=90
        )


class Api:
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

    def wait_job(self, job_id: str, seconds: float = 60):
        deadline = time.time() + seconds
        while time.time() < deadline:
            _, job = self.call("GET", f"/api/jobs/{job_id}")
            if job["state"] in ("done", "failed"):
                return job
            time.sleep(0.1)
        raise TimeoutError("job did not finish")


class Browser:
    """Minimal DevTools-protocol client."""

    def __init__(self, ws) -> None:
        self.ws = ws
        self.counter = 0

    async def send(self, method: str, **params):
        self.counter += 1
        mid = self.counter
        await self.ws.send(json.dumps({"id": mid, "method": method, "params": params}))
        while True:
            message = json.loads(await self.ws.recv())
            if message.get("method") == "Runtime.exceptionThrown":
                details = message["params"]["exceptionDetails"]
                problems.append("exception: " + str(details.get("exception", {}).get("description", details))[:300])
            if message.get("method") == "Log.entryAdded" and message["params"]["entry"]["level"] == "error":
                entry = message["params"]["entry"]
                problems.append("console: " + entry["text"] + " " + entry.get("url", ""))
            if message.get("id") == mid:
                return message.get("result", {})

    async def js(self, expression: str):
        result = await self.send(
            "Runtime.evaluate", expression=expression, awaitPromise=True, returnByValue=True
        )
        if "exceptionDetails" in result:
            problems.append("eval: " + expression[:70] + " -> " + str(result["exceptionDetails"])[:200])
        return result.get("result", {}).get("value")

    async def wait_for(self, expression: str, seconds: float = 15) -> bool:
        for _ in range(int(seconds / 0.2)):
            if await self.js(f"!!({expression})"):
                return True
            await asyncio.sleep(0.2)
        problems.append("timeout: " + expression[:90])
        return False

    async def key(self, key: str, code: str, vk: int, text: str | None = None) -> None:
        extra = {"text": text} if text else {}
        await self.send("Input.dispatchKeyEvent", type="keyDown", key=key, code=code,
                        windowsVirtualKeyCode=vk, **extra)
        await self.send("Input.dispatchKeyEvent", type="keyUp", key=key, code=code,
                        windowsVirtualKeyCode=vk)

    async def screenshot(self, path: Path) -> None:
        result = await self.send("Page.captureScreenshot", format="png")
        path.write_bytes(base64.b64decode(result["data"]))


async def run_checks(browser: Browser, api: Api, base: str, gallery_dir: Path, cancel_dir: Path,
                     out_dir: Path) -> None:
    stamp = int(time.time())
    _, project_a = api.call("POST", "/api/projects", {"name": f"Smoke A {stamp}"})
    job = api.call("POST", f"/api/projects/{project_a['id']}/imports", {"path": str(gallery_dir)})[1]
    api.wait_job(job["job_id"])
    _, project_b = api.call("POST", "/api/projects", {"name": f"Smoke B {stamp}"})
    a, b = project_a["id"], project_b["id"]

    await browser.send("Page.enable")
    await browser.send("Runtime.enable")
    await browser.send("Log.enable")
    await browser.send("Emulation.setDeviceMetricsOverride", width=1280, height=800,
                       deviceScaleFactor=1, mobile=False)

    # --- skip link (review blocker): first Tab, Enter, gallery must survive ---------------------
    await browser.send("Page.navigate", url=f"{base}/#/projects/{a}")
    await browser.wait_for(f"document.querySelectorAll('.tile').length === {PAGE_SIZE}")
    check("page shows no stray 'null' text", await browser.js("!document.body.innerText.includes('null')"))
    await browser.key("Tab", "Tab", 9)
    check("first Tab reaches the skip link", await browser.js("document.activeElement.className.includes('skip')"))
    await browser.key("Enter", "Enter", 13, text=chr(13))
    await asyncio.sleep(0.5)
    check("skip link keeps the view and moves focus to main",
          await browser.js("document.querySelectorAll('.tile').length") == PAGE_SIZE
          and await browser.js("location.hash") == f"#/projects/{a}"
          and await browser.js("document.activeElement.id") == "main")

    # --- load more keeps keyboard focus ---------------------------------------------------------
    await browser.js(f"document.querySelectorAll('.tile')[{PAGE_SIZE - 1}].focus()")
    await browser.key("ArrowRight", "ArrowRight", 39)
    await browser.wait_for(f"document.querySelectorAll('.tile').length === {PAGE_SIZE * 2}")
    check("load more appends tiles and keeps focus on the same tile",
          await browser.js("document.activeElement.dataset.index") == str(PAGE_SIZE - 1))
    await browser.key("ArrowRight", "ArrowRight", 39)
    check("arrow keys continue from the focused tile",
          await browser.js("document.activeElement.dataset.index") == str(PAGE_SIZE))

    # --- inspector keeps focus; Space toggles without resetting the selection -------------------
    await browser.js("document.querySelectorAll('.tile')[0].click()")
    await browser.js("document.querySelector('.inspector .seg button[data-value=train]').focus()")
    await browser.key("Enter", "Enter", 13, text=chr(13))
    await browser.wait_for("document.querySelectorAll('.tile .badge').length === 1")
    check("split button keeps focus after use",
          await browser.js("document.activeElement.dataset.value") == "train"
          and await browser.js("document.activeElement.getAttribute('aria-pressed')") == "true")
    await browser.js("document.querySelectorAll('.tile')[0].click()")
    await browser.js("document.querySelectorAll('.tile')[1].focus()")
    await browser.send("Input.dispatchKeyEvent", type="keyDown", key=" ", code="Space",
                       windowsVirtualKeyCode=32, text=" ")
    await browser.send("Input.dispatchKeyEvent", type="keyUp", key=" ", code="Space",
                       windowsVirtualKeyCode=32)
    await asyncio.sleep(0.3)
    check("Space adds to the selection", await browser.js("document.querySelectorAll('.tile[aria-pressed=true]').length") == 2)
    check("exactly one tile is in the tab order", await browser.js("document.querySelectorAll('.tile[tabindex=\"0\"]').length") == 1)

    # --- tag filter state -----------------------------------------------------------------------
    await browser.js("document.querySelectorAll('.tile')[2].click()")
    await browser.js("(()=>{const i=document.querySelector('.inspector .tag-box input'); i.focus(); i.value='zzz';})()")
    await browser.key("Enter", "Enter", 13, text=chr(13))
    await browser.wait_for("document.querySelector('#f-tag option[value=zzz]')")
    await browser.js("(()=>{const s=document.getElementById('f-tag'); s.value='zzz'; s.dispatchEvent(new Event('change'));})()")
    await browser.wait_for("document.querySelectorAll('.tile').length === 1")
    await browser.js("document.querySelectorAll('.tile')[0].click()")
    await browser.js("document.querySelector('.inspector .chip button').click()")
    await browser.wait_for(f"document.querySelectorAll('.tile').length === {PAGE_SIZE}")
    check("removing the last use of the filtered tag resets filter and grid",
          await browser.js("document.getElementById('f-tag').value") == "")

    # --- router race ----------------------------------------------------------------------------
    await browser.js(f"location.hash = '#/projects/{a}'; location.hash = '#/projects'; true")
    await asyncio.sleep(1.5)
    check("fast navigation ends on the last route",
          await browser.js("document.getElementById('title').textContent") == "Projects"
          and await browser.js("!document.querySelector('.gallery')"))

    # --- import: double click, delete guard, cancel ---------------------------------------------
    await browser.send("Page.navigate", url=f"{base}/#/projects/{b}")
    await browser.wait_for("document.querySelector('.empty')")
    await browser.js("[...document.querySelectorAll('.toolbar-actions .btn')].find(x=>x.textContent.includes('Import')).click()")
    await browser.wait_for("document.getElementById('import-path')")
    await browser.js(f"document.getElementById('import-path').value = {json.dumps(str(cancel_dir))}")
    start = "[...document.querySelectorAll('dialog .btn')].find(x=>x.textContent==='Start import')"
    await browser.js(f"{start}.click()")
    await browser.js(f"{start}?.click()")  # a double click must not start a second import
    await browser.wait_for("document.querySelector('dialog .progress')")
    status, _ = api.call("DELETE", f"/api/projects/{b}")
    check("deleting a project during its import is refused (409)", status == 409, str(status))
    await browser.wait_for("document.querySelector('dialog .progress > div').style.width.length > 0 && document.querySelector('dialog .progress > div').style.width !== '0%'", 30)
    await browser.js("[...document.querySelectorAll('dialog .btn')].find(x=>x.textContent==='Cancel import').click()")
    await browser.wait_for("document.querySelector('dialog .stats')", 30)
    summary = await browser.js("document.querySelector('dialog').innerText")
    await browser.screenshot(out_dir / "cancelled_summary.png")
    _, listing = api.call("GET", f"/api/projects/{b}/images?limit=1")
    _, batches = api.call("GET", f"/api/projects/{b}/batches")
    check("cancel stops the import and says so", "cancelled" in summary.lower(), summary[:60])
    check("images kept = images listed = batch record, and fewer than all",
          listing["total"] == batches[0]["added"] and 0 < listing["total"] < CANCEL_IMAGES,
          f"listed={listing['total']} batch={batches[0]['added']}")
    check("double click started only one import", len(batches) == 1, f"{len(batches)} batches")

    check("no JavaScript errors or console errors during the run", not problems, "; ".join(problems)[:300])


def find_browser() -> str:
    for candidate in BROWSER_CANDIDATES:
        if candidate and Path(candidate).exists():
            return candidate
    sys.exit("No Edge/Chrome found. Set STUDIO_BROWSER to the browser executable.")


async def main_async(base: str, api: Api, work: Path) -> None:
    browser_path = find_browser()
    debug_port = free_port()
    process = subprocess.Popen(
        [browser_path, "--headless=new", "--disable-gpu", f"--remote-debugging-port={debug_port}",
         f"--user-data-dir={work / 'browser-profile'}", "--no-first-run", "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        page = None
        for _ in range(60):
            try:
                tabs = json.load(urllib.request.urlopen(f"http://127.0.0.1:{debug_port}/json"))
                page = next(t for t in tabs if t["type"] == "page")
                break
            except Exception:
                time.sleep(0.5)
        if page is None:
            sys.exit("Could not connect to the browser's debugging port.")
        async with websockets.connect(page["webSocketDebuggerUrl"], max_size=None) as ws:
            await run_checks(Browser(ws), api, base, work / "gallery_images", work / "cancel_images", work)
    finally:
        process.terminate()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("--keep", action="store_true", help="keep the temp folder and print its path")
    args = parser.parse_args()

    work = Path(tempfile.mkdtemp(prefix="studio_ui_smoke_"))
    server = None
    try:
        config = copy.deepcopy(yaml.safe_load((REPO / "config.yaml").read_text(encoding="utf-8")))
        port = free_port()
        config["app"].update({"data_dir": str(work / "data"), "port": port})
        config["gallery"]["default_page_size"] = PAGE_SIZE
        config_path = work / "smoke.yaml"
        config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
        print("Generating test images...")
        make_images(work / "gallery_images", GALLERY_IMAGES, "g")
        make_images(work / "cancel_images", CANCEL_IMAGES, "c")

        server = subprocess.Popen(
            [sys.executable, "-m", "studio", "--config", str(config_path)], cwd=REPO,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        base = f"http://127.0.0.1:{port}"
        for _ in range(60):
            try:
                urllib.request.urlopen(f"{base}/api/health", timeout=1)
                break
            except Exception:
                time.sleep(0.5)
        else:
            sys.exit("The server did not start.")

        asyncio.run(main_async(base, Api(base), work))
    finally:
        if server is not None:
            server.terminate()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()
        if args.keep:
            print(f"Kept: {work}")
        else:
            shutil.rmtree(work, ignore_errors=True)

    failed = [name for name, ok in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
