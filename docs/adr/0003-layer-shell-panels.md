# 3. Panels are layer-shell surfaces, through gtk4-layer-shell

**Status:** Accepted  
**Date:** 2026-10-19

## Context

Panels must float above every window, take the keyboard while open, and sit at an exact place (centred, or under the bar for quick settings). Regular windows are managed by the compositor's tiling rules and can't promise any of that.

## Decision

Every panel is a wlr-layer-shell surface (overlay layer, exclusive keyboard) via gtk4-layer-shell, which must be loaded before GTK: `vyom daemon` re-executes itself with the library in `LD_PRELOAD`.

## Consequences

- Works the same on sway, Hyprland, river, Wayfire, labwc, niri…; not on GNOME's Mutter, which has no layer shell.
- Compositor effects apply by namespace (`vyom`), e.g. SwayFX's `layer_effects` blur.
