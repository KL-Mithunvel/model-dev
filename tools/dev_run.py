"""Run the app in a real browser and drive it like a user (dev tool).

    python tools/dev_run.py list                      # available scenarios
    python tools/dev_run.py run smoke                 # visible browser, watchable pace
    python tools/dev_run.py run smoke --headless      # no window, full speed (for quick checks)
    python tools/dev_run.py run tour --pace 1.5       # slower, for demos
    python tools/dev_run.py open                      # start the app with demo data and open it
                                                      # for YOU to use; Ctrl+C stops everything

While a visible scenario runs, avoid touching the browser window: the script's pointer is an
on-page red cursor, but your own mouse clicks would still land in the same page.
Screenshots of every run are kept under data/dev_runs/ (gitignored, last 8 runs).
Exit code 0 means every check passed.
"""

import argparse
import asyncio
import importlib.util
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))

from devbrowser import DevRunError, Session  # noqa: E402

SCENARIOS = TOOLS / "scenarios"


def load_scenario(name: str):
    path = SCENARIOS / f"{name}.py"
    if not path.is_file():
        raise DevRunError(f"No scenario named '{name}'. Try: python tools/dev_run.py list")
    spec = importlib.util.spec_from_file_location(f"scenario_{name}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def list_scenarios() -> int:
    for path in sorted(SCENARIOS.glob("*.py")):
        if path.name.startswith("_"):
            continue
        module = load_scenario(path.stem)
        print(f"  {path.stem:<12} {getattr(module, 'DESCRIPTION', '')}")
    return 0


async def run_scenario(args) -> int:
    module = load_scenario(args.scenario)
    print(f"Scenario '{args.scenario}': {getattr(module, 'DESCRIPTION', '')}")
    async with Session(headed=not args.headless, pace=args.pace, browser=args.browser,
                       config=getattr(module, "CONFIG", None), label=args.scenario) as session:
        try:
            await module.run(session)
        except DevRunError as error:
            session.check(f"scenario ran to the end ({error})", False)
            await session.shot("failure")
        except Exception as error:  # report, don't hide, bugs in the scenario itself
            session.check(f"scenario ran to the end ({type(error).__name__}: {error})", False)
            await session.shot("failure")
        return 0 if session.summary() else 1


async def open_for_user(args) -> int:
    from devbrowser import make_images

    async with Session(headed=True, pace=0, browser=args.browser, label="open") as session:
        folder = make_images(session.work / "demo_images", 40, "demo")
        project = session.api.make_project("Demo project", folder)
        await session.goto(f"/#/projects/{project['id']}")
        print(f"The app is open at {session.base}/#/projects/{project['id']} with 40 demo images.")
        print("Use it as you like. Press Ctrl+C here to stop the app and close the browser.")
        try:
            while True:
                await asyncio.sleep(1)
        except (KeyboardInterrupt, asyncio.CancelledError):
            pass
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="list scenarios")
    run = sub.add_parser("run", help="run a scenario")
    run.add_argument("scenario")
    run.add_argument("--headless", action="store_true", help="no visible window; full speed")
    run.add_argument("--pace", type=float, default=None,
                     help="speed of pointer moves and pauses: 1.0 watchable (default when visible), "
                          "0 instant, 2.0 slow")
    run.add_argument("--browser", default=None, help="path to Edge/Chrome (or set STUDIO_BROWSER)")
    opn = sub.add_parser("open", help="start the app with demo data and open it for you")
    opn.add_argument("--browser", default=None)
    args = parser.parse_args(argv)
    try:
        if args.command == "list":
            return list_scenarios()
        if args.command == "run":
            return asyncio.run(run_scenario(args))
        return asyncio.run(open_for_user(args))
    except KeyboardInterrupt:
        return 130
    except DevRunError as error:
        print(f"dev_run: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
