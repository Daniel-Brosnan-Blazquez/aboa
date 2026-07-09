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
            "aboa_archive=aboa.engine.commands:aboa_archive",
            "aboa_retrieve=aboa.engine.commands:aboa_retrieve",
            "aboa_delete=aboa.engine.commands:aboa_delete",
            "aboa_recover=aboa.engine.commands:aboa_recover",
            "aboa_clean_up=aboa.engine.commands:aboa_clean_up",
        ]
    },
)
