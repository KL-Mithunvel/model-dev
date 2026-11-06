"""A short narrated walk through the app, meant to be watched in the visible browser."""

import json

DESCRIPTION = "narrated demo: create a project, import images, select, split, command palette, dark mode"


async def run(s):
    folder = s.make_images("tour", 30)

    await s.say("The Projects page, empty at first")
    await s.goto("/#/projects")
    await s.wait_for("document.querySelector('.empty')")
    await s.shot("1_empty")

    await s.say("Create a project")
    await s.click(s.by_text("button", "New project", exact=False))
    await s.wait_for("document.getElementById('project-name')")
    await s.click("#project-name")
    await s.type_text("Warehouse pallets")
    await s.click(s.by_text("dialog .btn", "Create project"))
    await s.wait_for("document.querySelector('.gallery')")
    s.check("the new project opens", await s.js("document.getElementById('title').textContent") == "Warehouse pallets")

    await s.say("Import a folder of images")
    await s.click(s.by_text(".toolbar-actions .btn", "Import", exact=False))
    await s.wait_for("document.getElementById('import-path')")
    await s.click("#import-path")
    await s.js(f"document.getElementById('import-path').value = {json.dumps(str(folder))}")
    await s.click(s.by_text("dialog .btn", "Start import"))
    await s.wait_for("document.querySelector('dialog .stats')", 30)
    await s.shot("2_import_summary")
    await s.click(s.by_text("dialog .btn", "Done"))
    await s.wait_for("document.querySelectorAll('.tile').length === 30")
    s.check("30 images are shown", await s.js("document.querySelectorAll('.tile').length") == 30)

    await s.say("Select two images and give them to the test split")
    await s.click(".tile[data-index='0']")
    await s.click(".tile[data-index='1']", modifiers="ctrl")
    await s.click(".inspector .seg button[data-value=test]")
    await s.wait_for("document.querySelectorAll('.tile .badge').length === 2")
    await s.shot("3_selected_split")

    await s.say("Open the command palette with Ctrl+K")
    await s.press("Ctrl+K")
    await s.wait_for("document.querySelector('dialog.palette')")
    await s.type_text("split")
    await s.shot("4_palette")
    await s.press("Escape")

    await s.say("Switch to dark mode")
    await s.click(s.by_text(".nav-item", "Appearance", exact=False))
    await s.wait_for("document.querySelector('dialog .seg')")
    await s.click(s.by_text("dialog .seg button", "Dark"))
    await s.shot("5_dark")
    s.check("dark theme applied", await s.js("document.documentElement.dataset.theme") == "dark")
    await s.click(s.by_text("dialog .btn", "Done"))
    await s.say("That is the tour")
