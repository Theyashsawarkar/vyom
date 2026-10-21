# Security policy

## Supported versions

Only the latest release of Vyom gets fixes.

## Reporting a vulnerability

Please **don't open a public issue**. Report it privately through
[GitHub's security advisories](https://github.com/Theyashsawarkar/Vyom/security/advisories/new),
with what an attacker could do and how to reproduce it. You'll get a reply
within a week; a fix and a release follow as soon as it's confirmed, with
credit to you unless you'd rather not.

Vyom runs as your user. It loads tools (Python code) from
`~/.local/share/vyom/plugins` and `$VYOM_PLUGIN_PATH`: install only tools you trust.
