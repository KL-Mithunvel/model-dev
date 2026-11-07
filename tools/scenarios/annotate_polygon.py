"""Polygons (v0.3), driven with the real mouse and keyboard. Checks read back what the SERVER stored."""

import json

from PIL import Image

DESCRIPTION = "polygons: click-to-draw (3 ways to close), move, edit points, simplify, keyboard-only, crossing warning"
CONFIG = {"annotations": {"save_debounce_ms": 150}}
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


async def click_at(s, x, y, **kwargs):
    await s.click(await point(s, x, y), **kwargs)


async def click_points(s, pts):
    for x, y in pts:
        await click_at(s, x, y)


def data(s, image_id):
    return s.api.call("GET", f"/api/images/{image_id}/annotations")[1]


def polygons(s, image_id):
    return [a for a in data(s, image_id)["annotations"] if a["kind"] == "polygon"]


def near(a, b, tolerance=2.5):
    return abs(a - b) <= tolerance


def points_near(got, want, tolerance=2.5):
    return len(got) == len(want) and all(near(g[0], w[0], tolerance) and near(g[1], w[1], tolerance) for g, w in zip(got, want, strict=True))


async def saved(s):
    await s.wait_for(SAVED, 10)


async def open_image(s, project, image_id):
    await s.goto(f"/#/projects/{project}/annotate/{image_id}")
    name = json.dumps(NAMES[image_id])
    await s.wait_for(f"{OVERLAY} && document.querySelector('.a-title') && document.querySelector('.a-title').textContent === {name}"
                     " && document.querySelector('.photo').complete")


def toast_text():
    return "document.getElementById('toasts').innerText"


