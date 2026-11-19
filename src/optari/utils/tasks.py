"""Run heavy work off the Qt main thread with progress bar and cancellation."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Generator

import requests
from napari.qt.threading import GeneratorWorker, create_worker
from napari.utils.progress import cancelable_progress
from napari.viewer import Viewer
from qtpy.QtWidgets import QLabel

from optari.utils.misc import download_chunks, open_download
from optari.utils.viewer import show_activity_dock
from optari.widgets.dock_helpers import show_status_error

if TYPE_CHECKING:
    from optari.controllers.optari_controller import OptariController

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BackgroundStep:
    """Heavy work that has been validated and is ready to run in a worker thread.

    Separating "work out what to run" from "run it" is what lets a dock and an
    unattended batch run share one compute path: both build a step, one hands it to
    `start_task`, the other drives it inside a longer sequence.
    """

    func: Callable[[], Generator]
    total: int
    desc: str


class TaskFailed(Exception):
    """Re-typed RuntimeError that gets a worker exception past a napari/superqt special
    case.

    ``GeneratorWorker.work`` treats a bare ``RuntimeError``, and only that type, as "the
    underlying C/C++ object was probably deleted", returning it instead of letting it
    propagate: ``WorkerBase.run`` then emits neither ``errored`` nor ``finished`` for
    it, so the task looks like it's still running forever, the activity-dock bar never
    closes and the UI stays gated. Every other exception type reaches ``errored``
    correctly.
    """


def _guarded(func: Callable[[], Generator]) -> Callable[[], Generator]:
    """Wrap *func* so its RuntimeError reaches ``errored`` (see ``TaskFailed``)."""

    def wrapper():
        try:
            return (yield from func())
        except RuntimeError as exc:
            raise TaskFailed(exc) from exc

    return wrapper


# What a finished task reports, once: ("ok", return value), ("error", message) or
# ("cancelled", None).
Outcome = tuple[str, object]


def run_background_task(
    viewer: Viewer,
    step: BackgroundStep,
    *,
    register: Callable[[GeneratorWorker], None],
    on_finished: Callable[[Outcome], None],
) -> GeneratorWorker:
    """Run *step* in a worker thread with a progress bar that advances on each yield.

    Yielding a number instead (e.g. bytes written) advances it by that amount.
    Cancelling calls ``worker.quit()``, which stops the generator at its next yield.

    *on_finished* gets the outcome once the worker's ``finished``, its last signal, has
    fired, so whatever it starts next cannot race this worker's teardown. A queue (batch
    mode) tells a cancel from a failure, a single dock treats both alike (`start_task`).
    *register* receives the worker before anything else happens (it gates the UI).
    """

    worker = create_worker(_guarded(step.func), _ignore_errors=True)
    # Setting up the progress bar processes pending events, among them the `finished`
    # of a task whose result started this one. That task must already find this one
    # registered, or it opens the gate in between.
    register(worker)

    progress_bar = cancelable_progress(total=step.total, desc=step.desc)
    # napari only calls cancel_callback when iterating the bar, which this manually
    # updated bar never is, so its Cancel button is pointed at the worker directly.
    progress_bar.cancel = worker.quit
    outcome: list[Outcome] = [("error", f"{step.desc} produced no result")]

    def settle(kind: str, value: object = None) -> None:
        outcome[0] = (kind, value)

    def report_error(exc: Exception) -> None:
        logger.error("%s failed: %s", step.desc, exc, exc_info=exc)
        settle("error", f"Failed: {exc}")

    def finish() -> None:
        progress_bar.close()
        show_activity_dock(viewer, False)
        on_finished(outcome[0])

    worker.yielded.connect(lambda amount: progress_bar.update(amount or 1))
    worker.returned.connect(lambda result: settle("ok", result))
    worker.aborted.connect(lambda: settle("cancelled"))
    worker.errored.connect(report_error)
    worker.finished.connect(finish)

    show_activity_dock(viewer, True)
    worker.start()
    return worker


def start_task(
    optari_controller: OptariController,
    step: BackgroundStep,
    *,
    on_result: Callable[[object], None],
    on_error: Callable[[str], None],
) -> None:
    """Run *step* as the application's single background task.

    Registering the worker gates the UI (run buttons, scan browser) for its duration,
    and clearing it on finish is what releases the gate, so the two are bound together
    here rather than left to each call site to remember. When *on_result* starts the
    next task (download, then run), the gate passes to it and stays closed; whenever
    it does not, for whatever reason, the gate opens.
    """

    def finished(outcome: Outcome) -> None:
        kind, value = outcome
        try:
            if kind == "ok":
                on_result(value)
            else:
                on_error("Cancelled." if kind == "cancelled" else value)
        finally:
            if optari_controller.active_task is worker:
                optari_controller.set_active_task(None)

    worker = run_background_task(
        optari_controller.viewer,
        step,
        register=optari_controller.set_active_task,
        on_finished=finished,
    )


def download_then(
    optari_controller: OptariController,
    model_path: Path,
    url: str | None,
    status_label: QLabel,
    then: Callable[[], None],
) -> None:
    """Ensure *model_path* exists, downloading it as a background task if not, then run
    *then*. Runs *then* immediately when the file is already present.

    Connecting is a task of its own, since a slow server would otherwise freeze the
    window, and it yields the size the download's progress bar needs.
    """
    if model_path.is_file():
        then()
        return

    def connect():
        opened = open_download(url, model_path.name)
        yield  # where a cancel during the request takes effect
        return opened

    def download(opened: tuple[requests.Response, int]) -> None:
        response, total_size = opened
        logger.info(
            "downloading model '%s' (%s bytes)",
            model_path.name,
            total_size or "unknown",
        )
        start_task(
            optari_controller,
            BackgroundStep(
                partial(download_chunks, response, model_path),
                total=total_size,
                desc=f"Downloading {model_path.name}",
            ),
            on_result=lambda _: then(),
            on_error=partial(show_status_error, status_label),
        )

    status_label.setText("Preparing…")
    start_task(
        optari_controller,
        BackgroundStep(connect, total=0, desc=f"Connecting for {model_path.name}"),
        on_result=download,
        on_error=partial(show_status_error, status_label),
    )
