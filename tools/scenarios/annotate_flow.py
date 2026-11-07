"""The annotator's workflow features, with real input (v0.2): classes, labels, 'no objects',
navigation, repeat-previous, keyboard-only drawing, zoom/pan accuracy, EXIF rotation, draft
recovery, leaving mid-edit and save conflicts. Checks look at what the SERVER stored."""

import json

from PIL import Image

DESCRIPTION = "annotator workflow: labels, no objects, navigation, keyboard-only, zoom/pan, EXIF, recovery, conflicts"
CONFIG = {"annotations": {"save_debounce_ms": 150}}

SAVED = "document.querySelector('.save-chip') && document.querySelector('.save-chip').dataset.status === 'saved'"
OVERLAY = "document.querySelector('svg.overlay')"


async def point(s, x, y):
    script = (
        f"(() => {{ const svg = {OVERLAY}; const r = svg.getBoundingClientRect(); const v = svg.viewBox.baseVal;"
        f"return [r.left + {x} * r.width / v.width, r.top + {y} * r.height / v.height]; }})()"
    )
    sx, sy = await s.js(script)
    return (sx, sy)


async def draw(s, x0, y0, x1, y1):
    await s.drag(await point(s, x0, y0), await point(s, x1, y1), duration=0.2)


def annotations(s, image_id):
    return s.api.call("GET", f"/api/images/{image_id}/annotations")[1]


def near(a, b, tolerance=3.0):
    return abs(a - b) <= tolerance


NAMES = {}  # image id -> file name, filled in run()


async def arrive(s, project, image_id):
    """Wait until the annotator for `image_id` is fully mounted (so key presses are not dropped).

    The title check matters: between the URL changing and the new page mounting, the OLD page's
    elements are still there, so 'hash changed' alone is not proof that the new image is ready."""
    await s.wait_for(f"location.hash === '#/projects/{project}/annotate/{image_id}'")
    name = json.dumps(NAMES[image_id])
    await s.wait_for(f"{OVERLAY} && document.querySelector('.a-title') && document.querySelector('.a-title').textContent === {name} "
                     "&& document.querySelector('.photo').complete")


async def open_image(s, project, image_id):
    await s.goto(f"/#/projects/{project}/annotate/{image_id}")
    await arrive(s, project, image_id)


