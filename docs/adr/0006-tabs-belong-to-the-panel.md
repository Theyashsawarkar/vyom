# 6. Tabs belong to the panel, with one set of keys

**Status:** Accepted  
**Date:** 2026-10-24

## Context

Six tools grew tabs (bhava's categories, mudra's apps, raga's music/video, smriti's kinds, tarang's networks/hotspot, ganit's calculate/convert), each built from its own toggle buttons in `header_extra()` and switched with its own keys: `Ctrl+0..9`, `Ctrl+1..9`, `Ctrl+1..5`, `Ctrl+M`, `Ctrl+H`, `Ctrl+Tab`. Moving between tools meant relearning how to change tabs, and tarang's `Ctrl+H` (a toggle) fought the vim reading of h/l as left/right, next to the `Ctrl+K`/`Ctrl+J` every panel already uses for up/down.

## Decision

A tool declares `tabs = [(key, label[, tooltip])]` and gets `self.tab` and a `tab_changed(key)` hook; the panel draws the tabs in the search bar and switches them, the same in every tool:

- `Ctrl+H` / `Ctrl+L`: the previous / next tab, wrapping around (vim's left/right, beside `Ctrl+K`/`Ctrl+J`).
- `Ctrl+1..9`, `Ctrl+0`: a tab by its number (the tenth for 0).
- The footer shows `Ctrl+H/L tabs` whenever a tool has tabs; each tab's tooltip shows its number.

`select_tab(key)` switches from the tool (`vyom raga video`), `set_tabs()` replaces them (mudra's depend on what it finds), `tab_class` restyles them (bhava's glyphs). The panel handles these keys after the tool's `key()`, so a tool without tabs keeps `Ctrl+1..9` and `Ctrl+H/L` for itself (dvara's numbered actions).

## Consequences

- One way to change tabs everywhere, entirely from the keyboard, and the vim keys line up: J/K move through results, H/L through tabs.
- Tools lose their tab code and per-tool tab CSS; the look lives in Vyom's style.css.
- Tools with tabs need Vyom 0.3.0. Their old tab keys are gone (raga's `Ctrl+M`, ganit's `Ctrl+Tab`); tarang's `Ctrl+H` now means "previous tab", and bhava's numbers moved by one (`Ctrl+1` is Recent, `Ctrl+0` the tenth category).
