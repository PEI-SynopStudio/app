from abc import ABC, abstractmethod

from app.schemas.job import JobRequestMessage


class JobDispatcher(ABC):
    """What the job submission depends on; RabbitMQDispatcher is the implementation."""

    @abstractmethod
    def dispatch(self, request: JobRequestMessage) -> None:
        """Hand the job over and return at once; never runs the pipeline inline."""
