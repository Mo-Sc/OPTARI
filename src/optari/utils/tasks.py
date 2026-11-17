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
    """Re-typed RuntimeError that gets a worker exception past a napari/superqt special case.

    ``GeneratorWorker.work`` treats a bare ``RuntimeError`` specifically — and only that type
    — as "the underlying C/C++ object was probably deleted", returning it instead of letting
    it propagate: ``WorkerBase.run`` then emits neither ``errored`` nor ``finished`` for it, so
    the task looks like it's still running forever, the activity-dock bar never closes and the
    UI stays gated. Every other exception type reaches ``errored`` correctly.
    """


def _guarded(func: Callable[[], Generator]) -> Callable[[], Generator]:
    def wrapper():
        try:
            return (yield from func())
        except RuntimeError as exc:
            raise TaskFailed(exc) from exc

    return wrapper


def run_background_task(
    viewer: Viewer,
    func: Callable[[], Generator],
    *,
    total: int,
    desc: str,
    on_result: Callable,
    on_error: Callable[[str], None],
    on_done: Callable[[], None],
    register: Callable[[GeneratorWorker], None],
    on_cancel: Callable[[], None] | None = None,
) -> GeneratorWorker:
    """Run *func* in a worker thread
    progress bar advances on each yield, and calls *on_result* with the return value when done.

    yielding a number instead (e.g. bytes written) advances it by that amount
    cancelling calls ``worker.quit()``, which stops the generator at its next yield.

    A cancel routes to *on_cancel* and a genuine failure to *on_error*. They default to
    the same thing, which is all a single dock needs, but a caller driving a queue has to
    tell "the user stopped everything" apart from "this one item failed, carry on".

    *register* receives the worker before anything else happens (it gates the UI).
    """

    worker = create_worker(_guarded(func), _ignore_errors=True)
    # Setting up the progress bar processes pending events, among them the `finished`
    # of a task whose result started this one. That task must already find this one
    # registered, or it opens the gate in between.
    register(worker)

    progress_bar = cancelable_progress(total=total, desc=desc)
    # napari only calls cancel_callback when iterating the bar, which this manually
    # updated bar never is, so its Cancel button is pointed at the worker directly.
    progress_bar.cancel = worker.quit

    def finish() -> None:
        progress_bar.close()
        show_activity_dock(viewer, False)
        on_done()

    def report_error(exc: Exception) -> None:
        logger.error("%s failed: %s", desc, exc, exc_info=exc)
        on_error(f"Failed: {exc}")

    worker.yielded.connect(lambda amount: progress_bar.update(amount or 1))
    worker.returned.connect(on_result)
    worker.aborted.connect(on_cancel or (lambda: on_error("Cancelled.")))
    worker.errored.connect(report_error)
    worker.finished.connect(finish)

    show_activity_dock(viewer, True)
    worker.start()
    return worker


def start_task(
    optari_controller: "OptariController",
    step: BackgroundStep,
    *,
    on_result: Callable,
    on_error: Callable[[str], None],
) -> None:
    """Run *step* as the application's single background task.

    Registering the worker gates the UI (run buttons, scan browser) for its duration,
    and clearing it on finish is what releases the gate, so the two are bound together
    here rather than left to each call site to remember. When *on_result* starts the
    next task (download, then run), the gate passes to it and stays closed; whenever
    it does not, for whatever reason, the gate opens.
    """

    def release() -> None:
        if optari_controller.active_task is worker:
            optari_controller.set_active_task(None)

    worker = run_background_task(
        optari_controller.viewer,
        step.func,
        total=step.total,
        desc=step.desc,
        on_result=on_result,
        on_error=on_error,
        on_done=release,
        register=optari_controller.set_active_task,
    )


def download_then(
    optari_controller: "OptariController",
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
            on_error=status_label.setText,
        )

    status_label.setText("Preparing…")
    start_task(
        optari_controller,
        BackgroundStep(
            connect, total=0, desc=f"Connecting for {model_path.name}"
        ),
        on_result=download,
        on_error=status_label.setText,
    )
