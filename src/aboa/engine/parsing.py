"""
XML parsing helpers for ABOA archive configuration.

module aboa
"""

import os
from lxml import etree

from aboa.engine.errors import ArchiveConfigurationError
from aboa.engine.functions import get_schemas_path


def _validate_with_lxml(configuration_xml):
    """
    Validate the archive configuration XML file against the ABOA XSD schema.

    :param configuration_xml: parsed XML configuration file
    :type configuration_xml: lxml.etree.Element

    :raises ArchiveConfigurationError: when the file does not pass schema validation
    """

    # Parse schema and validate the XML file against it
    schema_path = os.path.join(get_schemas_path(), "aboa_archive_configurations.xsd")

    # Parse the XML configuration file
    try:
        xml_schema = etree.XMLSchema(etree.parse(schema_path))
    except etree.XMLSyntaxError as exc:
        raise ArchiveConfigurationError("The schema file is not valid XML: {}".format(exc))
    
    if not xml_schema.validate(configuration_xml):
        errors = "\n".join([str(error) for error in xml_schema.error_log])
        raise ArchiveConfigurationError("The configuration does not pass the schema validation: {}".format(errors))


def get_archive_configuration(configuration_path, validate_schema=True):
    """
    Parse an ABOA archive configuration XML file.

    The returned structure is runtime configuration only. File masks, file
    directories, processors, and retention policy keys are not persisted in database
    inventory tables.

    :param configuration_path: path to the XML configuration file
    :type configuration_path: str
    :param validate_schema: flag indicating whether to validate against the XSD
    :type validate_schema: bool

    :return: XPath evaluator for the parsed configuration
    :rtype: lxml.etree.XPathEvaluator

    :raises ArchiveConfigurationError: when the file is missing, malformed, or does
        not satisfy ABOA configuration rules
    """
    # Check if the XML configuration file exists
    if not os.path.exists(configuration_path):
        raise ArchiveConfigurationError("The configuration file {} does not exist".format(configuration_path))

    # Parse the XML configuration file
    try:
        configuration_xml = etree.parse(configuration_path)
    except etree.XMLSyntaxError as exc:
        raise ArchiveConfigurationError("The configuration file is not valid XML: {}".format(exc))

    # Validate the XML configuration file against the schema
    if validate_schema:
        _validate_with_lxml(configuration_xml)

    configuration_xpath = etree.XPathEvaluator(configuration_xml)

    return configuration_xpath