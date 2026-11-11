"""Workout definitions and the sensor-driven training state machine."""

from dataclasses import dataclass
from enum import Enum


@dataclass(frozen=True)
class SwimSet:
    label: str
    distance: int
    repetitions: int
    sendoff: float
    extra_rest: float = 30
    late_rest: float = 0

    def __post_init__(self):
        if self.distance not in (25, 50):
            raise ValueError("Only 25 and 50 unit repetitions are supported")
        if self.repetitions <= 0 or (self.distance == 25 and self.repetitions % 2):
            raise ValueError("Repetitions must be positive, and 25-unit sets must be even")
        if self.sendoff <= 0 or self.extra_rest <= 0 or self.late_rest < 0:
            raise ValueError("Send-off and extra rest must be positive; late rest cannot be negative")

    @property
    def reps_per_arrival(self):
        return 2 if self.distance == 25 else 1


@dataclass(frozen=True)
class Workout:
    name: str
    sets: tuple[SwimSet, ...]

    def __post_init__(self):
        if not self.sets:
            raise ValueError("A workout must contain at least one set")


WORKOUTS = (
    Workout("ENDURANCE", (SwimSet("FR", 25, 20, 50), SwimSet("FR", 50, 8, 90))),
    Workout("MIXED", (SwimSet("FR", 50, 4, 90), SwimSet("BK", 25, 8, 60),
                      SwimSet("FR", 50, 4, 90))),
    Workout("QUICK", (SwimSet("FR", 25, 4, 50), SwimSet("FR", 50, 2, 90))),
)


class Phase(Enum):
    SELECT = "SELECT"
    READY = "READY"
    SWIM = "SWIM"
    REST = "REST"
    BREAK = "BREAK"
    COMPLETE = "COMPLETE"
    STANDBY = "STANDBY"


class WorkoutSession:
    def __init__(self, workouts=WORKOUTS):
        if not workouts:
            raise ValueError("At least one workout is required")
        self.workouts = workouts
        self.choice = 0
        self.history = []
        self.reset()

    @property
    def workout(self):
        return self.workouts[self.choice]

    @property
    def current_set(self):
        return self.workout.sets[self.set_index]

    def select_delta(self, delta):
        if self.phase == Phase.SELECT:
            self.choice = (self.choice + delta) % len(self.workouts)

    def confirm(self, now):
        if self.phase == Phase.STANDBY:
            self.reset()
        elif self.phase == Phase.SELECT:
            self.set_index = 0
            self.completed = 0
            self.history.clear()
            self.phase = Phase.READY
            self.started_at = now
            self.due_at = now
            self.cue_due = True
        elif self.phase == Phase.BREAK:
            self.set_index += 1
            self.completed = 0
            self.phase = Phase.READY
            self.due_at = now
            self.cue_due = True
        elif self.phase == Phase.COMPLETE:
            self.reset()

    def reset(self):
        self.phase = Phase.SELECT
        self.set_index = 0
        self.completed = 0
        self.departed_at = self.due_at = self.started_at = None
        self.far_cue_played = self.wall_cue_played = False
        self.history.clear()
        self.cue_due = False

    def standby(self):
        self.reset()
        self.phase = Phase.STANDBY

    def extra_rest(self, now):
        if self.phase not in (Phase.READY, Phase.REST):
            return False
        self.due_at = max(now, self.due_at) + self.current_set.extra_rest
        self.cue_due = True
        return True

    def complete_set(self):
        """Complete a set without inventing split times."""
        if self.phase not in (Phase.READY, Phase.REST, Phase.SWIM):
            return False
        self.completed = self.current_set.repetitions
        self.phase = (Phase.BREAK if self.set_index + 1 < len(self.workout.sets)
                      else Phase.COMPLETE)
        self.due_at = None
        self.cue_due = False
        return True

    def next_sendoff(self, now):
        """Return the next scheduled departure and end, or None after the last rep."""
        if self.phase in (Phase.READY, Phase.REST):
            return self.due_at, "WALL"
        if self.phase != Phase.SWIM:
            return None
        current = self.current_set
        if current.distance == 25 and now < self.departed_at + current.sendoff:
            return self.departed_at + current.sendoff, "FAR"
        if self.completed + current.reps_per_arrival < current.repetitions:
            return self.departed_at + current.sendoff * current.reps_per_arrival, "WALL"
        return None

    def sensor_event(self, event, now):
        if event == "left" and self.phase in (Phase.READY, Phase.REST):
            self.departed_at = now
            self.phase = Phase.SWIM
            self.cue_due = False
            self.far_cue_played = self.wall_cue_played = False
        elif event == "arrived" and self.phase == Phase.SWIM:
            elapsed = max(0, now - self.departed_at)
            current = self.current_set
            count = current.reps_per_arrival
            if count == 2:
                estimate = elapsed - current.sendoff
                split = estimate if 0 <= estimate <= current.sendoff else None
                for _ in range(2):
                    self.history.insert(0, (current.distance, current.label, split, True))
            else:
                self.history.insert(0, (current.distance, current.label, elapsed, False))
            del self.history[4:]
            self.completed += count
            if self.completed >= current.repetitions:
                self.phase = (Phase.BREAK if self.set_index + 1 < len(self.workout.sets)
                              else Phase.COMPLETE)
                self.due_at = None
                self.cue_due = False
            else:
                self.due_at = self.departed_at + current.sendoff * count
                if now > self.due_at and current.late_rest:
                    self.due_at = now + current.late_rest
                    self.wall_cue_played = False
                self.phase = Phase.REST
                self.cue_due = not self.wall_cue_played

    def tick(self, now):
        """Return True once when a pending send-off is due."""
        if self.phase == Phase.SWIM:
            current = self.current_set
            far_due = (current.distance == 25 and not self.far_cue_played
                       and now >= self.departed_at + current.sendoff)
            wall_due = (self.completed + current.reps_per_arrival < current.repetitions
                        and not self.wall_cue_played
                        and now >= self.departed_at + current.sendoff * current.reps_per_arrival)
            if far_due:
                self.far_cue_played = True
            if wall_due:
                self.wall_cue_played = True
            return far_due or wall_due
        if self.phase in (Phase.READY, Phase.REST) and self.cue_due and now >= self.due_at:
            self.cue_due = False
            return True
        return False