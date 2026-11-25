# 9. The Spatial look

**Status:** Accepted  
**Date:** 2026-11-25

## Context

ADR 7 gave every panel one look: Catppuccin Mocha glass with an accent frame. In practice the accent was mauve everywhere (the panel's border, the selection's frame and left bar, primary buttons, sliders), and with tinted tiles beside it the panels read as a popular theme rather than Vayu's own. Nine directions were drawn on the same desktop with the same tools; Spatial was chosen.

## Decision

Panels keep ADR 7's structure (mode pill, content, key-cap footer) and take the Spatial look:

- Graphite glass with a faint white lift, a white hairline and a lit top edge; 28 px corners (SwayFX's `layer_effects "vyom"` matches).
- Where you are is brighter glass with a light rim, not a coloured frame or left bar; the accent is near-white in Vayu's theme.
- Search bar, tabs, buttons, chips, segmented controls, sliders and progress bars are pills; colour stays for meaning only; no glows.
- The fallback colours (without varna) are Vayu's Spatial palette.

## Consequences

- Every tool's own `style.css` follows the same shapes (round icons, borderless glass tiles, rims for the cursor).
- A theme with a coloured accent still works: selection is the accent at low alpha with a rim, so it tints rather than frames.
- The 3D tilt of the design mock-up isn't possible: layer-shell surfaces are flat.
