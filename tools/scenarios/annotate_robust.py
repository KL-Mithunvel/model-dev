"""Regression checks for the v0.2 independent review: saving while the page is hidden, the
annotation limit, refused saves, discarded drafts, a stuck Space key, accessibility structure,
long class names, and shortcut hygiene. Each check reproduces what the reviewer found."""

import asyncio
import json

DESCRIPTION = "annotator robustness: hide-while-saving, limits, refused saves, drafts, stuck keys, a11y, layout"
# a long debounce so "the page is hidden within the debounce window" is easy to hit; a tiny limit for the cap test
CONFIG = {"annotations": {"save_debounce_ms": 1200, "max_per_image": 3}}

SAVED = "document.querySelector('.save-chip').dataset.status === 'saved'"
OVERLAY = "document.querySelector('svg.overlay')"
NAMES = {}


async def point(s, x, y):
    sx, sy = await s.js(
        f"(() => {{ const svg = {OVERLAY}; const r = svg.getBoundingClientRect(); const v = svg.viewBox.baseVal;"
        f"return [r.left + {x} * r.width / v.width, r.top + {y} * r.height / v.height]; }})()"
    )
    return (sx, sy)


async def draw(s, x0, y0, x1, y1):
    await s.drag(await point(s, x0, y0), await point(s, x1, y1), duration=0.2)


def stored(s, image_id):
    return s.api.call("GET", f"/api/images/{image_id}/annotations")[1]


async def open_image(s, project, image_id):
    await s.goto(f"/#/projects/{project}/annotate/{image_id}")
    name = json.dumps(NAMES[image_id])
    await s.wait_for(f"{OVERLAY} && document.querySelector('.a-title') && document.querySelector('.a-title').textContent === {name}"
                     " && document.querySelector('.photo').complete")


async def set_visibility(s, state):
    """Pretend the browser tab was hidden/shown (what switching tabs or locking the screen does)."""
    await s.js(f"Object.defineProperty(document, 'visibilityState', {{ value: '{state}', configurable: true }});"
               "document.dispatchEvent(new Event('visibilitychange'))")


