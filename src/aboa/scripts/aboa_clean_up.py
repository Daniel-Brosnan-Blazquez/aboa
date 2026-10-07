#!/usr/bin/env python3
"""
Script wrapper for the ABOA clean-up command.
"""

from aboa.engine.commands import aboa_clean_up


def main():
    """
    Execute the clean-up command-line entry point.
    """
    aboa_clean_up()


if __name__ == "__main__":
    main()
