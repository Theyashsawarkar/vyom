# Vyom -- notes for agents

The runtime for Vayu's panels (the wofi replacement). Python + GTK 4 +
gtk4-layer-shell. Its own repo, pulled into Vayu (github.com/Theyashsawarkar/vayu,
whose CLAUDE.md "Plugins" rules apply). Each tool (dvara, ganit, smriti,
bhava, tarang, setu, doot, patra, suchana, raga, mudra, urja, vishram,
kendra) is a separate repo: never put a tool's code here. Vyom must work
on any layer-shell compositor without Vayu.

- `bin/vyom` is the launcher: with Vyom running it only sends a D-Bus
  action (org.gtk.Actions on dev.vayu.Vyom: open, dmenu, close, reload,
  quit), no GTK; `vyom daemon` re-execs itself with gtk4-layer-shell in
  LD_PRELOAD (required before GTK loads) and starts `vyom.app`.
- `vyom/app.py`: the single-instance Gtk.Application (stays resident),
  plugin loading, the built-in `dmenu` tool. `vyom/panel.py`: the one
  window class every tool shows in. `vyom/plugin.py`: the API (Row,
  Section, Hint, Plugin). `vyom/ui.py` / `vyom/util.py`: helpers.
  `vyom/style.css`: the shared look (tools add their own style.css).
- The API is a contract with 14 repos: change it compatibly (new optional
  hooks/attributes), and bump `vyom` in tools' plugin.toml when they need
  something new.
- Never block the GTK main loop on a command: search() runs in a thread;
  everything else uses panel.background(work, then) and touches widgets
  only in `then`.
- Every key has a `# keybind: Vyom/<scope> | <keys> | <Verb> ...` line
  (Vayu's keybinding search reads them) and is in the README.
- Every change: CHANGELOG.md entry; releases are tags with `VERSION` in
  `vyom/__init__.py`. `python -m py_compile vyom/*.py bin/vyom` must pass.
- Test live: tools linked into ~/.local/share/vyom/plugins; `bin/vyom quit;
  bin/vyom <tool>`, screenshot (grim), close it; `grep Traceback
  ~/.local/state/vyom/daemon.log`.
