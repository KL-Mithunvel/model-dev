"""Freeze dataset versions through the real dialog: create, refuse a duplicate, export, delete (Stage 3.3)."""

import json

DESCRIPTION = "versions dialog (create, identical state refused, frozen export, delete) with real clicks"
CONFIG = {}


def last_dialog(expr):
    return f"(() => {{ const d = [...document.querySelectorAll('dialog[open]')].pop(); return d ? ({expr}) : ''; }})()"


async def run(s):
    folder = s.make_images("ver", 3, size=(800, 600))
    project = s.api.make_project("Versions", folder)["id"]
    car = s.api.call("POST", f"/api/projects/{project}/classes", {"name": "car"})[1]["id"]
    items = s.api.call("GET", f"/api/projects/{project}/images?limit=10")[1]["items"]
    ids = [i["id"] for i in items]

    def put(image_id, annotations):
        status, body = s.api.call("PUT", f"/api/images/{image_id}/annotations",
                                  {"rev": 0, "annotations": annotations, "marked_empty": False, "label_class_id": None})
        assert status == 200, body

    box = {"class_id": car, "kind": "box", "data": {"x": 100, "y": 80, "w": 200, "h": 150}}
    put(ids[0], [box])
    put(ids[1], [box])

    await s.say("Open the project and the Versions dialog")
    await s.goto(f"/#/projects/{project}")
    await s.wait_for("[...document.querySelectorAll('.btn')].some(b => b.textContent.trim() === 'Versions…')")
    await s.click(s.by_text(".btn", "Versions…", exact=True))
    await s.wait_for("document.querySelector('#version-name')")
    await s.wait_for("document.querySelector('dialog .hint') && document.querySelector('dialog').innerText.includes('No versions yet')")
    s.check("an empty project says what a version is",
            "freezes the labelled images" in await s.js("document.querySelector('dialog').innerText"))

    await s.say("Type a name and create version 1")
    await s.click("#version-name")
    await s.type_text("first cut")
    await s.click(s.by_text("dialog button", "Create version"))
    await s.wait_for("document.querySelector('[data-version=\"1\"]')")
    row = await s.js("document.querySelector('[data-version=\"1\"]').innerText")
    s.check("version 1 is listed with its name and counts", "first cut" in row and "2 images" in row and "2 annotations" in row, row)
    await s.shot("v1_versions_dialog")

    await s.say("Creating it again without a change is refused in words")
    s.expect_console("409")
    await s.click(s.by_text("dialog button", "Create version"))
    await s.wait_for("document.querySelector('dialog .error-text').innerText.length > 0")
    message = await s.js("document.querySelector('dialog .error-text').innerText")
    s.check("the refusal names version 1", "unchanged since version 1" in message, message)
    s.check("still only one version", await s.js("document.querySelectorAll('[data-version]').length") == 1)

    await s.say("Label one more image, then freeze version 2")
    put(ids[2], [box])
    await s.click(s.by_text("dialog button", "Create version"))
    await s.wait_for("document.querySelector('[data-version=\"2\"]')")
    row2 = await s.js("document.querySelector('[data-version=\"2\"]').innerText")
    s.check("version 2 holds 3 images; the error text was cleared", "3 images" in row2 and await s.js("document.querySelector('dialog .error-text').innerText") == "", row2)

    await s.say("Version 1 still holds what it held: export it from its row")
    await s.click("[data-version='1'] .btn:not(.btn-quiet)")
    await s.wait_for(last_dialog("d.querySelector('.hint[role=status]') && d.querySelector('.hint[role=status]').innerText.includes('image')"))
    title = await s.js(last_dialog("d.querySelector('.dlg-head').innerText"))
    summary = await s.js(last_dialog("d.querySelector('.hint[role=status]').innerText"))
    s.check("the export dialog is for version 1 and counts the 2 frozen images, not the 3 live ones",
            title == "Export version 1" and "2 images" in summary and "2 annotations" in summary, f"{title} | {summary}")
    await s.click(s.by_text("dialog button", "Cancel"))
    await s.wait_for("document.querySelectorAll('dialog[open]').length === 1")

    await s.say("Delete version 2 after confirming")
    await s.click("[data-version='2'] .btn-quiet")
    await s.wait_for("[...document.querySelectorAll('dialog button')].some(b => b.textContent.trim() === 'Delete version')")
    await s.click(s.by_text("dialog button", "Delete version"))
    await s.wait_for("!document.querySelector('[data-version=\"2\"]')")
    s.check("version 2 is gone and version 1 remains", await s.js("document.querySelectorAll('[data-version]').length") == 1)
    versions = s.api.call("GET", f"/api/projects/{project}/versions")[1]
    s.check("the server agrees", [v["number"] for v in versions] == [1], json.dumps(versions)[:200])
    await s.shot("v2_after_delete")
