"""Measures how the annotator copes with 200 annotations (plan: 'smooth with 200', provisional).

For each interaction it records the time from a pointer/wheel event to the next painted frame
(handler + rendering), then reports the median and 95th percentile. 16 ms ~ 60 fps."""

import statistics

DESCRIPTION = "performance with 200 boxes and with 200 polygons of 12 points: pan, zoom, move, edit (reports numbers)"
BUDGET_P95_MS = 33  # provisional: 30 fps


async def run(s):
    project = s.api.make_project("Perf", s.make_images("p", 2))["id"]
    car = s.api.call("POST", f"/api/projects/{project}/classes", {"name": "car"})[1]["id"]
    first = s.api.call("GET", f"/api/projects/{project}/images")[1]["items"][0]["id"]
    boxes = [{"class_id": car, "kind": "box", "data": {"x": 10 + (i % 20) * 38, "y": 10 + (i // 20) * 52, "w": 30, "h": 40}} for i in range(200)]
    status, body = s.api.call("PUT", f"/api/images/{first}/annotations", {"rev": 0, "annotations": boxes, "marked_empty": False, "label_class_id": None})
    assert status == 200, body

    await s.goto(f"/#/projects/{project}/annotate/{first}")
    await s.wait_for("document.querySelectorAll('svg.overlay .shape').length === 200")
    await s.wait_for("document.querySelector('.photo').complete")
    print("  200 annotations rendered; measuring...")
    await s.js("""(() => { window.__lat = {}; window.__mode = 'none';
      const stage = document.querySelector('.stage');
      const record = () => { const t0 = performance.now(); requestAnimationFrame(() => requestAnimationFrame(() => {
        (window.__lat[window.__mode] ||= []).push(performance.now() - t0); })); };
      for (const type of ['pointermove', 'wheel']) stage.addEventListener(type, record, true);
    })()""")

    async def measure(mode, action):
        await s.js(f"window.__mode = {mode!r}")
        await action()
        await s.pause(0.2)
        import asyncio
        await asyncio.sleep(0.4)
        samples = await s.js(f"window.__lat[{mode!r}] || []")
        return samples

    async def many_moves(start, end, count, buttons=1):
        x0, y0 = start
        x1, y1 = end
        await s._mouse("mouseMoved", x0, y0)
        await s._mouse("mousePressed", x0, y0, "left", 1, 1)
        for i in range(1, count + 1):
            t = i / count
            await s._mouse("mouseMoved", x0 + (x1 - x0) * t, y0 + (y1 - y0) * t, "left", 1)
        await s._mouse("mouseReleased", x1, y1, "left", 0, 1)

    rect = await s.js("(() => { const r = document.querySelector('.stage').getBoundingClientRect(); return [r.left, r.top, r.width, r.height]; })()")
    cx, cy = rect[0] + rect[2] / 2, rect[1] + rect[3] / 2

    results = {}
    results["wheel zoom"] = await measure("zoom", lambda: wheel_steps(s, cx, cy))
    await s.press("0")
    await s.press("h")
    results["pan drag"] = await measure("pan", lambda: many_moves((cx, cy), (cx + 200, cy + 120), 60))
    await s.press("0")
    await s.press("v")
    inside = await s.js("(() => { const r = document.querySelector('svg.overlay .shape rect').getBoundingClientRect(); return [r.left + r.width / 2, r.top + r.height / 2]; })()")
    results["move a box"] = await measure("move", lambda: many_moves(tuple(inside), (inside[0] + 120, inside[1] + 90), 60))

    # ---- polygons: 200 polygons x 12 points on a second image ---------------------------------
    import math

    second = s.api.call("GET", f"/api/projects/{project}/images")[1]["items"][1]["id"]
    polygons = []
    for i in range(200):
        cx, cy = 20 + (i % 20) * 38, 20 + (i // 20) * 52
        pts = [[round(cx + 14 * math.cos(2 * math.pi * k / 12), 2), round(cy + 18 * math.sin(2 * math.pi * k / 12), 2)] for k in range(12)]
        polygons.append({"class_id": car, "kind": "polygon", "data": {"points": pts}})
    status, body = s.api.call("PUT", f"/api/images/{second}/annotations", {"rev": 0, "annotations": polygons, "marked_empty": False, "label_class_id": None})
    assert status == 200, body
    await s.goto(f"/#/projects/{project}/annotate/{second}")
    await s.wait_for("document.querySelectorAll('svg.overlay .shape').length === 200")
    await s.wait_for("document.querySelector('.photo').complete")
    await s.js("""(() => { window.__lat = {}; window.__mode = 'none';
      const stage = document.querySelector('.stage');
      const record = () => { const t0 = performance.now(); requestAnimationFrame(() => requestAnimationFrame(() => {
        (window.__lat[window.__mode] ||= []).push(performance.now() - t0); })); };
      for (const type of ['pointermove', 'wheel']) stage.addEventListener(type, record, true);
    })()""")
    rect = await s.js("(() => { const r = document.querySelector('.stage').getBoundingClientRect(); return [r.left, r.top, r.width, r.height]; })()")
    cx, cy = rect[0] + rect[2] / 2, rect[1] + rect[3] / 2
    results["zoom (200 polygons)"] = await measure("pzoom", lambda: wheel_steps(s, cx, cy))
    await s.press("0")
    await s.press("v")
    inside = await s.js("(() => { const r = document.querySelector('svg.overlay .shape polygon').getBoundingClientRect(); return [r.left + r.width / 2, r.top + r.height / 2]; })()")
    results["move a polygon"] = await measure("pmove", lambda: many_moves(tuple(inside), (inside[0] + 120, inside[1] + 90), 60))
    await s.click(".ann-row")  # select it from the list (the moved polygon now lies under others on the canvas)
    results["drag a point"] = await measure("pvertex", lambda: drag_first_vertex(s, many_moves))

    print("  interaction      events   median     p95")
    worst = 0
    for name, samples in results.items():
        if not samples:
            s.check(f"{name}: samples were collected", False)
            continue
        ordered = sorted(samples)
        p95 = ordered[max(0, int(len(ordered) * 0.95) - 1)]
        worst = max(worst, p95)
        print(f"  {name:<15} {len(samples):>6}   {statistics.median(samples):6.1f} ms {p95:6.1f} ms")
    s.check(f"every interaction stays under {BUDGET_P95_MS} ms at the 95th percentile with 200 annotations",
            0 < worst < BUDGET_P95_MS, f"worst p95 = {worst:.1f} ms")


async def wheel_steps(s, cx, cy):
    for _ in range(12):
        await s.send("Input.dispatchMouseEvent", type="mouseWheel", x=cx, y=cy, deltaX=0, deltaY=-120)
    for _ in range(12):
        await s.send("Input.dispatchMouseEvent", type="mouseWheel", x=cx, y=cy, deltaX=0, deltaY=120)


async def drag_first_vertex(s, many_moves):
    spot = await s.js("(() => { const r = document.querySelector('svg.overlay .handle.vertex').getBoundingClientRect(); return [r.left + r.width / 2, r.top + r.height / 2]; })()")
    await many_moves(tuple(spot), (spot[0] + 60, spot[1] + 40), 60)
