"""A saved numerical boundary is separate from a completed result."""


class PausedRun(InterruptedError):
    """Stop only after a complete checkpoint has been published."""

    def __init__(self, checkpoint_file):
        self.checkpoint_file = str(checkpoint_file)
        super().__init__(f'Calculation paused: {self.checkpoint_file}')