async def run(s):
    folder = s.make_images("poly", 8, size=(W, H))
    rotated = folder / "rotated.jpg"
    exif = Image.Exif()
    exif[0x0112] = 6
    Image.new("RGB", (W, H), (200, 40, 40)).save(rotated, exif=exif)
    project = s.api.make_project("Polygons", folder)["id"]
    car = s.api.call("POST", f"/api/projects/{project}/classes", {"name": "car"})[1]["id"]
    s.api.call("POST", f"/api/projects/{project}/classes", {"name": "bus"})
    items = s.api.call("GET", f"/api/projects/{project}/images?limit=50")[1]["items"]
    NAMES.update({i["id"]: i["original_name"] for i in items})
    rotated_id = next(i["id"] for i in items if i["original_name"] == "rotated.jpg")
    ids = [i["id"] for i in items if i["id"] != rotated_id]

    # ---- three ways to close a polygon ------------------------------------------------------
    await s.say("Draw a polygon by clicking 5 points, then click the first point to close it")
    await open_image(s, project, ids[0])
    await s.press("p")
    pentagon = [(100, 100), (300, 80), (380, 220), (250, 320), (110, 260)]
    await click_points(s, pentagon)
    await s.shot("p1_drawing")
    await click_at(s, 100, 100)  # back on the first point
    await saved(s)
    got = polygons(s, ids[0])
    s.check("clicking the first point closed and saved a 5-point polygon in the right place",
            len(got) == 1 and points_near(got[0]["data"]["points"], pentagon), str(got))
    s.check("it has the active class and is selected, with its points shown in the list",
            got and got[0]["class_id"] == car and "5 points" in await s.js("document.querySelector('.ann-row[aria-pressed=true]').innerText"))
    await s.shot("p2_closed")

    await s.say("Close with Enter")
    square = [(450, 100), (600, 100), (600, 250), (450, 250)]
    await click_points(s, square)
    await s.press("Enter")
    await saved(s)
    s.check("Enter closed a 4-point polygon", len(polygons(s, ids[0])) == 2 and points_near(polygons(s, ids[0])[1]["data"]["points"], square))

    await s.say("Close with a double-click")
    triangle = [(100, 400), (300, 400)]
    await click_points(s, triangle)
    await s.click(await point(s, 200, 540), double=True)
    await saved(s)
    third = polygons(s, ids[0])
    s.check("a double-click added the last point and closed the polygon (3 points)",
            len(third) == 3 and points_near(third[2]["data"]["points"], [(100, 400), (300, 400), (200, 540)]), str([p["data"] for p in third]))

    # ---- backspace / escape / too few points -----------------------------------------------
    await s.say("While drawing: Backspace removes the last point, Escape cancels, 2 points cannot be closed")
    await click_points(s, [(500, 400), (650, 400), (650, 520), (500, 520)])
    await s.press("Backspace")
    s.check("Backspace removed the last drawn point (3 left)", await s.js("document.querySelectorAll('svg.overlay .poly-dot').length") == 3)
    await s.press("Ctrl+z")
    s.check("Ctrl+Z while drawing also removes a point (2 left)", await s.js("document.querySelectorAll('svg.overlay .poly-dot').length") == 2)
    await s.press("Enter")
    s.check("closing with 2 points is refused with a message",
            "at least 3 points" in (await s.js(toast_text()) or "") and len(polygons(s, ids[0])) == 3)
    await s.press("Escape")
    s.check("Escape cancelled the drawing", await s.js("document.querySelectorAll('svg.overlay .poly-dot').length") == 0
            and len(polygons(s, ids[0])) == 3)

    # ---- select, move, edit points ---------------------------------------------------------
    await s.say("Select a polygon and drag it; drag a corner; drag an edge's middle handle to add a point")
    await s.press("v")
    before = polygons(s, ids[0])[1]["data"]["points"]  # the square
    await s.drag(await point(s, 525, 175), await point(s, 565, 205), duration=0.2)
    await saved(s)
    after = polygons(s, ids[0])[1]["data"]["points"]
    s.check("dragging the polygon moved every point by about (40, 30)",
            all(near(a[0] - b[0], 40) and near(a[1] - b[1], 30) for a, b in zip(after, before, strict=True)), f"{before} -> {after}")
    s.check("the polygon kept its exact shape (same edge lengths)",
            near(abs(after[1][0] - after[0][0]), abs(before[1][0] - before[0][0]), 0.2))
    await s.drag("svg.overlay .handle.vertex[data-vertex='2']", await point(s, 640, 300), duration=0.2)
    await saved(s)
    moved = polygons(s, ids[0])[1]["data"]["points"]
    s.check("dragging a corner moved only that point", near(moved[2][0], 640) and near(moved[2][1], 300)
            and points_near([moved[0], moved[1], moved[3]], [after[0], after[1], after[3]], 0.2), str(moved))
    count = len(moved)
    await s.drag("svg.overlay .handle.mid[data-mid='0']", await point(s, 540, 60), duration=0.2)
    await saved(s)
    grown = polygons(s, ids[0])[1]["data"]["points"]
    s.check("dragging an edge's middle handle added a point where it was dropped",
            len(grown) == count + 1 and near(grown[1][0], 540) and near(grown[1][1], 60), str(grown))
    await s.press("Ctrl+z")
    await saved(s)
    s.check("one undo removes both the new point and its move",
            len(polygons(s, ids[0])[1]["data"]["points"]) == count)

    await s.say("Remove a point: Alt+click, then Delete on a selected point; a triangle refuses")
    await s.click(await point(s, 240, 200))  # select the 5-point polygon
    await s.click("svg.overlay .handle.vertex[data-vertex='3']", modifiers="alt")
    await saved(s)
    s.check("Alt+click removed that point (5 -> 4)", len(polygons(s, ids[0])[0]["data"]["points"]) == 4)
    await s.click("svg.overlay .handle.vertex[data-vertex='0']")
    await s.press("Delete")
    await saved(s)
    s.check("Delete removed the selected point (4 -> 3)", len(polygons(s, ids[0])[0]["data"]["points"]) == 3)
    await s.press("Delete")
    await s.pause(0.3)
    s.check("a triangle cannot lose another point (a message explains)",
            len(polygons(s, ids[0])[0]["data"]["points"]) == 3 and "at least 3 points" in (await s.js(toast_text()) or ""))

    # ---- crossing warning, edges, zoom accuracy ----------------------------------------------
    await s.say("A polygon that crosses itself is allowed but flagged")
    await open_image(s, project, ids[1])
    await s.press("p")
    # (a perfectly symmetric bow-tie has zero area and is refused; this one has unequal loops)
    await click_points(s, [(100, 100), (300, 300), (300, 100), (100, 200)])
    await s.press("Enter")
    await saved(s)
    await s.pause(0.3)
    s.check("a crossing warning toast appears", "crosses itself" in (await s.js(toast_text()) or ""))
    s.check("and the list row says so", "crosses itself" in (await s.js("(document.querySelector('.ann-row') || {innerText: ''}).innerText") or ""))
    await s.say("A zero-area polygon (a symmetric bow-tie) is refused with an explanation")
    await s.press("p")
    await click_points(s, [(400, 100), (600, 300), (600, 100), (400, 300)])
    await s.press("Enter")
    await s.pause(0.3)
    s.check("a flat polygon is refused with a message and nothing extra is saved",
            "too flat or small" in (await s.js(toast_text()) or "") and len(polygons(s, ids[1])) == 1)
    await s.press("Escape")

    await s.say("Points clicked outside the image are clamped to its edge")
    await open_image(s, project, ids[2])
    await s.press("p")
    rect = await s.js(f"(() => {{ const r = {OVERLAY}.getBoundingClientRect(); return [r.left, r.top, r.right, r.bottom]; }})()")
    # the image is fitted with a 16 px margin inside the canvas, so 8 px outside the image is still on the canvas
    gap = 8
    outside = [(rect[0] - gap, rect[1] - gap), (rect[2] + gap, rect[1] - gap), (rect[2] + gap, rect[3] + gap), (rect[0] - gap, rect[3] + gap)]
    for sx, sy in outside:
        await s.click((sx, sy))
    await s.press("Enter")
    await saved(s)
    pts = polygons(s, ids[2])[0]["data"]["points"]
    s.check("the 4 outside clicks became the 4 image corners", points_near(pts, [(0, 0), (W, 0), (W, H), (0, H)], 0.6), str(pts))

    await s.say("Zoom in and pan, then draw: points must land under the pointer")
    await open_image(s, project, ids[3])
    await s.press("p")
    await s.wheel(await point(s, 400, 300), -360)
    clicks = [(700.0, 380.0), (900.0, 400.0), (880.0, 560.0), (720.0, 540.0)]
    for c in clicks:
        await s.click(c)
    await s.press("Enter")
    await saved(s)
    handles = await s.js("[...document.querySelectorAll('svg.overlay .handle.vertex')].map(h => { const r = h.getBoundingClientRect(); return [r.left + r.width / 2, r.top + r.height / 2]; })")
    s.check("each vertex handle sits under the click that created it (within 2.5 px) at this zoom",
            len(handles) == 4 and all(abs(a[0] - b[0]) <= 2.5 and abs(a[1] - b[1]) <= 2.5 for a, b in zip(handles, clicks, strict=True)), f"{handles} vs {clicks}")

    # ---- keyboard only -----------------------------------------------------------------------
    await s.say("Keyboard only: P, Enter drops a hexagon; ] picks a point; arrows move it; I adds one; Delete removes one")
    await open_image(s, project, ids[4])
    await s.js("document.querySelector('.stage').focus()")
    await s.press("p")
    await s.press("Enter")
    await saved(s)
    hexagon = polygons(s, ids[4])
    s.check("Enter dropped a 6-point polygon", len(hexagon) == 1 and len(hexagon[0]["data"]["points"]) == 6)
    start = hexagon[0]["data"]["points"]
    await s.press("v")
    await s.press("]")
    await s.press("Shift+Right")
    await s.press("Down")
    await saved(s)
    moved = polygons(s, ids[4])[0]["data"]["points"]
    s.check("] selected the first point; Shift+Right moved it 10 px and Down 1 px; the others did not move",
            near(moved[0][0] - start[0][0], 10, 0.6) and near(moved[0][1] - start[0][1], 1, 0.6) and points_near(moved[1:], start[1:], 0.2), f"{start[0]} -> {moved[0]}")
    await s.press("i")
    await saved(s)
    s.check("I inserted a point after the selected one", len(polygons(s, ids[4])[0]["data"]["points"]) == 7)
    await s.press("Delete")
    await saved(s)
    s.check("Delete removed the selected point", len(polygons(s, ids[4])[0]["data"]["points"]) == 6)
    await s.press("Escape")
    await s.press("Tab")
    s.check("Tab still cycles annotations", await s.js("document.querySelectorAll('.ann-row[aria-pressed=true]').length") == 1)

    # ---- simplify ----------------------------------------------------------------------------
    await s.say("Simplify a polygon that has far too many points")
    dense = [[100 + i * 5, 100] for i in range(40)] + [[300, 100], [300, 300], [100, 300]]
    status, body = s.api.call("PUT", f"/api/images/{ids[5]}/annotations", {"rev": 0, "annotations": [{"class_id": car, "kind": "polygon", "data": {"points": dense}}], "marked_empty": False, "label_class_id": None})
    assert status == 200, body
    await open_image(s, project, ids[5])
    await s.click(".ann-row")
    await s.click(s.by_text(".a-actions .btn", "Simplify polygon", exact=False))
    await saved(s)
    simpler = polygons(s, ids[5])[0]["data"]["points"]
    s.check("Simplify reduced 43 points to just the corners", len(simpler) == 4, str(len(simpler)))
    s.check("a toast reports the reduction", "from 43 to 4" in (await s.js(toast_text()) or ""))
    await s.click(s.by_text("#toasts button", "Undo"))
    await saved(s)
    s.check("Undo from the toast restores all 43 points", len(polygons(s, ids[5])[0]["data"]["points"]) == 43)

    # ---- mixed shapes, repeat previous, rotated image, stats ----------------------------------
    await s.say("Boxes and polygons together; repeat the previous image; stats count polygons")
    await open_image(s, project, ids[6])
    await s.press("b")
    await s.drag(await point(s, 50, 50), await point(s, 150, 120), duration=0.2)
    await s.press("p")
    await click_points(s, [(300, 300), (420, 310), (380, 420)])
    await s.press("Enter")
    await saved(s)
    kinds = sorted(a["kind"] for a in data(s, ids[6])["annotations"])
    s.check("a box and a polygon live on the same image", kinds == ["box", "polygon"], str(kinds))
    await open_image(s, project, ids[7])
    await s.click(s.by_text(".a-actions .btn", "Repeat previous image", exact=False))
    await s.wait_for("document.querySelectorAll('.ann-row').length === 2")
    await saved(s)
    copied = sorted(a["kind"] for a in data(s, ids[7])["annotations"])
    s.check("Repeat previous image copied the box AND the polygon", copied == ["box", "polygon"], str(copied))
    stats = s.api.call("GET", f"/api/projects/{project}/annotation-stats")[1]["per_class"][0]
    s.check("the project stats count polygons separately", stats["polygons"] >= 6 and stats["boxes"] >= 2, str(stats))

    await open_image(s, project, rotated_id)
    await s.press("p")
    await click_points(s, [(100, 650), (480, 660), (300, 780)])
    await s.press("Enter")
    await saved(s)
    got = polygons(s, rotated_id)
    s.check("a polygon low on the EXIF-rotated image (600 x 800) was accepted", len(got) == 1 and near(got[0]["data"]["points"][2][1], 780), str(got))
