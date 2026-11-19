"""AI assist in the annotator with the demo backend (Stage 4): click to outline, describe objects,
confidence filter, accept / reject, undo, and "nothing is saved until you accept"."""

DESCRIPTION = "AI assist (demo backend): click-to-outline, text boxes, score filter, accept/reject/undo, nothing saved unaccepted"
CONFIG = {"ml": {"backends": ["fake"]}, "annotations": {"save_debounce_ms": 150}}

W, H = 800, 600
SAVED = "document.querySelector('.save-chip') && document.querySelector('.save-chip').dataset.status === 'saved'"
SUGGESTIONS = "document.querySelectorAll('.suggestion').length"


async def point(s, x, y):
    script = (
        "(() => { const o = document.querySelector('svg.overlay'); const r = o.getBoundingClientRect();"
        "const v = o.viewBox.baseVal;"
        f"return [r.left + {x} * r.width / v.width, r.top + {y} * r.height / v.height]; }})()"
    )
    sx, sy = await s.js(script)
    return (sx, sy)


def stored(s, image_id):
    return s.api.call("GET", f"/api/images/{image_id}/annotations")[1]["annotations"]


async def run(s):
    folder = s.make_images("pics", 2, size=(W, H))
    project = s.api.make_project("Assist", folder)["id"]
    pallet = s.api.call("POST", f"/api/projects/{project}/classes", {"name": "pallet"})[1]["id"]
    image = s.api.call("GET", f"/api/projects/{project}/images?limit=5")[1]["items"][0]["id"]

    await s.say("Open the annotator: the assist panel names the demo backend honestly")
    await s.goto(f"/#/projects/{project}/annotate/{image}")
    await s.wait_for("document.querySelector('[data-assist]') && document.querySelector('[data-assist]').innerText.includes('Demo backend')")
    s.check("the panel says the results are made up",
            "made up" in await s.js("document.querySelector('[data-assist]').innerText"))

    await s.say("Press M and click an object: an outline is SUGGESTED, not saved")
    await s.press("m")
    s.check("the AI assist tool is selected",
            await s.js("document.querySelector('.stage').dataset.tool") == "assist")
    await s.click(await point(s, 400, 300))
    await s.wait_for(f"{SUGGESTIONS} === 1")
    s.check("the suggestion is a dashed polygon",
            await s.js("document.querySelector('.suggestion polygon').getAttribute('stroke-dasharray')") is not None)
    await s.shot("assist_suggestion")
    s.check("nothing is stored yet", stored(s, image) == [])
    s.check("the annotation list is still empty",
            "Nothing drawn yet" in await s.js("document.querySelector('.a-inspector').innerText"))

    await s.say("Enter accepts it: now it is a real annotation and is saved")
    await s.press("Enter")
    await s.wait_for(f"{SUGGESTIONS} === 0")
    await s.wait_for(SAVED, 10)
    saved = stored(s, image)
    s.check("exactly one polygon of the class pallet was stored",
            len(saved) == 1 and saved[0]["kind"] == "polygon" and saved[0]["class_id"] == pallet, str(saved))

    await s.say("Clicking directly on a suggestion accepts it too")
    await s.click(await point(s, 200, 150))
    await s.wait_for(f"{SUGGESTIONS} === 1")
    await s.click(".suggestion polygon")
    await s.wait_for(f"{SUGGESTIONS} === 0")
    await s.wait_for(SAVED, 10)
    s.check("two annotations now", len(stored(s, image)) == 2)

    await s.say("Describe objects: boxes for each phrase, with a score filter")
    await s.click("[data-mode=text]")
    await s.click("#assist-text")
    await s.type_text("pallet, forklift")
    await s.click(s.by_text("[data-assist] button", "Find"))
    await s.wait_for("document.querySelectorAll('[data-suggestion]').length > 0")
    s.check("with the default 50% filter only the 4 confident boxes are listed",
            await s.js("document.querySelectorAll('[data-suggestion]').length") == 4
            and await s.js(f"{SUGGESTIONS}") == 4)
    s.check("the hidden ones are mentioned",
            "2 suggestions hidden" in await s.js("document.querySelector('[data-assist]').innerText"))
    await s.shot("assist_text")

    await s.say("Lower the filter to 0%: all 6 show; reject one")
    await s.js("(() => { const r = document.querySelector('#assist-score'); r.value = 0; r.dispatchEvent(new Event('input', {bubbles: true})); })()")
    await s.wait_for("document.querySelectorAll('[data-suggestion]').length === 6")
    await s.click("[data-suggestion] button[data-fk^='sug-reject']")
    await s.wait_for("document.querySelectorAll('[data-suggestion]').length === 5")

    await s.say("Accept all shown: forklift has no class, so it takes the active class")
    await s.click(s.by_text("[data-assist] button", "Accept 5 shown"))
    await s.wait_for(f"{SUGGESTIONS} === 0")
    await s.wait_for(SAVED, 10)
    saved = stored(s, image)
    s.check("5 boxes were added to the 2 polygons", len(saved) == 7 and sum(a["kind"] == "box" for a in saved) == 5, str(len(saved)))
    s.check("all of them have a valid class", all(a["class_id"] == pallet for a in saved))

    await s.say("One Undo removes the whole accepted batch")
    await s.click(".stage")
    await s.press("Ctrl+Z")
    await s.wait_for(SAVED, 10)
    s.check("undo took back all 5 boxes in one step", len(stored(s, image)) == 2, str(len(stored(s, image))))

    await s.say("Escape rejects suggestions without saving")
    await s.click("[data-mode=text]")
    await s.click(s.by_text("[data-assist] button", "Find"))
    await s.wait_for("document.querySelectorAll('[data-suggestion]').length > 0")
    await s.click(".stage")
    await s.press("Escape")
    await s.wait_for(f"{SUGGESTIONS} === 0")
    s.check("rejected suggestions were not saved", len(stored(s, image)) == 2)

    await s.say("Reload: only accepted work is there")
    await s.goto(f"/#/projects/{project}/annotate/{image}")
    await s.wait_for("document.querySelector('.a-inspector')")
    s.check("no suggestions survive a reload", await s.js(SUGGESTIONS) == 0)
    s.check("page shows no stray 'null' text", await s.js("!document.body.innerText.includes('null')"))
