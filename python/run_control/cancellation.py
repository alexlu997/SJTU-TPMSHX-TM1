"""Qt-free cancellation exception shared by pipelines and solvers."""


class CancelledError(InterruptedError):
    """Raised only at an explicit cooperative cancellation checkpoint."""
