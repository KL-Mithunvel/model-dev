"""Hardware dashboard with simulated readings: live charts, warnings with a fix, time window,
recording a run, viewing and deleting it (Stage 5). Runs on the fake sampler, so any machine passes."""

DESCRIPTION = "hardware dashboard (live charts, warnings, window, record/view/delete a run) with real clicks"
CONFIG = {
    "hardware": {
        "sampler": "fake", "autostart": True, "monitor_interval_s": 0.25, "history_interval_s": 1,
        "fake": {"vram_fraction": 0.95, "gpu_temp_c": 60},
    }
}


async def run(s):
    await s.say("Open the Hardware page from the sidebar")
    await s.goto("/#/projects")
    await s.click("#nav-hardware")
    await s.wait_for("document.querySelectorAll('[data-chart]').length >= 6")
    s.check("the sidebar marks Hardware as the current page",
            await s.js("document.querySelector('#nav-hardware').getAttribute('aria-current')") == "page"
            and await s.js("document.querySelector('#nav-projects').getAttribute('aria-current')") is None)
    s.check("simulated readings are labelled as such", await s.js("!!document.querySelector('[data-simulated]')"))
    s.check("page shows no stray 'null' text", await s.js("!document.body.innerText.includes('null')"))

    await s.say("Live data arrives: the charts show numbers with units")
    await s.wait_for("document.querySelector('[data-chart=cpu] .chart-value').textContent.includes('%')")
    await s.wait_for("document.querySelector('[data-chart=cpu] .chart-line')?.getAttribute('d').length > 20")
    s.check("memory chart shows a percentage and GB used",
            "GB" in await s.js("document.querySelector('[data-chart=ram] .chart-value').textContent"))
    s.check("disk chart shows both read and write",
            await s.js("document.querySelector('[data-chart=disk] .chart-value').textContent.includes('Read') && "
                       "document.querySelector('[data-chart=disk] .chart-value').textContent.includes('Write')"))
    s.check("the GPU memory axis is the card's total (6 GB)",
            "6.0" in await s.js("document.querySelector('[data-chart=gpu-vram] .chart-top').textContent"))
    s.check("every chart has a text alternative",
            await s.js("[...document.querySelectorAll('[data-chart]')].every(c => (c.getAttribute('aria-label')||'').includes(':'))"))
    s.check("CPU thread bars exist", await s.js("document.querySelectorAll('[data-core]').length") == 8)
    await s.shot("monitor_live")

    await s.say("GPU memory is nearly full: a specific warning with a fix")
    await s.wait_for("document.querySelector('[data-warning=vram_high]')")
    text = await s.js("document.querySelector('[data-warning=vram_high]').innerText")
    s.check("the warning says what is wrong and what to do", "GPU memory" in text and "What to do" in text and "batch size" in text, text)
    s.check("the device card names the GPU", "Fake GPU" in await s.js("document.querySelector('[data-device]').innerText"))

    await s.say("Switch the time window")
    await s.click("[data-window='300']")
    await s.wait_for("document.querySelector('[data-chart=cpu] .chart-start').textContent.includes('5 min')")
    s.check("the chosen window is pressed and the axis label follows",
            await s.js("document.querySelector('[data-window=\"300\"]').getAttribute('aria-pressed')") == "true")

    await s.say("An empty name is refused in words")
    s.expect_console("400")
    await s.click("#start-run")
    await s.wait_for("document.querySelector('.monitor .error-text').textContent.length > 0")

    await s.say("Record a run")
    await s.click("#run-name")
    await s.type_text("Overnight check")
    await s.press("Enter")
    await s.wait_for("document.querySelector('[data-recording]')")
    s.check("recording shows the run name", "Overnight check" in await s.js("document.querySelector('[data-recording]').innerText"))
    await s.js("window.__stop = document.querySelector('#stop-run')")
    await s.wait_for("document.querySelector('[data-recording]').innerText.includes('0:03')")
    s.check("the Stop button is the same element after several samples (not rebuilt)",
            await s.js("document.querySelector('#stop-run') === window.__stop"))  # real seconds: pause() is skipped when headless
    await s.click("#stop-run")
    await s.wait_for("document.querySelector('[data-runs] [data-view]:not([disabled])')")  # the row exists while recording, but View is disabled
    row = await s.js("document.querySelector('[data-runs] [data-run]').innerText")
    s.check("the finished run is listed", "Overnight check" in row, row)

    await s.say("View the run: charts of the stored readings and a summary")
    await s.click("[data-runs] [data-view]")
    await s.wait_for("document.querySelector('dialog[open] [data-summary]')")
    s.check("the run dialog draws charts from stored rows",
            await s.js("document.querySelectorAll('dialog[open] [data-chart]').length") >= 6)
    s.check("the summary has average and peak columns",
            "Peak" in await s.js("document.querySelector('dialog[open] [data-summary]').innerText"))
    await s.shot("monitor_run")
    await s.click(s.by_text("dialog button", "Close"))

    await s.say("Delete the run after confirming")
    await s.click("[data-runs] [data-delete]")
    await s.click(s.by_text("dialog button", "Delete run"))
    await s.wait_for("!document.querySelector('[data-runs] [data-run]')")
    s.check("the list is empty again and says so", "No runs yet" in await s.js("document.querySelector('[data-runs]').innerText"))

    await s.say("Leaving the page stops the live feed; coming back works")
    await s.click("#nav-projects")
    await s.wait_for("location.hash === '#/projects'")
    await s.click("#nav-hardware")
    await s.wait_for("document.querySelector('[data-chart=cpu] .chart-line')?.getAttribute('d').length > 20")
    s.check("the page works again after leaving and returning", True)
