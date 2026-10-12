# ==============================#
# backend.app.core.exceptions
# ===============================#


"""
This file defines custom exceptions used accross the application in a clean and neat manner
"""


class AcademicAuthorizationError(Exception):
    """Raised when an actor is not allowed to perform an academic action."""


class AcademicScopeError(Exception):
    """Raised when synchronized academic data is invalid or unavailable."""
