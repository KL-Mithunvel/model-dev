"""Regression checks for the v0.3 independent review (each one failed or was unguarded before the fix)."""

import asyncio
import json
import tempfile
from pathlib import Path

from PIL import Image

DESCRIPTION = "v0.3 review regressions: stale point, double-click close, flat edits, repeat across sizes, P+Enter focus, drawing guard, Esc on toasts"
CONFIG = {"annotations": {"save_debounce_ms": 150, "min_polygon_area_px": 3000}}
W, H = 800, 600
SAVED = "document.querySelector('.save-chip').dataset.status === 'saved'"
OVERLAY = "document.querySelector('svg.overlay')"
NAMES = {}


async def point(s, x, y):
    sx, sy = await s.js(
        f"(() => {{ const svg = {OVERLAY}; const r = svg.getBoundingClientRect(); const v = svg.viewBox.baseVal;"
        f"return [r.left + {x} * r.width / v.width, r.top + {y} * r.height / v.height]; }})()"
    )
    return (sx, sy)


async def click_points(s, pts):
    for x, y in pts:
        await s.click(await point(s, x, y))


def annotations(s, image_id):
    return s.api.call("GET", f"/api/images/{image_id}/annotations")[1]["annotations"]


def polygons(s, image_id):
    return [a for a in annotations(s, image_id) if a["kind"] == "polygon"]


async def open_image(s, project, image_id):
    await s.goto(f"/#/projects/{project}/annotate/{image_id}")
    name = json.dumps(NAMES[image_id])
    await s.wait_for(f"{OVERLAY} && document.querySelector('.a-title') && document.querySelector('.a-title').textContent === {name}"
                     " && document.querySelector('.photo').complete")


async def clear_toasts(s):
    await s.js("document.getElementById('toasts').replaceChildren()")


