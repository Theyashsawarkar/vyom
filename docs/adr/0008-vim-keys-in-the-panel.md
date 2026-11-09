# 8. Vim keys in the panel: modes, a Space leader, the same letters in every tool

**Status:** Accepted  
**Date:** 2026-11-08

## Context

Every Vayu tool grew its own keys, and the same key came to mean different things: `Ctrl+U` unpaired a phone in doot, showed unnamed devices in setu and scrolled half a page in bhava; `Ctrl+Backspace` removed a device in setu and dismissed every notification in akashvani, even while you typed in the search box. Some keys were dangerous: on a card, GTK's Space pressed the focused button, so Space in the power menu locked the screen. ganit (its ADR 0005) and bhava had already built vim modes, each its own way; bhava did it by reaching into the panel's private widgets. The user asked for every tool to be vim-driven, with Space as the leader and keys that are easy to reason about.

## Decision

The panel owns vim keys, and a tool opts in with `modal = True`:

- **`vyom/keys.py`**, pure Python (no GTK): keys as data (`Bind(seq, action, desc, mode, when)`), tokens and sequences (`" yy"`, `"gg"`, `"<C-d>"`), counts (an exact digit bind still wins), which-key lists, help and palette rows, and `# keybind:` annotations with the mode after the scope (`Vyom/ganit calculator:normal`). The Python tools outside Vyom carry a vendored copy (`scripts/vendor-keys.sh`, with a version and hash header and `--check`), because some load root-owned files under `python3 -I` and can't import from a home directory.
- **`vyom/modal.py`**, the panel side: NORMAL and INSERT modes (`start_mode`, per tab if a dict; `[plugin.x] start_mode` overrides), boxes that take typing only in INSERT (click one to type), a mode pill and the keys typed so far in the footer, a which-key strip 300 ms after a prefix, `?` help, `Space Space` palette, `confirm(question, action)` (y yes, any other key no), and a cursor for cards (j/k between controls, h/l move a slider, Enter toggles).
- **One dispatcher order:** overlays (confirm, help, palette, a tool's own) › a pending sequence or count › the tool's `key()` as the escape hatch › INSERT keys › NORMAL sequences › the old keys as hidden aliases (Tab, Ctrl+H/L, Ctrl+1..9, F11, arrows).
- **The same letters everywhere.** Core keys: `j`/`k`, `gg`/`G`, `Ctrl+d`/`Ctrl+u`, `H`/`L` tabs, `/` search, `i` type, `Enter`, `q`, `?`, `Esc` (pending key, then the tool's own use, then the search, then close). Reserved Space groups (a tool may leave one empty, never reuse its letter): Space palette, `?` keys, `q` close, `t` tabs, `u` toggles (`u f` fullscreen), `y` copy, `f` find, `s` sort, `r` refresh, `a` add, `d` delete, `e` edit, `o` open outside, `g` go to, `m` mark, `,` settings, `k` ask AI. A tool's own nouns use the free letters (b c h i j l n p v w x z).
- **Space never presses a focused button on a card**, modal or not. Enter does.

A tool that doesn't opt in keeps today's keys exactly, so the 14 tools move one at a time.

## Consequences

- Learning one tool teaches the next: `Space y` copies and `Space d` deletes in every tool, `?` lists the keys, and deleting always asks.
- Tools drop their own mode code (ganit's footer, which-key, help and confirm; bhava's widget surgery) and declare data instead; annotations and README tables can be generated from it, so they can't drift.
- New optional hooks on `Plugin` (`keys`, `editables`, `insert_target`, `escape`, `mode_changed`, `mode_hints`, `keys_to_widget`, `wants_all_keys`, `confirm`, `vim_mode`) and `set_status(text, kind)`; nothing a tool already had changes meaning. The names avoid what tools already use (`self.mode` in bhava, `self.counts` in patra).
- A key that moved says where it went, for one release (`Bind(seq, "moved:Space u f", hidden=True)`).
- Things every tool needs live in core, so no tool reaches into the panel's widgets: `Space u p` shows or hides the preview (remembered per tool, like fullscreen), a modal card marks the control you're on with `vk-cursor` (GTK's own focus ring doesn't show in a layer-shell panel), and `Plugin.build_rail()` adds a side rail left of the results (`tabs_in_rail = True` hides the top tab bar when the rail shows the tabs).
- The footer never widens the panel: the tool's keys sit in a box that clips them, a status message takes their place while it shows, and the core's passing notes ("that key moved", "not a key here", "Kept") clear themselves (`set_status(text, kind, clear_after=seconds)`). On a small card the which-key strip uses fewer columns and wraps its title, so it never widens the card either.
- Keys typed before the results are there (`5j` right after the panel opens, or while a search runs) wait for them and then run, instead of moving nothing.
- Supersedes the key part of [ADR 6](0006-tabs-belong-to-the-panel.md) for modal tools: `H`/`L` and `Space t` switch tabs; the old tab keys stay as aliases.
