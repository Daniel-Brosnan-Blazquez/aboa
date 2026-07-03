"""
Errors definition for the datamodel module.

module aboa
"""

class Error(Exception):
    """Base class for exceptions in this module."""
    pass


class AboaResourcesPathNotAvailable(Error):
    """Raised when the environment variable ABOA_RESOURCES_PATH is not defined."""

    def __init__(self, message):
        """
        Store the exception message.

        :param message: explanation of the missing resources path
        :type message: str
        """
        self.message = message
        super().__init__(message)
