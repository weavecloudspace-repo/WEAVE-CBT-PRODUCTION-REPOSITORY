# ========================== #
# app.domains.node.exceptions
# ========================== #


class NodeError(Exception):
    """Base exception for CBT node/installation failures."""


class NodeIdentityNotFoundError(NodeError):
    """Raised when this CBT installation has not been paired yet."""


class NodeIdentityStorageError(NodeError):
    """Raised when persistent installation identity cannot be read or written."""


class NodeIdentityCorruptError(NodeIdentityStorageError):
    """Raised when the stored installation identity is invalid or corrupted."""


class InstallationAlreadyPairedError(NodeError):
    """Raised when pairing is attempted on an already paired installation."""
