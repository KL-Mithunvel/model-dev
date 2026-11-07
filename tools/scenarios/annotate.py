"""The annotator, driven with the real mouse and keyboard (v0.2).

Every check that matters looks at what the SERVER stored, not only at what the page shows."""


from PIL import Image

DESCRIPTION = "annotator: draw 20+ boxes, move/resize/nudge, undo/redo, classes, labels, no-objects, navigation"
CONFIG = {"annotations": {"save_debounce_ms": 150}}  # keep the run short; behaviour is the same

W, H = 800, 600
SAVED = "document.querySelector('.save-chip') && document.querySelector('.save-chip').dataset.status === 'saved'"


async def point(s, x, y):
    """Screen position of an image pixel (x, y), derived from where the overlay is drawn."""
    script = (
        "(() => { const r = document.querySelector('svg.overlay').getBoundingClientRect();"
        "const v = document.querySelector('svg.overlay').viewBox.baseVal;"
        f"return [r.left + {x} * r.width / v.width, r.top + {y} * r.height / v.height]; }})()"
    )
    sx, sy = await s.js(script)
    return (sx, sy)


async def draw(s, x0, y0, x1, y1):
    await s.drag(await point(s, x0, y0), await point(s, x1, y1), duration=0.25)


def stored(s, image_id):
    return s.api.call("GET", f"/api/images/{image_id}/annotations")[1]


def near(a, b, tolerance=3.0):
    return abs(a - b) <= tolerance


async def saved(s):
    await s.wait_for(SAVED, 10)


async def run(s):
    folder = s.make_images("pics", 12, size=(W, H))
    # image 13: stored on disk as 800x600 but EXIF-rotated, so it DISPLAYS as 600x800
    rotated = folder / "rotated.jpg"
    exif = Image.Exif()
    exif[0x0112] = 6
    Image.new("RGB", (W, H), (200, 40, 40)).save(rotated, exif=exif)
    project = s.api.make_project("Annotate", folder)["id"]
    car = s.api.call("POST", f"/api/projects/{project}/classes", {"name": "car"})[1]["id"]
    bus = s.api.call("POST", f"/api/projects/{project}/classes", {"name": "bus"})[1]["id"]
    images = s.api.call("GET", f"/api/projects/{project}/images?limit=50")[1]["items"]
    first = images[0]["id"]

    await s.say("Open the annotator on the first image")
    await s.goto(f"/#/projects/{project}/annotate/{first}")
    await s.wait_for("document.querySelector('svg.overlay') && document.querySelector('.photo').complete")
    await s.shot("a1_open")
    s.check("the annotator shows the image, tools, classes and filmstrip",
            await s.js("!!document.querySelector('.toolstrip') && document.querySelectorAll('.class-row').length === 2 "
                       "&& document.querySelectorAll('.film-item').length >= 5"))
    s.check("image and overlay agree on the image size",
            await s.js("(() => { const p = document.querySelector('.photo'); const v = document.querySelector('svg.overlay').viewBox.baseVal;"
                       "return p.naturalWidth === v.width && p.naturalHeight === v.height; })()"))

    await s.say("Draw a box with the mouse (B, then drag)")
    await s.press("b")
    await draw(s, 100, 100, 300, 250)
    await saved(s)
    got = stored(s, first)["annotations"]
    s.check("one box was drawn and saved with the right coordinates",
            len(got) == 1 and near(got[0]["data"]["x"], 100) and near(got[0]["data"]["y"], 100)
            and near(got[0]["data"]["w"], 200) and near(got[0]["data"]["h"], 150), str(got))
    s.check("it got the first class", got and got[0]["class_id"] == car)

    await s.say("Draw 20 more boxes without touching a menu")
    for i in range(20):
        x, y = 20 + (i % 5) * 150, 300 + (i // 5) * 70
        await draw(s, x, y, x + 100, y + 50)
    await saved(s)
    s.check("21 boxes are stored", len(stored(s, first)["annotations"]) == 21)
    await s.shot("a2_many_boxes")

    await s.say("Select a box and drag it")
    await s.press("v")
    before = stored(s, first)["annotations"][0]["data"]
    await s.drag(await point(s, 200, 175), await point(s, 260, 215), duration=0.25)
    await saved(s)
    after = stored(s, first)["annotations"][0]["data"]
    s.check("dragging moved the box by about (60, 40)",
            near(after["x"] - before["x"], 60) and near(after["y"] - before["y"], 40) and near(after["w"], before["w"], 0.5),
            f"{before} -> {after}")

    await s.say("Resize it with the bottom-right handle")
    await s.drag(await point(s, after["x"] + after["w"], after["y"] + after["h"]), await point(s, after["x"] + after["w"] + 40, after["y"] + after["h"] + 30), duration=0.25)
    await saved(s)
    resized = stored(s, first)["annotations"][0]["data"]
    s.check("the handle grew the box by about (40, 30) and kept its corner",
            near(resized["w"] - after["w"], 40) and near(resized["h"] - after["h"], 30) and near(resized["x"], after["x"], 0.5), f"{after} -> {resized}")

    await s.say("Keyboard: nudge, then undo and redo")
    count = len(stored(s, first)["annotations"])
    await s.press("Right")
    await s.press("Shift+Down")
    await saved(s)
    nudged = stored(s, first)["annotations"][0]["data"]
    s.check("arrows nudge the selected box (1 px, and 10 px with Shift)",
            near(nudged["x"] - resized["x"], 1, 0.5) and near(nudged["y"] - resized["y"], 10, 0.5), f"{resized} -> {nudged}")
    await s.press("Ctrl+z")
    await saved(s)
    s.check("undo restores the exact earlier position",
            stored(s, first)["annotations"][0]["data"] == resized)
    await s.press("Ctrl+Shift+z")
    await saved(s)
    s.check("redo brings the nudge back", stored(s, first)["annotations"][0]["data"] == nudged)
    await s.press("Delete")
    await saved(s)
    s.check("Delete removes the selected box", len(stored(s, first)["annotations"]) == count - 1)
    await s.press("Ctrl+z")
    await saved(s)
    s.check("undo brings the deleted box back", len(stored(s, first)["annotations"]) == count)

    await s.say("Change the class of a box with the number keys")
    await s.press("v")
    await s.click("svg.overlay .shape rect")  # the first box
    await s.press("2")
    await saved(s)
    s.check("pressing 2 changed the selected box to the second class",
            stored(s, first)["annotations"][0]["class_id"] == bus)

    await s.shot("a3_edited")
