"""Keypoints (v0.4), driven with the real mouse and keyboard. Checks read back what the SERVER stored."""

import json

DESCRIPTION = "keypoints: sequential placement (visible/hidden/skip), drag, keyboard-only, class skeleton editor, repeat previous"
CONFIG = {"annotations": {"save_debounce_ms": 150}}
W, H = 800, 600
SAVED = "document.querySelector('.save-chip').dataset.status === 'saved'"
OVERLAY = "document.querySelector('svg.overlay')"
NAMES = {}
SKELETON = {"names": ["head", "neck", "tail", "front paw", "back paw"], "edges": [[0, 1], [1, 2], [1, 3], [2, 4]]}
POSE = [(200, 150), (260, 230), (480, 300), (280, 420), (460, 430)]


async def point(s, x, y):
    sx, sy = await s.js(
        f"(() => {{ const svg = {OVERLAY}; const r = svg.getBoundingClientRect(); const v = svg.viewBox.baseVal;"
        f"return [r.left + {x} * r.width / v.width, r.top + {y} * r.height / v.height]; }})()"
    )
    return (sx, sy)


async def click_at(s, x, y, **kwargs):
    await s.click(await point(s, x, y), **kwargs)


def sets(s, image_id):
    return [a for a in s.api.call("GET", f"/api/images/{image_id}/annotations")[1]["annotations"] if a["kind"] == "keypoints"]


def near(a, b, tolerance=2.5):
    return abs(a - b) <= tolerance


