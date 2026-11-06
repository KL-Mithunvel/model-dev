"""Regression checks for the web UI, using real mouse and keyboard input.

Add a check here whenever a UI bug is fixed (see docs/AGENTS.md, QA checklist)."""

import json

DESCRIPTION = "UI regression checks: skip link, focus, keyboard, filters, router, import cancel"
PAGE_SIZE = 20  # small, so "load more" is easy to trigger
CONFIG = {"gallery": {"default_page_size": PAGE_SIZE}}
CANCEL_IMAGES = 500


async def run(s):
    gallery_images = s.make_images("g", 70)
    cancel_images = s.make_images("c", CANCEL_IMAGES)
    project_a = s.api.make_project("Smoke A", gallery_images)["id"]
    project_b = s.api.make_project("Smoke B")["id"]
    tiles = "document.querySelectorAll('.tile')"

    await s.say("Open the gallery of a project with 70 images")
    await s.goto(f"/#/projects/{project_a}")
    await s.wait_for(f"{tiles}.length === {PAGE_SIZE}")
    s.check("page shows no stray 'null' text", await s.js("!document.body.innerText.includes('null')"))

    await s.say("Keyboard: the first Tab reaches the skip link, Enter uses it")
    await s.press("Tab")
    s.check("first Tab reaches the skip link", await s.js("document.activeElement.className.includes('skip')"))
    await s.press("Enter")
    await s.pause(0.4)
    s.check("skip link keeps the view and moves focus to main",
            await s.js(f"{tiles}.length") == PAGE_SIZE
            and await s.js("location.hash") == f"#/projects/{project_a}"
            and await s.js("document.activeElement.id") == "main")

    await s.say("Load more: focus must stay on the tile you were on")
    await s.click(f".tile[data-index='{PAGE_SIZE - 1}']")
    await s.press("Right")
    await s.wait_for(f"{tiles}.length === {PAGE_SIZE * 2}")
    s.check("load more appends tiles and keeps focus on the same tile",
            await s.js("document.activeElement.dataset.index") == str(PAGE_SIZE - 1))
    await s.press("Right")
    s.check("arrow keys continue from the focused tile",
            await s.js("document.activeElement.dataset.index") == str(PAGE_SIZE))

    await s.say("Inspector: choosing a split must not drop keyboard focus")
    await s.click(".tile[data-index='0']")
    await s.click(".inspector .seg button[data-value=train]")
    await s.wait_for("document.querySelectorAll('.tile .badge').length === 1")
    s.check("split button keeps focus after a click",
            await s.js("document.activeElement.dataset.value") == "train"
            and await s.js("document.activeElement.getAttribute('aria-pressed')") == "true")
    await s.press("Enter")
    s.check("split button keeps focus after Enter", await s.js("document.activeElement.dataset.value") == "train")

    await s.say("Space adds a tile to the selection instead of replacing it")
    await s.click(".tile[data-index='0']")
    await s.press("Right")
    await s.press("Space")
    s.check("Space adds to the selection", await s.js("document.querySelectorAll('.tile[aria-pressed=true]').length") == 2)
    s.check("exactly one tile is in the tab order",
            await s.js("document.querySelectorAll('.tile[tabindex=\"0\"]').length") == 1)

    await s.say("Tags: add one, filter by it, remove it - the filter must reset")
    await s.click(".tile[data-index='2']")
    await s.click(".inspector .tag-box input")
    await s.type_text("zzz")
    await s.press("Enter")
    await s.wait_for("document.querySelector('#f-tag option[value=zzz]')")
    await s.js("(()=>{const e=document.getElementById('f-tag'); e.value='zzz'; e.dispatchEvent(new Event('change'));})()")
    await s.wait_for(f"{tiles}.length === 1")
    await s.click(".tile[data-index='0']")
    await s.click(".inspector .chip button")
    await s.wait_for(f"{tiles}.length === {PAGE_SIZE}")
    s.check("removing the last use of the filtered tag resets filter and grid",
            await s.js("document.getElementById('f-tag').value") == "")

    await s.say("Fast navigation: the last route must win")
    await s.js(f"location.hash = '#/projects/{project_a}'; location.hash = '#/projects'; true")
    await s.pause(1.2)
    await s.wait_for("document.getElementById('title').textContent === 'Projects'")
    s.check("fast navigation ends on the last route",
            await s.js("document.getElementById('title').textContent") == "Projects"
            and await s.js("!document.querySelector('.gallery')"))

    await s.say("Import 500 images, double-click Start, then cancel part-way")
    await s.goto(f"/#/projects/{project_b}")
    await s.wait_for("document.querySelector('.empty')")
    await s.click(s.by_text(".toolbar-actions .btn", "Import", exact=False))
    await s.wait_for("document.getElementById('import-path')")
    await s.click("#import-path")
    await s.js(f"document.getElementById('import-path').value = {json.dumps(str(cancel_images))}")
    await s.click(s.by_text("dialog .btn", "Start import"), double=True)
    await s.wait_for("document.querySelector('dialog .progress')")
    status, _ = s.api.call("DELETE", f"/api/projects/{project_b}")
    s.check("deleting a project during its import is refused (409)", status == 409, str(status))
    await s.wait_for("(document.querySelector('dialog .progress > div') || {style: {width: ''}}).style.width.length > 0 "
                     "&& document.querySelector('dialog .progress > div').style.width !== '0%'", 30)
    await s.click(s.by_text("dialog .btn", "Cancel import"))
    await s.wait_for("document.querySelector('dialog .stats')", 30)
    summary = await s.js("document.querySelector('dialog').innerText")
    await s.shot("cancelled_summary")
    _, listing = s.api.call("GET", f"/api/projects/{project_b}/images?limit=1")
    _, batches = s.api.call("GET", f"/api/projects/{project_b}/batches")
    s.check("cancel stops the import and says so", "cancelled" in summary.lower(), summary[:60])
    s.check("images kept = images listed = batch record, and fewer than all",
            listing["total"] == batches[0]["added"] and 0 < listing["total"] < CANCEL_IMAGES,
            f"listed={listing['total']} batch={batches[0]['added']}")
    s.check("the double click started only one import", len(batches) == 1, f"{len(batches)} batches")
