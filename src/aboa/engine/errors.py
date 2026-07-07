"""
Errors definition for the engine module.

module aboa
"""

class Error(Exception):
    """Base class for exceptions in this module."""
    pass


class InputError(Error):
    """Raised when a caller provides invalid query or command input."""
    pass


class AboaResourcesPathNotAvailable(Error):
    """Raised when the environment variable ABOA_RESOURCES_PATH is not defined."""
    pass


class AboaLogPathNotAvailable(Error):
    """Raised when the environment variable ABOA_LOG_PATH is not defined."""
    pass


class AboaSchemasPathNotAvailable(Error):
    """Raised when the environment variable ABOA_SCHEMAS_PATH is not defined."""
    pass


class ArchiveConfigurationError(Error):
    """Raised when archive XML configuration is missing, malformed, or invalid."""
    pass


class ArchiveFileError(Error):
    """Raised when an archive operation cannot process the requested file."""
    pass


class ArchiveDeletionError(Error):
    """Raised when archived-file deletion fails."""
    pass


class ArchiveRetrievalError(Error):
    """Raised when archived-file retrieval fails."""
    pass


class ProcessorError(Error):
    """Raised when a configured metadata processor cannot be executed correctly."""
    pass
