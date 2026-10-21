# 5. Search panels share one size; cards size themselves

**Status:** Accepted  
**Date:** 2026-10-19

## Context

With each tool choosing its own size, switching tools with Tab made the panel jump around. But card panels (power menu, battery, quick settings) are different kinds of things: stretched to a search panel's size they looked empty.

## Decision

Every list/grid panel opens at `[vyom] width x height` (900x520 by default) times `scale`, capped at 90% of the screen. Card panels and anchored panels keep the tool's own width and are as tall as their content.

## Consequences

- Moving between search tools feels like one window.
- A tool's `width`/`height` only matter for cards and anchored panels.
