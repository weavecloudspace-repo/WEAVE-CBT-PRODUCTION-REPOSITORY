# =========================== #
#    attempts/exceptions.py   #
# =========================== #

"""Domain exceptions for candidate examination attempts."""


class AttemptError(Exception):
    """Base exception for attempt-domain failures."""


class ExamNotActiveForAttempt(AttemptError):
    """Raised when a candidate tries to start an exam that is not active."""


class ExamNotYetOpen(AttemptError):
    """Raised when a candidate tries to start before the exam opens."""


class ExamStartWindowClosed(AttemptError):
    """Raised when a new attempt is requested at or after the exam close time."""


class AttemptNotInterrupted(AttemptError):
    """Raised when resume is requested for an attempt that is not interrupted."""


class AttemptTimeExhausted(AttemptError):
    """Raised when an interrupted attempt has no writing time remaining."""