async def run(s):
    project = s.api.make_project("Robust", s.make_images("r", 6))["id"]
    car = s.api.call("POST", f"/api/projects/{project}/classes", {"name": "car"})[1]["id"]
    items = s.api.call("GET", f"/api/projects/{project}/images?limit=20")[1]["items"]
    ids = [i["id"] for i in items]
    NAMES.update({i["id"]: i["original_name"] for i in items})

    # ---- B1: the page is hidden right after an edit ----------------------------------------------
    await s.say("Draw, then hide the tab inside the autosave delay (Alt+Tab, lock screen)")
    await open_image(s, project, ids[0])
    await s.press("b")
    await draw(s, 100, 100, 220, 180)
    await set_visibility(s, "hidden")
    await asyncio.sleep(1.8)  # longer than the autosave delay: the old code sent a second, stale request
    await set_visibility(s, "visible")
    s.check("hiding the page saved the edit exactly once: no false 'changed elsewhere' conflict",
            await s.js("document.querySelector('.save-chip').dataset.status") == "saved"
            and await s.js("document.querySelector('.a-banner').hidden"))
    s.check("the box is on the server", len(stored(s, ids[0])["annotations"]) == 1)
    await draw(s, 300, 100, 420, 180)
    await s.wait_for(SAVED, 10)
    s.check("a second box drawn after that is also saved (saving was not stopped)",
            len(stored(s, ids[0])["annotations"]) == 2)
    s.check("and the local draft was cleared", await s.js(f"localStorage.getItem('studio.draft.{ids[0]}')") is None)

    # ---- S1: the annotation limit ----------------------------------------------------------------
    await s.say("The 4th box on an image is refused with a clear message (limit is 3 here)")
    await open_image(s, project, ids[1])
    await s.press("b")
    for i in range(3):
        await draw(s, 40 + i * 140, 300, 140 + i * 140, 380)
    await draw(s, 40, 450, 140, 520)
    await s.pause(0.3)
    toast = await s.js("document.getElementById('toasts').innerText") or ""
    s.check("a toast explains the limit", "at most 3 annotations" in toast, toast)
    s.check("the page shows 3 annotations, not 4", await s.js("document.querySelectorAll('.ann-row').length") == 3)
    await s.wait_for(SAVED, 10)
    s.check("the chip is not stuck on 'retrying' and the server holds 3",
            await s.js("document.querySelector('.save-chip').dataset.status") == "saved" and len(stored(s, ids[1])["annotations"]) == 3)

    # ---- S2: the server refuses the content (class deleted elsewhere) ------------------------------
    await s.say("A class is deleted in another tab while a box of that class is still unsaved")
    s.expect_console("status of 400")  # the server refuses the box on purpose in this step
    temp = s.api.call("POST", f"/api/projects/{project}/classes", {"name": "temp"})[1]["id"]
    await open_image(s, project, ids[2])
    await s.press("2")  # active class = temp
    await s.press("b")
    await draw(s, 100, 100, 220, 180)
    s.api.call("DELETE", f"/api/classes/{temp}?force=true")  # before the 1.2 s autosave fires
    await s.wait_for("document.querySelector('.save-chip').dataset.status === 'rejected'", 10)
    banner = await s.js("document.querySelector('.a-banner').innerText")
    s.check("the refusal is explained instead of retrying forever", "did not accept" in banner, banner)
    await s.shot("r1_rejected_banner")
    await s.click(s.by_text(".a-banner .btn", "Remove annotations that no longer fit"))
    await s.wait_for(SAVED, 10)
    s.check("removing the invalid box lets saving succeed and clears the banner",
            await s.js("document.querySelector('.a-banner').hidden") and stored(s, ids[2])["annotations"] == [])

    # ---- S3: 'Load the latest version' must discard the local draft --------------------------------
    await s.say("Conflict -> Load the latest version: the stale draft must not come back")
    await open_image(s, project, ids[3])
    rev = stored(s, ids[3])["rev"]
    s.api.call("PUT", f"/api/images/{ids[3]}/annotations", {"rev": rev, "annotations": [{"class_id": car, "kind": "box", "data": {"x": 5, "y": 5, "w": 40, "h": 40}}], "marked_empty": False, "label_class_id": None})
    await s.press("b")
    await draw(s, 300, 300, 420, 380)
    await s.wait_for("document.querySelector('.save-chip').dataset.status === 'conflict'", 10)
    await s.click(s.by_text(".a-banner .btn", "Load the latest version"))
    await s.pause(0.5)
    s.check("the draft is gone after choosing the server's version", await s.js(f"localStorage.getItem('studio.draft.{ids[3]}')") is None)
    await open_image(s, project, ids[3])
    await s.pause(0.3)
    s.check("reopening the image does not offer the discarded edits again", await s.js("document.querySelector('.a-banner').hidden"))

    # ---- S4: a held Space must not stay held when the window loses focus ------------------------------
    await s.say("Hold Space, lose window focus: the next drag must draw, not pan")
    await open_image(s, project, ids[4])
    await s.js("document.querySelector('.stage').focus()")
    await s.send("Input.dispatchKeyEvent", type="keyDown", key=" ", code="Space", windowsVirtualKeyCode=32, text=" ")
    s.check("Space-pan is on while Space is held", await s.js("document.querySelector('.stage').classList.contains('space-pan')"))
    await s.js("window.dispatchEvent(new Event('blur'))")
    s.check("window blur releases it", not await s.js("document.querySelector('.stage').classList.contains('space-pan')"))
    await s.press("b")
    await draw(s, 100, 100, 220, 180)
    await s.wait_for(SAVED, 10)
    s.check("so the next drag draws a box", len(stored(s, ids[4])["annotations"]) == 1)

    # ---- S7/S8: structure, one tab stop, long names -------------------------------------------------
    await s.say("Accessibility structure and a very long class name")
    long_name = "x" * 80
    s.api.call("POST", f"/api/projects/{project}/classes", {"name": long_name})
    await open_image(s, project, ids[5])
    s.check("filmstrip thumbnails are buttons inside list items (not buttons pretending to be items)",
            await s.js("(() => { const items = [...document.querySelectorAll('.filmstrip [role=listitem]')];"
                       "return items.length > 0 && items.every(i => i.tagName === 'DIV' && i.querySelector('button.film-item'))"
                       " && !document.querySelector('button[role=listitem]'); })()"))
    s.check("the image-label group is ONE tab stop",
            await s.js("[...document.querySelectorAll('.radio-list [role=radio]')].filter(r => r.tabIndex === 0).length") == 1)
    first_label = await s.js("document.querySelector('.radio-list [role=radio]').focus(); 1")
    await s.press("Right")
    await s.wait_for(SAVED, 10)
    label = stored(s, ids[5])["label_class_id"]
    s.check("an arrow key moves between labels and selects (2nd class)", label is not None and label != car, f"{first_label}: {label}")
    s.check("a long class name does not widen the inspector",
            await s.js("(() => { const i = document.querySelector('.a-inspector'); return i.scrollWidth <= i.clientWidth + 1; })()"))
    await s.shot("r2_long_class_name")
    await s.click(".class-row + .btn")
    await s.wait_for("document.getElementById('class-name')")
    s.check("colour swatches are named by position, not by hex code",
            await s.js("[...document.querySelectorAll('.swatch')].every(b => /^Colour \\d+ of \\d+$/.test(b.getAttribute('aria-label')))"))
    s.check("the swatch group is one tab stop",
            await s.js("[...document.querySelectorAll('.swatches [role=radio]')].filter(r => r.tabIndex === 0).length") == 1)
    await s.press("Escape")

    # ---- shortcut hygiene ----------------------------------------------------------------------------
    await s.say("Alt+D must not change image, and Ctrl+S must not open the browser's Save dialog")
    before = await s.js("location.hash")
    await s.js("document.querySelector('.stage').focus()")
    await s.press("Alt+d")
    await s.pause(0.3)
    s.check("Alt+D does nothing", await s.js("location.hash") == before)
    await s.press("Ctrl+s")
    await s.pause(0.3)
    s.check("Ctrl+S says changes are saved automatically",
            "saved automatically" in (await s.js("document.getElementById('toasts').innerText") or ""))
