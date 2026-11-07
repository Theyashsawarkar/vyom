# 7. A status strip, and one look for every tool

**Status:** Accepted  
**Date:** 2026-11-07

## Context

Each tool showed state its own way: tarang's connected network was a row like any other, setu's batteries a small number at the end of a row, kendra's tiles told on from off by a faint tint. The selected row was a light tint with a 1px frame that was easy to lose on a dim screen, signal strength was a bare percentage, and colour alone carried meaning in several places. Tools re-built the same pieces (a battery bar, a coloured chip, a progress list) slightly differently.

## Decision

- `Plugin.build_strip()` returns a widget shown above the list (a status strip: what's going on before you read the list), rebuilt after every search or with `self.panel.refresh_strip()`.
- `Row` gains `chips` (coloured chips at the right) and `level` / `level_text` / `level_color` (4 signal bars and a word: "Good"), and `Section` gains `count` and `note`.
- `vyom.ui` gains the shared building blocks: `hero`, `ring`, `bars`, `meter`, `steps`, `notice`, `segmented`, `section`, `soft`, `chips`, `keycap`, and `button(..., key=)` that shows its key on the button. Drawn widgets take their colour from CSS (`t-<colour>`), so themes apply.
- The look: the selected row has a 2px accent frame, a tint and a 4px bar on its left edge; rows are taller with larger text; chips have an outline in their colour; the current tab is underlined in the accent.
- Colour always means something (red danger, green done, yellow waiting, peach what to look for, accent where you are) and is never the only signal: a word or a shape says it too.

## Consequences

Tools describe their state and the panel draws it the same way everywhere. Older tools keep working (the new fields default to nothing), but look like the new ones only once they use the strip and the new row fields.
