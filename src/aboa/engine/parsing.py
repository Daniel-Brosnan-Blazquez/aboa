"""
XML parsing helpers for ABOA archive configuration.

module aboa
"""

import logging
import os
from collections import defaultdict

from lxml import etree

from aboa.engine.errors import ArchiveConfigurationError
from aboa.engine.functions import get_schemas_path

logger = logging.getLogger(__name__)


def _validate_with_lxml(configuration_xml):
    """
    Validate the archive configuration XML file against the ABOA XSD schema.

    :param configuration_xml: parsed XML configuration file
    :type configuration_xml: lxml.etree.Element

    :return: None
    :rtype: None

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


def _warn_duplicated_archive_configuration_fields(configuration_xml):
    """
    Warn when multiple archive rules define the same routing field value.

    :param configuration_xml: parsed XML configuration file
    :type configuration_xml: lxml.etree.ElementTree

    :return: None
    :rtype: None
    """
    field_extractors = {
        "file_group": lambda node: node.get("file_group"),
        "file_mask": lambda node: node.xpath("string(file_mask)").strip(),
        "file_directory": lambda node: node.xpath("string(file_directory)").strip(),
    }

    archive_configurations = configuration_xml.xpath("/archive_configurations/archive_configuration")
    for field_name, field_extractor in field_extractors.items():
        configurations_by_value = defaultdict(list)
        for archive_configuration in archive_configurations:
            value = field_extractor(archive_configuration)
            if value is None:
                continue
            value = value.strip()
            if value != "":
                configurations_by_value[value].append(archive_configuration)

        for value, duplicated_configurations in configurations_by_value.items():
            if len(duplicated_configurations) > 1:
                lines = [
                    str(configuration.sourceline)
                    for configuration in duplicated_configurations
                    if configuration.sourceline is not None
                ]
                line_message = " at lines {}".format(", ".join(lines)) if len(lines) > 0 else ""
                logger.warning(
                    "Archive configuration contains multiple archive_configuration nodes with the same {} '{}'{}.".format(
                        field_name,
                        value,
                        line_message,
                    )
                )


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

    _warn_duplicated_archive_configuration_fields(configuration_xml)

    configuration_xpath = etree.XPathEvaluator(configuration_xml)

    return configuration_xpath
