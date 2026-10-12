# =========================== #
#   questions/exceptions.py   #
# =========================== #

"""Domain exceptions for question-bank authorization and scope rules."""


class QuestionDomainError(Exception):
    """Base exception for question-domain failures."""


class QuestionNotFound(QuestionDomainError):
    """Raised when a requested question-bank resource does not exist."""


class QuestionAuthorizationError(QuestionDomainError):
    """Raised when an actor cannot author within a question-bank scope."""


class QuestionScopeError(QuestionDomainError):
    """Raised when a question bank references an invalid academic scope."""


class QuestionConflictError(QuestionDomainError):
    """Raised when a question mutation conflicts with newer persisted state."""
