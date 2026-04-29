"""Base class for task-specific controllers."""


class TaskControllerBase:
    """Minimal interface for task controllers.

    Each task controller (Analysis, Unmixing, etc)
    inherits from this.
    """

    def __init__(self, parent_controller):
        """Initialize with reference to parent controller.

        Args:
            parent_controller: PatariController instance with viewer and session state.
        """
        self.patari_controller = parent_controller
        self.viewer = parent_controller.viewer

    def initialize_ui(self) -> None:
        """Initialize UI controls (populate lists, combos, etc). Override if needed."""
        pass

    def bind_events(self) -> None:
        """Connect signals to event handlers. Override if needed."""
        pass

    def unbind_events(self) -> None:
        """Disconnect signals. Override if needed."""
        pass

    def teardown(self) -> None:
        """Release resources (models, threads). Override if needed."""
        pass
