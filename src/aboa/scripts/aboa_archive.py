#!/usr/bin/env python3
"""
Script wrapper for the ABOA archive command.
"""

from aboa.engine.commands import aboa_archive


def main():
    """
    Execute the archive command-line entry point.
    """
    aboa_archive()


if __name__ == "__main__":
    main()
