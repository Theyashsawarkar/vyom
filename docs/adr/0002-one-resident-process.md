# 2. One resident process for every panel

**Status:** Accepted  
**Date:** 2026-10-19

## Context

Each wofi-based popup started a new process: GTK start-up, theme loading and script start-up made every panel take a visible moment to appear, and each script reimplemented its own list and keys.

## Decision

Vyom is a single-instance `Gtk.Application` that stays resident (`vyom daemon`, started at login). `vyom <tool>` only sends it a D-Bus action (`org.gtk.Actions` on `dev.vayu.Vyom`) and never loads GTK itself. Every tool is a plugin loaded into that process and shown in one shared panel class.

## Consequences

- A panel opens in well under a tenth of a second.
- One broken plugin is caught and logged, not fatal; but plugins share a process, so a plugin that blocks the main loop freezes every panel: the API runs `search()` in a thread and offers `background()` for the rest.
- The daemon must be running: the CLI starts it on demand.
