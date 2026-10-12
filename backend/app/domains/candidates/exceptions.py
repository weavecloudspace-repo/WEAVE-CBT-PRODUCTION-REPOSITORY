# =========================== #
#   candidates/exceptions.py  #
# =========================== #

"""Domain exceptions for candidate roster preparation."""


class CandidateDomainError(Exception):
    """Base exception for candidate-domain failures."""


class CandidateRosterError(CandidateDomainError):
    """Raised when a roster cannot be changed in the current exam state."""


class CandidateEnrollmentError(CandidateDomainError):
    """Raised when an enrollment does not belong to the exam session/targets."""


class CandidateAlreadyExists(CandidateDomainError):
    """Raised when the enrollment is already present on the exam roster."""
