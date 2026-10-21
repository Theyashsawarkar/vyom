# Contributing to Vyom

Thanks for wanting to make Vyom better. Bug reports, ideas and pull
requests are all welcome. A problem with a single tool (dvara, ganit…)
belongs in that tool's repository; this one is the runtime every tool
shares: the daemon, the panel, the plugin API, theming and `vyom dmenu`.

## Development setup

```sh
git clone https://github.com/Theyashsawarkar/vyom ~/code/vyom
ln -sfn ~/code/vyom ~/.local/share/vyom/core
ln -sfn ~/code/vyom/bin/vyom ~/.local/bin/vyom
vyom quit; vyom dvara          # restart the daemon with your code
grep -A20 Traceback ~/.local/state/vyom/daemon.log
python -m py_compile vyom/*.py bin/vyom
```

## How it fits together

- `bin/vyom`: the launcher. With the daemon running it only sends a D-Bus
  action (`org.gtk.Actions` on `dev.vayu.Vyom`), so it never loads GTK.
- `vyom/app.py`: the resident single-instance `Gtk.Application`, plugin
  loading, the built-in `dmenu` tool.
- `vyom/panel.py`: the one window class every tool shows in.
- `vyom/plugin.py`: the API (`Plugin`, `Row`, `Section`, `Hint`).
- `vyom/ui.py`, `vyom/util.py`: helpers for tools; `vyom/style.css`: the look.

## Rules

- **The plugin API is a contract with every tool repository.** Change it
  compatibly (new optional hooks and attributes), and say in the changelog
  which Vyom version a tool needs for something new.
- **Never block the GTK main loop.** `search()` runs in a worker thread;
  everything else slow goes through `panel.background(work, then)`.
- **Every key is discoverable**: a `# keybind: Vyom/<scope> | <keys> | <Verb> ...`
  line next to it and a mention in the README.
- **Works on any layer-shell compositor**, without Vayu.
- Every change gets a `CHANGELOG.md` entry; releases are tags `vX.Y.Z` with
  `VERSION` in `vyom/__init__.py` bumped.

## Pull requests

Keep them focused, describe what and why, and tick the checklist in the
template. By contributing you agree your work is released under the
[MIT License](LICENSE).
