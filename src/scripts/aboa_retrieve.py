#!/usr/bin/env python3
"""
Script wrapper for the ABOA retrieve command.
"""

from aboa.engine.commands import aboa_retrieve


def main():
    """
    Execute the retrieve command-line entry point.
    """
    aboa_retrieve()


if __name__ == "__main__":
    main()
