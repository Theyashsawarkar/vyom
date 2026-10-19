# Vyom -- notes for agents

Vayu's system panels and launcher, replacing wofi, built in stages
(README "Roadmap"). Python + GTK 4 + gtk4-layer-shell. Its own repo,
pulled into Vayu (github.com/Theyashsawarkar/vayu, whose CLAUDE.md
"Plugins" rules apply): it must work on any layer-shell compositor without
Vayu. Vayu-specific behaviour only through ~/.config/vyom/config.toml
(Vayu ships its own in its `vyom/` stow package).

- `bin/vyom` is the launcher: with Vyom running it only sends a D-Bus
  action (org.gtk.Actions on dev.vayu.Vyom), no GTK; otherwise it re-execs
  itself with gtk4-layer-shell in LD_PRELOAD (required before GTK loads)
  and starts `vyom.app`.
- `vyom/app.py` is the single-instance Gtk.Application (stays resident);
  each mode is a window it owns. `vyom/system.py` reads/changes the
  system; `vyom/quick.py` is the quick settings panel; `style.css` the look.
- Never block the GTK main loop on a command: run it in a thread
  (`panel.background(work, then=...)`) and touch widgets only in `then`.
- Detect, don't assume: a tile/slider/button whose tool or hardware is
  missing must not show (`available()`), and it must still start.
- Every key in a panel has a `# keybind: Vyom/<scope> | <keys> | <Verb> ...`
  line (Vayu's keybinding search reads them) and is listed in the README.
- Every change: CHANGELOG.md entry; releases are tags with `VERSION` in
  `vyom/__init__.py` bumped. `python -m py_compile vyom/*.py bin/vyom`
  must pass.
- Test with a real compositor: `bin/vyom quit; bin/vyom quick`, then
  screenshot the panel (`grim -g "1460,40 460x480" shot.png` on a 1920
  wide screen) and check it; `vyom quit` when done.
