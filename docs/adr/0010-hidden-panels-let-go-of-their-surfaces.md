# 10. Hidden panels let go of their surfaces

**Status:** Accepted  
**Date:** 2026-11-27

## Context

ADR 2 keeps one resident process, and every panel is built at start and kept, so a key press only has to show one. Measured in a headless sway (Intel GPU, GTK 4.24, its default Vulkan renderer), after each tool had been opened once:

- each panel that had been shown kept its surface while hidden: its window on the compositor and its swapchain, 3-4 full-size buffers in graphics memory. With every tool opened once that was 132 MB of graphics memory (92 MB of it shared with the compositor), on top of the process's 100-115 MB PSS. `smaps` doesn't show it; the DRM file's `fdinfo` does (`drm-resident-system0`).
- the C heap kept what GTK and Mesa had freed. After a driver update Mesa compiles its shaders in the process, and the heap stayed at 138 MB; `malloc_trim(0)` brings it to about 20 MB in under a millisecond.

Destroying hidden panels instead (and building them again on the next opening) freed the same graphics memory, but the process grew by 35 MB: rebuilt widget trees never give back what the old ones used.

## Decision

A panel that has been hidden for `[vyom] release_after` seconds (default 30; `false` keeps every surface) unrealizes: its widgets, state and the plugin's data stay, only the surface and its buffers go. Then Vyom trims the C heap (`util.trim_memory()`, glibc's `malloc_trim`). It also trims once after the start-up warm-up.

The warm-up's panel lets go too: what the warm-up makes that is worth keeping (pipelines, glyph and icon caches) belongs to the renderer's device, not the surface, and measured first openings stayed as quick.

## Consequences

- With every tool opened once, graphics memory goes from 132 MB to 35-40 MB once they've been hidden a while; the PSS doesn't change.
- Opening a panel that has let go of its surface makes a new one: 10-20 ms more than reopening a kept one (measured; a panel reopens in 8-60 ms with or without it). A panel opened again within `release_after` seconds is as quick as before.
- Plugins see no difference: their widgets are kept. A widget that needs the surface (the frame clock, `get_native()`) has to ask for it after each opening, as `log_first_paint` does.
