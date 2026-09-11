#!/usr/bin/env python3
"""
Script wrapper for the ABOA recover command.
"""

from aboa.engine.commands import aboa_recover


def main():
    """
    Execute the recover command-line entry point.
    """
    aboa_recover()


if __name__ == "__main__":
    main()
