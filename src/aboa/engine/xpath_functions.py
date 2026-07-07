"""
XPath extension functions for archive configuration matching.

module aboa
"""

import fnmatch

from lxml import etree


def _xpath_match(context, source_mask, file_name):
    """
    XPath extension function to match file names against configured masks.
    """
    if isinstance(file_name, list):
        file_name = file_name[0] if file_name else ""
    masks = source_mask if isinstance(source_mask, list) else [source_mask]
    for mask in masks:
        if hasattr(mask, "text"):
            mask = mask.text
        if mask is not None and fnmatch.fnmatch(str(file_name), str(mask)):
            return True
    return False


def register_xpath_functions():
    """
    Register ABOA XPath extension functions with lxml.
    """
    xpath_namespace = etree.FunctionNamespace(None)
    xpath_namespace["match"] = _xpath_match
