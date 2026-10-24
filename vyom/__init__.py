"""Vyom: the runtime for Vayu's panels. Tools import the API from here:

    from vyom import Plugin, Row, Section, Hint, util, ui
"""
VERSION = "0.3.0"

from .plugin import Hint, Plugin, Row, Section  # noqa: E402,F401

# `from vyom import ui, util` works inside the daemon (ui needs GTK).
