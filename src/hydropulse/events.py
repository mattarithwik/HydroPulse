from dataclasses import dataclass, field
from datetime import datetime

from hydropulse.domain import EventType


@dataclass
class EventState:
    open: bool = False
    above_batches: set[str] = field(default_factory=set)
    below_batches: set[str] = field(default_factory=set)
    transitions: list[tuple[datetime, str]] = field(default_factory=list)

    def observe(
        self, at: datetime, batch_id: str, stage: float, threshold: float, stale: bool = False
    ) -> None:
        if stale:
            self.transitions.append((at, "unknown_stale"))
            return
        if stage >= threshold:
            self.above_batches.add(batch_id)
            self.below_batches.clear()
            if not self.open:  # a valid observed crossing opens immediately
                self.open = True
                self.transitions.append((at, EventType.OBSERVED_FLOODING.value))
        else:
            self.below_batches.add(batch_id)
            self.above_batches.clear()
            if self.open and len(self.below_batches) >= 3:
                self.open = False
                self.transitions.append((at, "resolved"))