async def run(s):
    folder = s.make_images("rev", 3, size=(W, H))
    project = s.api.make_project("Review", folder)["id"]
    s.api.call("POST", f"/api/projects/{project}/classes", {"name": "car"})
    items = s.api.call("GET", f"/api/projects/{project}/images?limit=50")[1]["items"]
    NAMES.update({i["id"]: i["original_name"] for i in items})
    ids = [i["id"] for i in items]
    errors = []

    # ---- P + Enter right after clicking the tool BUTTON (focus used to stay on the button) -------
    await s.say("Click the polygon tool button, then press Enter: a hexagon must appear")
    await open_image(s, project, ids[0])
    await s.click("button[aria-label^='Draw polygon']")
    await s.press("Enter")
    await s.wait_for(SAVED, 10)
    got = polygons(s, ids[0])
    s.check("Enter after clicking the polygon tool button dropped a hexagon", len(got) == 1 and len(got[0]["data"]["points"]) == 6, str(got))

    # ---- double-click on the first point closes without a stray extra point --------------------
    await s.say("Double-click the first point: the polygon closes and nothing else starts")
    await click_points(s, [(100, 100), (300, 100), (200, 300)])
    await s.click(await point(s, 100, 100), double=True)
    await s.wait_for(SAVED, 10)
    await asyncio.sleep(0.6)
    now = polygons(s, ids[0])
    drafts = await s.js("document.querySelectorAll('svg.overlay .poly-dot').length")
    s.check("double-clicking the first point made exactly one new triangle", len(now) == 2 and len(now[1]["data"]["points"]) == 3, str([p["data"] for p in now]))
    s.check("no half-drawn polygon is left behind", drafts == 0, f"{drafts} draft dots")

    # ---- an edit that would flatten the polygon is refused (the server would refuse the save) ----
    await s.say("Drag a corner so the triangle becomes almost flat: the change must be refused")
    await s.press("v")
    before = polygons(s, ids[0])[1]["data"]["points"]
    await clear_toasts(s)
    await s.drag("svg.overlay .handle.vertex[data-vertex='2']", await point(s, 200, 105), duration=0.2)
    await asyncio.sleep(0.5)
    after = polygons(s, ids[0])[1]["data"]["points"]
    toast = await s.js("document.getElementById('toasts').innerText")
    s.check("the flattening drag was not applied", after == before, f"{before} -> {after}")
    s.check("the user was told why", "flatten" in toast.lower(), toast)
    status = await s.js("document.querySelector('.save-chip').dataset.status")
    s.check("saving did not enter an error state", status == "saved", status)

    # ---- a cancelled midpoint drag leaves no stale point that crashes the next key ------------
    await s.say("Start dragging a midpoint handle, press Escape, then use point keys")
    await s.js("window.__errs = []; window.addEventListener('error', (e) => window.__errs.push(String(e.message)))")
    mid = await s.js("(() => { const r = document.querySelector('svg.overlay .handle.mid')?.getBoundingClientRect(); return r ? [r.left + r.width / 2, r.top + r.height / 2] : null; })()")
    if mid:
        await s.send("Input.dispatchMouseEvent", type="mouseMoved", x=mid[0], y=mid[1])
        await s.send("Input.dispatchMouseEvent", type="mousePressed", x=mid[0], y=mid[1], button="left", clickCount=1)
        await s.send("Input.dispatchMouseEvent", type="mouseMoved", x=mid[0] + 30, y=mid[1] + 20, button="left")
        await s.press("Escape")
        await s.send("Input.dispatchMouseEvent", type="mouseReleased", x=mid[0] + 30, y=mid[1] + 20, button="left", clickCount=1)
    for key in ("]", "Right", "i", "["):
        await s.press(key)
    errors = await s.js("window.__errs")
    s.check("point keys after a cancelled midpoint drag cause no script error", not errors, str(errors))
    await s.wait_for(SAVED, 10)

    # ---- half-drawn polygon is protected from navigation and tool keys ------------------------
    await s.say("While drawing, A / D / B must not silently throw the polygon away")
    await s.press("p")
    await click_points(s, [(500, 100), (700, 100)])
    title = await s.js("document.querySelector('.a-title').textContent")
    await clear_toasts(s)
    await s.press("d")
    await asyncio.sleep(0.3)
    same = await s.js("document.querySelector('.a-title').textContent") == title
    toast = await s.js("document.getElementById('toasts').innerText")
    s.check("D did not leave the image while a polygon was half drawn", same, toast)
    s.check("a message explained how to continue", "finish the polygon" in toast.lower(), toast)
    await s.press("b")
    still = await s.js("document.querySelectorAll('svg.overlay .poly-dot').length")
    s.check("switching to the box tool did not discard the points", still == 2, f"{still} dots")

    # ---- Escape: first cancels the drawing (toast stays), then dismisses the toast ------------
    await s.press("Escape")
    drawing = await s.js("document.querySelectorAll('svg.overlay .poly-dot').length")
    s.check("Escape cancelled the half-drawn polygon", drawing == 0, f"{drawing} dots")
    for _ in range(6):
        await s.press("Escape")
        if not await s.js("document.getElementById('toasts').children.length"):
            break
    left = await s.js("document.getElementById('toasts').children.length")
    s.check("Escape dismisses notifications", left == 0, f"{left} left")

    # ---- Repeat previous image across different image sizes -----------------------------------
    await s.say("Copy annotations onto a smaller image: shapes that do not fit are skipped and reported")
    other = Path(tempfile.mkdtemp(prefix="rev_sizes_"))
    Image.new("RGB", (800, 600), (30, 120, 200)).save(other / "a_big.jpg")
    Image.new("RGB", (400, 300), (200, 120, 30)).save(other / "b_small.jpg")
    project2 = s.api.make_project("Sizes", other)["id"]
    car2 = s.api.call("POST", f"/api/projects/{project2}/classes", {"name": "car"})[1]["id"]
    pair = s.api.call("GET", f"/api/projects/{project2}/images?limit=50")[1]["items"]
    NAMES.update({i["id"]: i["original_name"] for i in pair})
    big = next(i["id"] for i in pair if i["original_name"] == "a_big.jpg")
    small = next(i["id"] for i in pair if i["original_name"] == "b_small.jpg")
    fits = {"class_id": car2, "kind": "polygon", "data": {"points": [[50, 50], [200, 50], [120, 200]]}}
    too_far = {"class_id": car2, "kind": "polygon", "data": {"points": [[500, 100], [700, 100], [600, 300]]}}
    status, body = s.api.call("PUT", f"/api/images/{big}/annotations", {"rev": 0, "annotations": [fits, too_far], "marked_empty": False, "label_class_id": None})
    assert status == 200, body
    await open_image(s, project2, small)
    await s.click(s.by_text(".a-actions .btn", "Repeat previous image", exact=False))
    await s.wait_for("document.querySelectorAll('.ann-row').length === 1")
    await s.wait_for(SAVED, 10)
    toast = await s.js("document.getElementById('toasts').innerText")
    s.check("only the polygon that fits the smaller image was copied", len(polygons(s, small)) == 1, str(polygons(s, small)))
    s.check("the toast says one was skipped", "skipped 1" in toast, toast)
    status = await s.js("document.querySelector('.save-chip').dataset.status")
    s.check("the save was accepted (not refused for out-of-bounds points)", status == "saved", status)
