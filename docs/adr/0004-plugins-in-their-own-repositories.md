# 4. Every tool is its own repository

**Status:** Accepted  
**Date:** 2026-10-19

## Context

Bundling all tools in Vyom would force every user to take all fourteen, tie every tool's releases together, and blur the line between the runtime and its users.

## Decision

Vyom holds only the runtime and the plugin API. Each tool lives in its own repository and is cloned into `~/.local/share/vyom/plugins/<name>`. The API changes only compatibly; a tool declares the oldest Vyom it needs in `plugin.toml`, and `vyom list` explains why a tool is skipped.

## Consequences

- Users install only what they want; tools release on their own schedule.
- The API is a contract with many repositories: removing or changing a hook is a breaking change across all of them.