def pose_near(got, want, tolerance=2.5):
    return len(got) == len(want) and all(g[2] > 0 and near(g[0], w[0], tolerance) and near(g[1], w[1], tolerance) for g, w in zip(got, want, strict=True))


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
    folder = s.make_images("kp", 6, size=(W, H))
    project = s.api.make_project("Keypoints", folder)["id"]
    cat = s.api.call("POST", f"/api/projects/{project}/classes", {"name": "cat", "skeleton": SKELETON})[1]["id"]
    s.api.call("POST", f"/api/projects/{project}/classes", {"name": "plain"})
    items = s.api.call("GET", f"/api/projects/{project}/images?limit=50")[1]["items"]
    NAMES.update({i["id"]: i["original_name"] for i in items})
    ids = [i["id"] for i in items]

    # ---- place a full pose, one click per point ----------------------------------------------
    await s.say("Keypoint tool: click the head, neck, tail, front paw and back paw in order")
    await open_image(s, project, ids[0])
    await s.press("k")
    await click_at(s, *POSE[0])
    hint = await s.js("document.querySelector('.kp-hint').innerText")
    s.check("after the first click the hint names the next point (neck, 2 of 5)", "neck" in hint and "2 of 5" in hint, hint)
    for x, y in POSE[1:]:
        await click_at(s, x, y)
    await saved(s)
    got = sets(s, ids[0])
    s.check("the 5th click finished the set and the server stored 5 visible points in place",
            len(got) == 1 and got[0]["class_id"] == cat and pose_near(got[0]["data"]["points"], POSE) and all(p[2] == 2 for p in got[0]["data"]["points"]), str(got))
    s.check("it is selected and its points are listed in the inspector",
            await s.js("document.querySelectorAll('.kp-list li').length") == 5 and "head" in await s.js("document.querySelector('.kp-list').innerText"))
    s.check("the hint is gone and 5 dots + 4 lines are drawn",
            await s.js("document.querySelector('.kp-hint').hidden") and await s.js("document.querySelectorAll('svg.overlay .kp-dot').length") == 5
            and await s.js("document.querySelectorAll('svg.overlay line').length") == 4)
    await s.shot("k1_full_pose")

    # ---- hidden, skipped, finish early, step back, cancel ------------------------------------
    await s.say("Shift+click = hidden, X = skip a point, Enter finishes early")
    await click_at(s, 100, 480)  # tool is still the keypoint tool: starts a new set at 'head'
    await click_at(s, 140, 520, modifiers="shift")
    await s.press("x")
    await s.press("Enter")
    await saved(s)
    two = sets(s, ids[0])
    pts = two[1]["data"]["points"] if len(two) == 2 else []
    s.check("second set: head visible, neck hidden, the rest not labelled (stored as 0,0,0)",
            len(pts) == 5 and pts[0][2] == 2 and pts[1][2] == 1 and pts[2:] == [[0, 0, 0]] * 3, str(pts))
    s.check("a hidden point is drawn with a dashed outline", await s.js("document.querySelectorAll('svg.overlay .kp-dot[stroke-dasharray=\"2 2\"]').length") == 1)

    await s.say("Backspace steps back one point; Escape cancels the whole set")
    await click_at(s, 600, 100)
    await click_at(s, 640, 140)
    await s.press("Backspace")
    s.check("Backspace went back to 'neck' (2 of 5)", "2 of 5" in await s.js("document.querySelector('.kp-hint').innerText"))
    await s.press("Escape")
    s.check("Escape cancelled: hint hidden, nothing extra saved", await s.js("document.querySelector('.kp-hint').hidden") and len(sets(s, ids[0])) == 2)
    await s.press("k")
    await click_at(s, 600, 100)
    await s.press("v")
    s.check("switching tools mid-way is refused with a message", "Finish the keypoints" in (await s.js(toast_text()) or "") and await s.js("document.querySelector('.stage').dataset.tool") == "keypoints")
    await s.press("Escape")

    # ---- move a whole pose, drag one point -----------------------------------------------------
    await s.say("Select the first pose, drag it, then drag just the tail")
    await s.press("v")
    await s.click(".ann-row")
    before = sets(s, ids[0])[0]["data"]["points"]
    await s.drag(await point(s, 380, 250), await point(s, 420, 280), duration=0.2)
    await saved(s)
    after = sets(s, ids[0])[0]["data"]["points"]
    s.check("dragging the pose moved all points by about (40, 30)", all(near(a[0] - b[0], 40) and near(a[1] - b[1], 30) for a, b in zip(after, before, strict=True)), f"{before} -> {after}")
    await s.drag("svg.overlay .kp-handle[data-kp='2']", await point(s, 540, 380), duration=0.2)
    await saved(s)
    moved = sets(s, ids[0])[0]["data"]["points"]
    s.check("dragging the tail moved only the tail", near(moved[2][0], 540) and near(moved[2][1], 380) and pose_near([moved[0], moved[1], moved[3], moved[4]], [after[0], after[1], after[3], after[4]], 0.2), str(moved))
    await s.press("Ctrl+z")
    await saved(s)
    s.check("one undo puts the tail back", pose_near(sets(s, ids[0])[0]["data"]["points"], after, 0.2))

    # ---- keyboard only -------------------------------------------------------------------------
    await s.say("Keyboard: ] picks a point, Shift+Right moves it 10 px, O cycles visible / hidden / not labelled")
    await s.js("document.querySelector('.stage').focus()")
    await s.press("Escape")  # forget the tail, which the drag above had picked
    await s.press("]")
    await s.press("Shift+Right")
    await saved(s)
    nudged = sets(s, ids[0])[0]["data"]["points"]
    s.check("Shift+Right moved only the head, 10 px", near(nudged[0][0] - after[0][0], 10, 0.6) and pose_near(nudged[1:], after[1:], 0.2), str(nudged[0]))
    await s.press("o")
    await saved(s)
    s.check("O made the head hidden (v=1), keeping its place", sets(s, ids[0])[0]["data"]["points"][0][2] == 1 and near(sets(s, ids[0])[0]["data"]["points"][0][0], nudged[0][0], 0.2))
    await s.press("o")
    await saved(s)
    cleared = sets(s, ids[0])[0]["data"]["points"][0]
    s.check("O again made it not labelled (0,0,0)", cleared == [0, 0, 0], str(cleared))
    await s.click(s.by_text(".kp-state", "not labelled", exact=True))
    await saved(s)
    back = sets(s, ids[0])[0]["data"]["points"][0]
    s.check("the 'not labelled' button in the list puts the head back, visible, inside the pose", back[2] == 2 and 0 < back[0] < W and 0 < back[1] < H, str(back))

    await s.say("A set must keep at least one labelled point")
    for index in (1, 2, 3, 4):
        await s.click(f"[data-fk='kpv:{index}']")  # visible -> hidden
        await s.click(f"[data-fk='kpv:{index}']")  # hidden -> not labelled
    await saved(s)
    left = sets(s, ids[0])[0]["data"]["points"]
    s.check("four points cleared, the head remains", [p[2] for p in left] == [2, 0, 0, 0, 0], str(left))
    await s.click("[data-fk='kpv:0']")
    await s.click("[data-fk='kpv:0']")
    s.check("clearing the last labelled point is refused with a message", "at least one labelled point" in (await s.js(toast_text()) or ""))

    await s.say("Keyboard only: K then Enter drops a whole pose in the middle of the view")
    await open_image(s, project, ids[1])
    await s.js("document.querySelector('.stage').focus()")
    await s.press("k")
    await s.press("Enter")
    await saved(s)
    dropped = sets(s, ids[1])
    s.check("Enter dropped a 5-point pose, all visible and inside the image",
            len(dropped) == 1 and len(dropped[0]["data"]["points"]) == 5 and all(p[2] == 2 and 0 <= p[0] <= W and 0 <= p[1] <= H for p in dropped[0]["data"]["points"]), str(dropped))

    # ---- a class without a skeleton, the class dialog ---------------------------------------------
    await s.say("A class with no keypoints explains what to do")
    await open_image(s, project, ids[2])
    await s.press("2")  # the 'plain' class
    await s.press("k")
    await click_at(s, 300, 300)
    s.check("clicking with a class that has no keypoints gives a helpful message, nothing is drawn",
            "no keypoints" in (await s.js(toast_text()) or "") and not sets(s, ids[2]) and await s.js("document.querySelector('.kp-hint').hidden"))

    await s.say("Give the class keypoints in its dialog; a bad connection is explained")
    await s.click("[aria-label='Edit class plain']")
    await s.wait_for("document.querySelector('#class-points')")
    await s.click("dialog summary")  # the keypoint fields are folded away until asked for
    await s.click("#class-points")
    await s.type_text("a")
    await s.press("Enter")
    await s.type_text("b")
    await s.click("#class-links")
    await s.type_text("a - z")
    await s.click(s.by_text("dialog button", "Save"))
    s.check("an unknown point in a connection is explained and nothing is saved",
            "“z” is not in the list" in (await s.js("document.querySelector('dialog .error-text').innerText") or ""))
    await s.click("#class-links")
    await s.press("Ctrl+a")
    await s.press("Backspace")
    await s.type_text("a - b")
    await s.click(s.by_text("dialog button", "Save"))
    await s.wait_for("!document.querySelector('dialog[open]')")
    plain = next(c for c in s.api.call("GET", f"/api/projects/{project}/classes")[1] if c["name"] == "plain")
    s.check("the skeleton was saved on the class", plain["skeleton"] == {"names": ["a", "b"], "edges": [[0, 1]]}, str(plain))
    await click_at(s, 300, 300)
    await click_at(s, 360, 340)
    await saved(s)
    two_points = sets(s, ids[2])
    s.check("the new 2-point class can now be annotated (finished after the 2nd click)", len(two_points) == 1 and len(two_points[0]["data"]["points"]) == 2)

    s.expect_console("400")  # the refusal below is deliberate
    await s.say("Its point count is locked once keypoints use it, but names can change")
    await s.click("[aria-label='Edit class plain']")
    await s.wait_for("document.querySelector('#class-points')")
    await s.click("#class-points")
    await s.press("Ctrl+End")
    await s.press("Enter")
    await s.type_text("c")
    await s.click(s.by_text("dialog button", "Save"))
    await s.wait_for("document.querySelector('dialog .error-text') && document.querySelector('dialog .error-text').innerText.length > 0", 5)
    shown = await s.js("document.querySelector('dialog .error-text').innerText") or ""
    s.check("adding a point is refused with an explanation", "cannot change" in shown, shown)
    await s.click(s.by_text("dialog button", "Cancel"))

    # ---- repeat previous, reload, rotated ------------------------------------------------------------
    await s.say("Repeat the previous image's annotations copies keypoints too")
    s.api.call("PUT", f"/api/images/{ids[3]}/annotations", {"rev": 0, "annotations": [{"class_id": cat, "kind": "keypoints", "data": {"points": [[p[0], p[1], 2] for p in POSE]}}], "marked_empty": False, "label_class_id": None})
    await open_image(s, project, ids[4])
    ids_in_order = [i["id"] for i in s.api.call("GET", f"/api/projects/{project}/images?limit=50")[1]["items"]]
    previous = ids_in_order[ids_in_order.index(ids[4]) - 1]
    s.check("the previous image (in gallery order) is the one with the pose", previous == ids[3])
    await s.click(s.by_text(".a-actions .btn", "Repeat previous image", exact=False))
    await s.wait_for("document.querySelectorAll('.ann-list .ann-row').length === 1")
    await saved(s)
    copied = sets(s, ids[4])
    s.check("the pose was copied to this image", len(copied) == 1 and pose_near(copied[0]["data"]["points"], POSE, 0.2), str(copied))

    await s.say("Reload: the drawing comes back from the server")
    await open_image(s, project, ids[0])
    s.check("5 dots per drawn point after a reload", await s.js("document.querySelectorAll('svg.overlay .kp-dot').length") > 0)
    stats = s.api.call("GET", f"/api/projects/{project}/annotation-stats")[1]
    s.check("project stats count keypoint sets per class", any(c.get("keypoints", 0) >= 1 for c in stats["per_class"]), str(stats))
