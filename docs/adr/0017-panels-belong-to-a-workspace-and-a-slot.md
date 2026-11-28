# 17. Panels belong to a workspace and a slot

**Status:** Accepted (changes ADR 3's "exclusive keyboard")  
**Date:** 2026-11-28

## Context

Every panel was an overlay layer surface with an exclusive keyboard, and opening one closed every other (`close_all`). Layer surfaces belong to an output, not a workspace, so a panel opened on workspace 1 stayed on screen after switching to workspace 2, over its windows, and still took every key. And only one panel could be open: picking an app in the launcher, then clicking quick settings on the bar, closed the launcher. The user asked for panels that stay where they were opened and for several at once.

What sway 1.12 (SwayFX 0.6) does with a layer surface's keyboard, measured in a headless sway:

- **exclusive**: it gets the keyboard as it maps and keeps it; a click on a window gives the window the keyboard for an instant and takes it straight back (the panel sees a leave and an enter in the same event batch).
- **on demand**: it gets the keyboard as it maps and loses it at once, because mapping re-lays the layers and a re-layout drops an on-demand surface's focus whenever no surface is exclusive (`arrange_layers`). Going exclusive then on demand loses it the same way. Only a click gives it the keyboard, until the next re-layout (any layer surface changing, a notification popup appearing).
- **none**: never given the keyboard, but it still gets the pointer.
- On a workspace with no window, a surface that gives the keyboard up keeps it: sway has nothing to hand it to.

## Decision

**Where.** A pure model (`vyom/places.py`) knows each open panel's workspace and slot and who has the keyboard; `app.py` feeds it what sway says and what you do and applies the result. A panel opens on the focused workspace, on that workspace's output (gtk4-layer-shell `set_monitor`). Sway is followed in-process (`vyom/sway.py`): one socket on `$SWAYSOCK`, subscribed to `workspace`, `output` and `shutdown`, read by a GLib fd watch, so Vyom wakes only when sway says something changed. A focus event is applied from its own payload at once, then the workspace list (one `GET_WORKSPACES`) corrects it; a burst of events asks once. A panel whose workspace leaves the screen is **parked**: hidden, nothing reset (no `closed()`, no `opened()`), and shown again unchanged when the workspace comes back; a workspace moved to another output takes its panels along. Without sway (no socket, another compositor) every panel counts as on one workspace.

**Slots.** A panel's slot is the centre, or the corner or edge it anchors to (kendra: top-right); `[plugin.<name>] slot` (or a tool's `slot`) overrides it. Panels in different slots are open side by side; opening one into a taken slot parks the occupant as **covered**: its key brings it back as it was (and covers the other in turn). Closing a panel never brings back the one it covered, except for a transient picker (below), which is a popup over it.

**Never covered.** Panels shown side by side never cover each other: on each output, a centre panel that an edge or corner panel would overlap moves into the free area beside it (`places.clear_of`: centred there, a 12 px gap from the edge panel and the screen), anchored to the left (and the top, for a top or bottom edge panel) with layer-shell margins. Only when that area is narrower than the panel does it get narrower, never below 640 px (below that it overlaps rather than become unusable). It goes back to its own place and size as soon as the edge panel closes or is parked. The move is instant, one commit with the new margins: a slide would cost a frame clock tick per frame while it runs, and the panel lands where you look within the frame the edge panel appears. On the user's 1920x1080 (scale 1.25): the launcher, 1125 px wide, sat at x 398-1523 under quick settings (x 1474-1912); beside it now it sits at x 174-1299, the same width, 175 px clear. On 1280x800 it narrows to about 806 px.

**Stacking.** Sway stacks layer surfaces in the order it got them, not the order they show; a surface moved to another layer goes on top of it. So a panel that takes the keyboard while another shows (opened, or clicked) spends one frame on the top layer and goes back to the overlay, on top.

**Keyboard.** The panel with the keyboard is exclusive; every other panel shown takes none. It's the panel opened last; a click (or tap) on another panel makes that one exclusive (a capture-phase `GestureClick`, so the keyboard follows the click within a frame). A click on a window shows up as the blip above: the panel lets go (keyboard none) and sway gives the window the keyboard; the panels stay open and quieter. Esc and a tool's `close()` close only their own panel, then the keyboard goes to the panel that had it before, if one shows; a tool's key toggles only that panel. Leaving a workspace remembers who had the keyboard (the blip of the switch itself, heard just before sway's event, doesn't count as a window taking it) and coming back gives it back. Where sway leaves the keyboard on a panel that let it go (no window to take it), that panel stays the one with the keyboard, so the lit glass never lies. For a quarter of a second after Vyom changes a panel's keyboard mode or shows or hides one, focus notices are its own and ignored.

**Look.** The panel with the keyboard is the glass above, with its lit rim and top edge, a step brighter while other panels show (`.vyom-panel.lit`); the others drop the rim and top light and flatten the gradient (`.vyom-panel.away`), their text unchanged. No ring, no glow, no colour.

**Transient.** `vyom dmenu`'s picker (`transient = True`, or `[plugin.<name>] transient`) never stays behind: it closes, answering nothing, when it loses the keyboard, is covered, or its workspace is left, and a panel it covered comes back. No other panel closes on losing focus: none did before (exclusive panels never lost it), and a panel left open is meant to be open.

**Tools.** Two optional hooks: `parked()` when the panel hides without closing, `unparked()` when it shows again. Timers that stop by themselves while a panel is hidden (they check `panel.get_visible()`) restart there; scans and fast readings pause. Core restarts a list's `live` refresh itself.

## Consequences

- A panel never follows you to another workspace, and comes back exactly as you left it; each workspace keeps its own. Key to first frame is unchanged (headless, kept panels: launcher 13 ms median before and after, quick settings 15 -> 11 ms); unparking a kept panel is as quick as opening it (it keeps its surface; a rarely used one may have released it, ADR 11).
- No new wakeups: the IPC socket is quiet until sway sends an event. Switching workspaces costs one IPC round trip and a map or unmap per panel.
- Panels shown together never overlap down to a 640 px centre panel; below that (a very small screen) they can, and the one with the keyboard is drawn on top (a click raises it, like a window). The same rule holds for any edge slot (left, bottom, top).
- A panel parked on another workspace and opened again here opens fresh (`closed()`, then `opened()`): a panel is one window, so it can't be in two places.
- Sway shows the switch for a frame before Vyom hides the old workspace's panels (layer surfaces aren't part of the workspace); a workspace moved to another output reappears there after sway's own interim focus change.
- Every tool keeps working unchanged; those whose timers stop when hidden (tarang, kendra) or that pause something global while open (akashvani holds popups back) implement the hooks.
