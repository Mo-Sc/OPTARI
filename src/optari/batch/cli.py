"""Run a batch preset from the terminal.

The runner drives the same controllers as the GUI, so the CLI keeps a hidden napari
viewer and runs the unchanged :class:`BatchRunner` in a Qt event loop. A run from here
and one from the Batch dialog do the same.

Exit codes: 0 all scans done, 1 some scans failed, 2 the plan was refused.
"""

import argparse
import datetime as dt
import os
import signal
import sys
from pathlib import Path

import jax  # noqa: F401, must import before Qt/napari, see launcher.py

from optari.batch.plan import (
    build_plan,
    describe_plan,
    plan_warnings,
    resume_plan,
    validate_plan,
)
from optari.utils.logging import configure_logging
from optari.utils.presets import PresetStore
from optari.utils.setup import get_user_batch_presets_dir


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="optari-batch",
        description="Run an OPTARI batch preset over a dataset",
    )
    parser.add_argument(
        "preset", help="batch preset .json, or a saved preset's name"
    )
    parser.add_argument(
        "dataset", type=Path, help="folder holding Study_*/Scan_* data"
    )
    parser.add_argument(
        "output", type=Path, help="output folder, created if missing"
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="skip scans an interrupted export-only run already exported",
    )
    args = parser.parse_args()
    configure_logging()

    try:
        preset = PresetStore(get_user_batch_presets_dir()).load(args.preset)
        args.output.mkdir(parents=True, exist_ok=True)
        plan = build_plan(
            root=args.dataset, batch_preset=preset, output_dir=args.output
        )
    except (ValueError, OSError) as exc:
        print(f"x {exc}", file=sys.stderr)
        sys.exit(2)

    problems = []
    # an empty dataset is validate_plan's to report, not a finished run
    if args.resume and plan.jobs:
        # the interrupted run's report stays, this one gets its own
        stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        plan.report_name = f"batch_report_{stamp}.xlsx"
        problems += resume_plan(plan)
        if not problems and not plan.jobs:
            print("All scans are already exported.")
            sys.exit(0)
    problems += validate_plan(plan)
    print(describe_plan(plan))
    for warning in plan_warnings(plan):
        print(f"! {warning}")
    if problems:
        print("\n".join(f"✗ {p}" for p in problems), file=sys.stderr)
        sys.exit(2)

    from napari import Viewer
    from qtpy.QtCore import Qt
    from qtpy.QtWidgets import QApplication

    from optari.batch.runner import BatchRunner
    from optari.controllers.optari_controller import OptariController

    app = QApplication([])
    viewer = Viewer(show=False)
    controller = OptariController(viewer)
    # A never-shown window has no GL surface and overlays come out black. Shown with
    # this flag it renders like the GUI's, but nothing appears on screen.
    viewer.window._qt_window.setAttribute(Qt.WA_DontShowOnScreen)
    viewer.window._qt_window.show()

    runner = BatchRunner(
        controller,
        plan,
        on_progress=lambda job, status: print(
            f"{job.key}: {status}", flush=True
        ),
        on_finished=app.quit,
    )
    # Qt's loop would swallow KeyboardInterrupt. Killing outright is safe: every output
    # is written atomically, so only the scan in progress is lost, and --resume picks up.
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    runner.start()
    app.exec_()

    print(f"{runner.report.summary()}, report: {plan.report_path}", flush=True)
    controller.shutdown()
    # skip Qt's teardown after the loop, which can segfault, see launcher.py
    os._exit(1 if runner.report.failures else 0)


if __name__ == "__main__":
    main()
