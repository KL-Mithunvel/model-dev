"""Export labels as COCO / YOLO and import them back, through the real dialogs (Stage 3.1)."""

import json
import urllib.request
import zipfile

DESCRIPTION = "export dialog (formats, live summary, refusals) and label import (zip round trip, report)"
CONFIG = {}
SKELETON = {"names": ["head", "neck", "tail"], "edges": [[0, 1], [1, 2]]}


def text_of(selector):
    return f"(document.querySelector({json.dumps(selector)}) || {{innerText: ''}}).innerText"


async def set_value(s, selector, value):
    await s.js(f"(() => {{ const e = document.querySelector({json.dumps(selector)}); e.value = {json.dumps(value)}; e.dispatchEvent(new Event('input', {{bubbles: true}})); }})()")


async def run(s):
    folder = s.make_images("ex", 3, size=(800, 600))
    project = s.api.make_project("Exports", folder)["id"]
    car = s.api.call("POST", f"/api/projects/{project}/classes", {"name": "car"})[1]["id"]
    cat = s.api.call("POST", f"/api/projects/{project}/classes", {"name": "cat", "skeleton": SKELETON})[1]["id"]
    items = s.api.call("GET", f"/api/projects/{project}/images?limit=10")[1]["items"]
    ids = [i["id"] for i in items]

    def put(image_id, annotations):
        status, body = s.api.call("PUT", f"/api/images/{image_id}/annotations",
                                  {"rev": 0, "annotations": annotations, "marked_empty": False, "label_class_id": None})
        assert status == 200, body

    put(ids[0], [{"class_id": car, "kind": "box", "data": {"x": 100, "y": 80, "w": 200, "h": 150}},
                 {"class_id": car, "kind": "polygon", "data": {"points": [[400, 100], [600, 120], [500, 300]]}}])
    put(ids[1], [{"class_id": cat, "kind": "keypoints", "data": {"points": [[200, 100, 2], [0, 0, 0], [300, 300, 1]]}}])

    await s.say("Open the export dialog from the project toolbar")
    await s.goto(f"/#/projects/{project}")
    await s.wait_for("document.querySelector('.card, .grid, .empty, [data-id]')")
    await s.click(s.by_text(".btn", "Export…", exact=True))
    await s.wait_for("document.querySelector('dialog[open]') && document.querySelector('dialog .hint[role=status]').innerText.includes('image')")
    summary = await s.js(text_of("dialog .hint[role=status]"))
    s.check("COCO is preselected and the summary counts 2 images and 3 annotations, 1 unlabelled left out",
            "2 images" in summary and "3 annotations" in summary and "1 unlabelled image left out" in summary, summary)
    await s.shot("e1_export_dialog")

    await s.say("Pick YOLO detection: only the box fits, the summary says what is left out")
    await s.click("#export-yolo-detect")
    await s.wait_for("document.querySelector('dialog .hint[role=status]').innerText.includes('cannot hold')")
    summary = await s.js(text_of("dialog .hint[role=status]"))
    s.check("YOLO detect: 1 annotation kept and 2 left out", "1 annotation" in summary and "2 annotations this format cannot hold" in summary, summary)

    await s.say("YOLO pose with a second keypoint class of another size is refused in words")
    s.api.call("POST", f"/api/projects/{project}/classes", {"name": "dog", "skeleton": {"names": ["a", "b"], "edges": []}})
    s.expect_console("400")
    await s.click("#export-yolo-pose")
    await s.wait_for("document.querySelector('dialog .error-text').innerText.length > 0")
    s.check("the refusal explains the problem", "same number of points" in await s.js(text_of("dialog .error-text")))
    await s.click(s.by_text("dialog button", "Cancel"))
    await s.wait_for("!document.querySelector('dialog[open]')")

    await s.say("Build the zips the dialog would download, then import one into a fresh project")
    zip_path = s.work / "coco.zip"
    with urllib.request.urlopen(f"{s.base}/api/projects/{project}/export?format=coco&images=false") as response:
        zip_path.write_bytes(response.read())
    with zipfile.ZipFile(zip_path) as archive:
        s.check("the COCO zip has one annotation file and a report, and no images when asked",
                "annotations/instances_train.json" in archive.namelist() and not [n for n in archive.namelist() if n.startswith("images/")])

    target = s.api.make_project("Target", folder)["id"]
    await s.goto(f"/#/projects/{target}")
    await s.wait_for("[...document.querySelectorAll('.btn')].some(b => b.textContent.trim() === 'Import labels…')")
    await s.click(s.by_text(".btn", "Import labels…", exact=True))
    await s.wait_for("document.querySelector('#labels-path')")
    await s.click("#labels-path")
    await set_value(s, "#labels-path", str(zip_path))  # long Windows paths: paste, do not type
    await s.click(s.by_text("dialog button", "Import labels"))
    await s.wait_for("document.querySelector('dialog [role=status]') && document.querySelector('dialog [role=status]').innerText.includes('annotation')")
    report = await s.js(text_of("dialog [role=status]"))
    s.check("the report says 3 annotations on 2 images and names the new classes",
            "3 annotations on 2 images" in report and "car" in report and "cat" in report, report)
    stored = {i["original_name"]: i["id"] for i in s.api.call("GET", f"/api/projects/{target}/images?limit=10")[1]["items"]}
    counts = sorted(len(s.api.call("GET", f"/api/images/{i}/annotations")[1]["annotations"]) for i in stored.values())
    s.check("the target project now holds 0, 1 and 2 annotations on its three images", counts == [0, 1, 2], str(counts))
    classes = {c["name"]: c for c in s.api.call("GET", f"/api/projects/{target}/classes")[1]}
    s.check("the keypoint class kept its skeleton", classes["cat"]["skeleton"] == SKELETON, str(classes.get("cat")))
    await s.click(s.by_text("dialog button", "Close"))

    await s.say("A folder with nothing usable is explained")
    empty = s.work / "empty_labels"
    empty.mkdir()
    s.expect_console("400")
    await s.click(s.by_text(".btn", "Import labels…", exact=True))
    await s.wait_for("document.querySelector('#labels-path')")
    await s.click("#labels-path")
    await set_value(s, "#labels-path", str(empty))  # long Windows paths: paste, do not type
    await s.click(s.by_text("dialog button", "Import labels"))
    await s.wait_for("document.querySelector('dialog .error-text').innerText.length > 0")
    s.check("a source without labels says what was expected", "Found no COCO" in await s.js(text_of("dialog .error-text")))
