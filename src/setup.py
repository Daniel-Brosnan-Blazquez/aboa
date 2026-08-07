"""
Setup configuration for the aboa application.

module aboa
"""

from setuptools import find_packages, setup

setup(
    name="aboa",
    version="0.1.0",
    description="Archive for Business Operations Analysis",
    packages=find_packages(),
    package_data={
        "aboa": ["config/*.json", "config/*.xml", "schemas/*.xsd"],
        "aboa.datamodel": ["*.sql"],
    },
    python_requires=">=3",
    install_requires=[
        "sqlalchemy==1.3.22",
        "psycopg2-binary==2.9.11",
        "python-dateutil==2.9.0.post0",
        "lxml==6.0.2",
    ],
    extras_require={
        "tests": [
            "pytest==8.4.2",
            "pytest-cov==7.0.0",
        ]
    },
    entry_points={
        "console_scripts": [
            "aboa_init=scripts.aboa_init:main",
            "aboa_archive=scripts.aboa_archive:main",
            "aboa_retrieve=scripts.aboa_retrieve:main",
            "aboa_delete=scripts.aboa_delete:main",
            "aboa_recover=scripts.aboa_recover:main",
            "aboa_clean_up=scripts.aboa_clean_up:main",
        ]
    },
)