async def run(s):
    folder = s.make_images("pics", 8, size=(800, 600))
    rotated = folder / "rotated.jpg"  # the file is 800x600 but EXIF says rotate 90: it DISPLAYS as 600x800
    exif = Image.Exif()
    exif[0x0112] = 6
    Image.new("RGB", (800, 600), (200, 40, 40)).save(rotated, exif=exif)
    project = s.api.make_project("Flow", folder)["id"]
    car = s.api.call("POST", f"/api/projects/{project}/classes", {"name": "car"})[1]["id"]
    s.api.call("POST", f"/api/projects/{project}/classes", {"name": "bus"})
    items = s.api.call("GET", f"/api/projects/{project}/images?limit=50")[1]["items"]
    ids = [i["id"] for i in items]
    NAMES.update({i["id"]: i["original_name"] for i in items})
    rotated_id = next(i["id"] for i in items if i["original_name"] == "rotated.jpg")
    plain = [i for i in ids if i != rotated_id]

    # ---- classes from the UI ---------------------------------------------------------------
    await s.say("A project with no classes: drawing asks you to add one")
    empty_project = s.api.make_project("No classes yet", s.make_images("p2", 2))["id"]
    first_item = s.api.call("GET", f"/api/projects/{empty_project}/images")[1]["items"][0]
    first_of_empty = first_item["id"]
    NAMES[first_of_empty] = first_item["original_name"]
    await open_image(s, empty_project, first_of_empty)
    await s.press("b")
    await s.drag(await point(s, 100, 100), await point(s, 200, 200), duration=0.2)
    await s.wait_for("document.getElementById('class-name')")
    s.check("drawing without a class opens the new-class dialog", True)
    await s.type_text("pallet")
    await s.click(s.by_text("dialog .btn", "Add class"))
    await s.wait_for("document.querySelectorAll('.class-row').length === 1")
    await s.drag(await point(s, 100, 100), await point(s, 200, 200), duration=0.2)
    await s.wait_for(SAVED)
    got = annotations(s, first_of_empty)["annotations"]
    s.check("after adding the class, the box is drawn with it", len(got) == 1 and near(got[0]["data"]["w"], 100), str(got))

    await s.say("Delete a used class from the UI (it asks first)")
    await s.click(".class-row + .btn")  # the pencil next to the class
    await s.wait_for("document.getElementById('class-name')")
    await s.click(s.by_text("dialog .btn", "Delete class…"))
    await s.wait_for("document.querySelectorAll('dialog').length >= 1 && document.body.innerText.includes('cannot be undone')")
    await s.shot("f0_delete_class_confirm")
    await s.click(s.by_text("dialog .btn", "Delete class and 1 annotation", exact=False))
    await s.wait_for("document.querySelectorAll('.class-row').length === 0")
    s.check("deleting the class removed its box on the server and in the view",
            annotations(s, first_of_empty)["annotations"] == [] and await s.js("document.querySelectorAll('.ann-row').length") == 0)

    # ---- image label, no objects -----------------------------------------------------------
    await s.say("Single-label classification: Shift+1 labels the whole image")
    await open_image(s, project, plain[0])
    await s.press("Shift+1")
    await s.wait_for(SAVED)
    s.check("Shift+1 stored the first class as the image label", annotations(s, plain[0])["label_class_id"] == car)
    await s.press("Shift+1")
    await s.wait_for(SAVED)
    s.check("Shift+1 again clears the label", annotations(s, plain[0])["label_class_id"] is None)

    await s.say("Explicit 'no objects' with E")
    await s.press("e")
    await s.wait_for(SAVED)
    s.check("E marked the image as having no objects", annotations(s, plain[0])["marked_empty"] is True)
    await s.press("b")
    await draw(s, 50, 50, 150, 120)
    await s.wait_for(SAVED)
    state = annotations(s, plain[0])
    s.check("drawing a box clears the 'no objects' mark", state["marked_empty"] is False and len(state["annotations"]) == 1)
    await s.press("e")
    await s.pause(0.3)
    s.check("E on an image with boxes is refused with a message",
            "Delete them first" in (await s.js("document.getElementById('toasts').innerText") or "")
            and annotations(s, plain[0])["marked_empty"] is False)

    # ---- navigation ------------------------------------------------------------------------
    await s.say("Navigate: D next, A previous, N next unlabelled - and drawing right before moving is saved")
    await s.press("v")
    await draw(s, 300, 300, 400, 400)  # (select tool: this only rubber-bands nothing) -> no box expected
    await s.press("b")
    await draw(s, 300, 300, 400, 400)
    await s.press("d")  # leave immediately, without waiting for the debounce
    await arrive(s, project, plain[1])
    s.check("D opened the next image", await s.js("document.querySelector('.a-title').textContent") == items[1]["original_name"])
    await s.pause(0.5)
    s.check("the box drawn just before leaving was saved on the previous image", len(annotations(s, plain[0])["annotations"]) == 2)
    await s.press("a")
    await arrive(s, project, plain[0])
    await s.press("n")
    await arrive(s, project, plain[1])
    s.check("N skipped the labelled image and opened the next unlabelled one",
            await s.js("location.hash") == f"#/projects/{project}/annotate/{plain[1]}")

    # ---- repeat previous, keyboard-only drawing ---------------------------------------------
    await s.say("Repeat the previous image's boxes")
    await s.click(s.by_text(".a-actions .btn", "Repeat previous image", exact=False))
    await s.wait_for("document.querySelectorAll('.ann-row').length === 2")  # the copy arrived...
    await s.wait_for(SAVED)  # ...and has been saved (status is 'dirty' from the moment of the edit)
    s.check("the previous image's 2 boxes were copied and saved", len(annotations(s, plain[1])["annotations"]) == 2)

    await s.say("Keyboard only: B, Enter drops a box; arrows move it; Alt+arrows resize it")
    await open_image(s, project, plain[2])
    await s.js("document.querySelector('.stage').focus()")
    await s.press("b")
    await s.press("Enter")
    await s.wait_for(SAVED)
    box = annotations(s, plain[2])["annotations"]
    s.check("Enter created one default box in the middle of the view", len(box) == 1 and 100 < box[0]["data"]["w"] < 600, str(box))
    start = box[0]["data"]
    await s.press("Shift+Right")
    await s.press("Alt+Down")
    await s.wait_for(SAVED)
    moved = annotations(s, plain[2])["annotations"][0]["data"]
    s.check("arrows moved it 10 px right and Alt+Down made it 1 px taller",
            near(moved["x"] - start["x"], 10, 0.6) and near(moved["h"] - start["h"], 1, 0.6), f"{start} -> {moved}")
    await s.press("Tab")
    await s.pause(0.2)
    s.check("Tab with the canvas focused moves through annotations", await s.js("document.querySelectorAll('.ann-row[aria-pressed=true]').length") == 1)

    # ---- zoom and pan accuracy -------------------------------------------------------------
    await s.say("Zoom in with the wheel, pan with Space-drag, and draw: the box must land where the pointer was")
    await open_image(s, project, plain[3])
    await s.wheel(await point(s, 400, 300), -360)
    await s.pause(0.2)
    zoom = await s.js("document.querySelector('.hud').textContent")
    s.check("the wheel zoomed in", int(zoom.split("%")[0]) > 100, zoom)
    before = await s.js(f"{OVERLAY}.getBoundingClientRect().left")
    await s.js("document.querySelector('.stage').focus()")
    await s.send("Input.dispatchKeyEvent", type="keyDown", key=" ", code="Space", windowsVirtualKeyCode=32, text=" ")
    await s.drag(await point(s, 400, 300), (500.0, 420.0), duration=0.2)
    await s.send("Input.dispatchKeyEvent", type="keyUp", key=" ", code="Space", windowsVirtualKeyCode=32)
    after = await s.js(f"{OVERLAY}.getBoundingClientRect().left")
    s.check("Space-drag panned the image", abs(after - before) > 20, f"{before} -> {after}")
    await s.press("b")
    sx0, sy0 = 700.0, 400.0
    sx1, sy1 = 900.0, 520.0
    await s.drag((sx0, sy0), (sx1, sy1), duration=0.2)
    await s.wait_for(SAVED)
    drawn = await s.js("(() => { const r = [...document.querySelectorAll('svg.overlay .shape rect')].pop().getBoundingClientRect(); return [r.left, r.top, r.right, r.bottom]; })()")
    s.check("the drawn box sits under the pointer's drag (within 2 px) at this zoom/pan",
            all(abs(a - b) <= 2.5 for a, b in zip(drawn, [sx0, sy0, sx1, sy1], strict=True)), f"{drawn} vs {[sx0, sy0, sx1, sy1]}")
    stored_box = annotations(s, plain[3])["annotations"][0]["data"]
    p0 = await point(s, stored_box["x"], stored_box["y"])
    s.check("the stored coordinates map back to the same screen spot", abs(p0[0] - sx0) <= 2.5 and abs(p0[1] - sy0) <= 2.5, str(stored_box))
    await s.press("0")

    # ---- EXIF-rotated image ----------------------------------------------------------------
    await s.say("An EXIF-rotated photo must line up (it displays as 600 x 800)")
    await open_image(s, project, rotated_id)
    dims = await s.js(f"[{OVERLAY}.viewBox.baseVal.width, {OVERLAY}.viewBox.baseVal.height, document.querySelector('.photo').naturalWidth, document.querySelector('.photo').naturalHeight]")
    s.check("overlay and photo both use the rotated size 600 x 800", dims == [600, 800, 600, 800], str(dims))
    await s.press("b")
    s.check("the toast area does not block clicks on the canvas",
            await s.js("(() => { const t = document.getElementById('toasts'); const r = t.getBoundingClientRect();"
                       "const hit = document.elementFromPoint(r.left + 4, r.top + 4); return !hit || hit.id !== 'toasts'; })()"))
    await draw(s, 100, 650, 500, 780)  # low on the tall image: only valid if the oriented height (800) is used
    await s.wait_for(SAVED)
    got = annotations(s, rotated_id)["annotations"]
    s.check("a box low on the rotated image was accepted and stored", len(got) == 1 and near(got[0]["data"]["y"], 650) and near(got[0]["data"]["h"], 130), str(got))

    # ---- draft recovery --------------------------------------------------------------------
    await s.say("Unsaved changes from an earlier session are offered back")
    target = plain[4]
    rev = annotations(s, target)["rev"]
    draft = {"baseRev": rev, "at": 0, "payload": {"annotations": [{"class_id": car, "kind": "box", "data": {"x": 30, "y": 30, "w": 90, "h": 60}}], "marked_empty": False, "label_class_id": None}}
    await s.goto("/#/projects")
    await s.js(f"localStorage.setItem('studio.draft.{target}', {json.dumps(json.dumps(draft))})")
    await open_image(s, project, target)
    await s.wait_for("document.querySelector('.a-banner') && !document.querySelector('.a-banner').hidden")
    await s.shot("f1_draft_banner")
    s.check("a banner offers the unsaved changes", "unsaved changes" in (await s.js("document.querySelector('.a-banner').innerText")))
    await s.click(s.by_text(".a-banner .btn", "Restore them"))
    await s.wait_for(SAVED)
    got = annotations(s, target)["annotations"]
    s.check("restoring applied the draft and saved it", len(got) == 1 and near(got[0]["data"]["w"], 90), str(got))
    s.check("the draft was removed after saving", await s.js(f"localStorage.getItem('studio.draft.{target}')") is None)

    # ---- closing the page right after an edit -----------------------------------------------
    await s.say("Close the page immediately after drawing")
    target = plain[5]
    await open_image(s, project, target)
    await s.press("b")
    await draw(s, 200, 200, 330, 300)
    await s.send("Page.navigate", url="about:blank")  # leaves before the debounce could have fired
    await s.pause(0.1)
    await s.wait_for("true", 1)
    import asyncio
    await asyncio.sleep(1.0)
    s.check("the box was not lost when the page was left", len(annotations(s, target)["annotations"]) == 1)

    # ---- save conflicts --------------------------------------------------------------------
    await s.say("Someone else changes the image while it is open: the editor must not overwrite silently")
    target = plain[6]
    await open_image(s, project, target)
    rev = annotations(s, target)["rev"]
    other = [{"class_id": car, "kind": "box", "data": {"x": 5, "y": 5, "w": 50, "h": 50}}]
    s.api.call("PUT", f"/api/images/{target}/annotations", {"rev": rev, "annotations": other, "marked_empty": False, "label_class_id": None})
    await s.press("b")
    await draw(s, 300, 300, 420, 380)
    await s.wait_for("document.querySelector('.save-chip').dataset.status === 'conflict'")
    await s.shot("f2_conflict")
    s.check("a conflict banner is shown instead of overwriting",
            "somewhere else" in (await s.js("document.querySelector('.a-banner').innerText")))
    s.check("meanwhile the other change is intact on the server", len(annotations(s, target)["annotations"]) == 1)
    await s.click(s.by_text(".a-banner .btn", "Keep my version"))
    await s.wait_for(SAVED)
    s.check("Keep my version saved the local boxes", len(annotations(s, target)["annotations"]) == 1
            and near(annotations(s, target)["annotations"][0]["data"]["x"], 300))
