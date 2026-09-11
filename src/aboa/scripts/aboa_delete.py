#!/usr/bin/env python3
"""
Script wrapper for the ABOA delete command.
"""

from aboa.engine.commands import aboa_delete


def main():
    """
    Execute the delete command-line entry point.
    """
    aboa_delete()


if __name__ == "__main__":
    main()
