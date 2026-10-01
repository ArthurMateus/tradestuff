"""``copytrade run [--root PATH]``: start the paper-trading runner (paper only; there is no mode flag)."""

from __future__ import annotations

import argparse


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    raise NotImplementedError
