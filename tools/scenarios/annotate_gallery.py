"""Gallery side of annotation (v0.2): progress, badges, filters, and the ways into the annotator."""

DESCRIPTION = "gallery + annotation: progress, badges, filters, Annotate buttons, class manager"
CONFIG = {"annotations": {"save_debounce_ms": 150}}


def put(s, image_id, annotations=(), empty=False, label=None):
    rev = s.api.call("GET", f"/api/images/{image_id}/annotations")[1]["rev"]
    status, body = s.api.call("PUT", f"/api/images/{image_id}/annotations", {
        "rev": rev, "annotations": list(annotations), "marked_empty": empty, "label_class_id": label})
    assert status == 200, body


async def run(s):
    project = s.api.make_project("Gallery labels", s.make_images("g", 6))["id"]
    car = s.api.call("POST", f"/api/projects/{project}/classes", {"name": "car"})[1]["id"]
    s.api.call("POST", f"/api/projects/{project}/classes", {"name": "bus"})
    ids = [i["id"] for i in s.api.call("GET", f"/api/projects/{project}/images?limit=20")[1]["items"]]
    box = {"class_id": car, "kind": "box", "data": {"x": 10, "y": 10, "w": 50, "h": 40}}
    put(s, ids[0], [box, box])
    put(s, ids[1], [box])
    put(s, ids[2], empty=True)
    put(s, ids[3], label=car)  # ids[4] and ids[5] stay unlabelled

    await s.say("The gallery shows labelling progress and a badge on each tile")
    await s.goto(f"/#/projects/{project}")
    await s.wait_for("document.querySelectorAll('.tile').length === 6")
    summary = await s.js("document.getElementById('summary').textContent")
    s.check("the summary says 4 of 6 are labelled", "4 of 6 labelled" in summary, summary)
    badges = await s.js("[...document.querySelectorAll('.tile .badge-right')].map(b => b.textContent.trim())")
    s.check("tiles show 2, 1, empty and the label name", badges == ["2", "1", "empty", "car"], str(badges))
    await s.shot("g1_badges")

    await s.say("Filter to the images that still need labelling")
    await s.js("(()=>{const e=document.getElementById('f-labelled'); e.value='false'; e.dispatchEvent(new Event('change'));})()")
    await s.wait_for("document.querySelectorAll('.tile').length === 2")
    s.check("'Not labelled yet' keeps only the 2 unlabelled images", True)
    await s.js("(()=>{const e=document.getElementById('f-labelled'); e.value=''; e.dispatchEvent(new Event('change'));})()")
    await s.js(f"(()=>{{const e=document.getElementById('f-class'); e.value='{car}'; e.dispatchEvent(new Event('change'));}})()")
    await s.wait_for("document.querySelectorAll('.tile').length === 3")
    s.check("the 'car' class filter keeps images with a car box or the car label (3)", True)
    await s.click(s.by_text("button", "Clear filters"))
    await s.wait_for("document.querySelectorAll('.tile').length === 6")

    await s.say("The Annotate button opens the first image that still needs labelling")
    await s.click(s.by_text(".toolbar-actions .btn", "Annotate", exact=False))
    await s.wait_for(f"location.hash === '#/projects/{project}/annotate/{ids[4]}'")
    s.check("Annotate went to the first unlabelled image", True)

    await s.say("Back in the gallery: double-click a tile, and the inspector's Annotate button")
    await s.goto(f"/#/projects/{project}")
    await s.wait_for("document.querySelectorAll('.tile').length === 6")
    await s.click(".tile[data-index='1']", double=True)
    await s.wait_for(f"location.hash === '#/projects/{project}/annotate/{ids[1]}'")
    s.check("double-clicking a tile opens it in the annotator", True)
    await s.goto(f"/#/projects/{project}")
    await s.wait_for("document.querySelectorAll('.tile').length === 6")
    await s.click(".tile[data-index='5']")
    await s.click(s.by_text(".inspector .btn", "Annotate this image"))
    await s.wait_for(f"location.hash === '#/projects/{project}/annotate/{ids[5]}'")
    s.check("the inspector's Annotate button opens that image", True)

    await s.say("Manage classes from the gallery")
    await s.goto(f"/#/projects/{project}")
    await s.wait_for("document.querySelectorAll('.tile').length === 6")
    await s.click(s.by_text(".toolbar-actions .btn", "Classes", exact=False))
    await s.wait_for("document.querySelector('dialog') && document.querySelector('dialog').innerText.includes('car')")
    await s.shot("g2_class_manager")
    await s.click(s.by_text("dialog .btn", "Add a class"))
    await s.wait_for("document.getElementById('class-name')")
    await s.type_text("truck")
    await s.click(s.by_text("dialog .btn", "Add class"))
    await s.wait_for("document.querySelector('dialog') && document.querySelector('dialog').innerText.includes('truck')")
    classes = [c["name"] for c in s.api.call("GET", f"/api/projects/{project}/classes")[1]]
    s.check("a class added from the gallery exists on the server", classes == ["car", "bus", "truck"], str(classes))
