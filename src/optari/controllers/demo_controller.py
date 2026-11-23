"""Template controller for a new feature, see "Adding a feature" in the developer guide.

To activate, uncommented in OptariController`.

It shows the viewer's frame and runs a background step that walks over the scan's
frames.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Generator
from dataclasses import dataclass
from functools import partial

from optari.controllers.base import TaskControllerBase
from optari.utils.tasks import BackgroundStep
from optari.widgets.demo_dock import create_demo_dock


@dataclass(frozen=True)
class DemoParams:
    """Everything one run needs, read from the dock (or a batch preset) before it
    starts.
    """

    n_frames: int


def demo_frames(n_frames: int) -> Generator[None, None, int]:
    """The work itself. Runs in a worker thread, so it must not touch Qt or napari.

    Each yield advances the progress bar by one, and cancelling stops it at the next
    yield.
    """
    for _ in range(n_frames):
        time.sleep(0.05)
        yield
    return n_frames


class DemoController(TaskControllerBase):
    """Owns the Demo dock, which only it uses, so it declares the dock itself."""

    DOCK = ("demo_dock", create_demo_dock, "Demo", "right", True)

    def _signal_bindings(self) -> list[tuple[object, Callable]]:
        return [(self.dock.run_button.clicked, self.on_run_clicked)]

    def refresh_ui(self) -> None:
        """Called after every state change, e.g.

        a scan load or a task starting or ending.
        """
        self.dock.run_button.setEnabled(
            self.optari_controller.pa_data is not None
            and not self.optari_controller.task_running
        )

    def on_frame_changed(self, frame_idx: int) -> None:
        self.dock.status_label.setText(f"Viewer on frame {frame_idx}.")

    def on_run_clicked(self, event=None) -> None:
        # run_from_ui chains _params_from_ui, prepare, the worker and publish, and gates
        # the UI while it runs.
        self.run_from_ui(self.dock)

    def _params_from_ui(self) -> DemoParams:
        pa_data = self.optari_controller.pa_data
        if pa_data is None:
            raise ValueError("Load a scan first.")
        return DemoParams(n_frames=int(pa_data.shape[0]))

    def prepare(self, params: DemoParams) -> BackgroundStep:
        return BackgroundStep(
            func=partial(demo_frames, params.n_frames),
            total=params.n_frames,
            desc="Running demo",
        )

    def publish(self, result: int, params: DemoParams) -> str:
        """Back on the main thread: add layers here.

        Returns the text after "Finished:".
        """
        return f"walked over {result} frame(s), nothing changed"
