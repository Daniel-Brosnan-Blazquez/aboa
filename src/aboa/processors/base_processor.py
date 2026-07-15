"""
Base processor contract for ABOA file metadata extraction.

module aboa
"""


class BaseProcessor():
    """
    Default processor contract for ABOA metadata extraction.

    Custom processors should expose a ``process(file_path)`` function returning a
    dictionary with any metadata extracted from the file.
    """

    version = "1.0"

    def process(self, file_path):
        """
        Extract metadata from a file.

        :param file_path: path to the file being archived
        :type file_path: str

        :return: metadata dictionary
        :rtype: dict
        """
        return {}


def process(file_path):
    """
    Module-level default processor function.

    :param file_path: path to the file being archived
    :type file_path: str

    :return: metadata dictionary
    :rtype: dict
    """
    return BaseProcessor().process(file_path)
