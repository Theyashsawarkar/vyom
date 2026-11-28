# 16. Every connection in the live state

**Status:** Accepted (extends ADR 12 and 13)  
**Date:** 2026-11-28

## Context

The live Wi-Fi state (ADR 12) said a great deal about the Wi-Fi card and, of everything else, only the wired connection's name (`wired`). The net history (ADR 13) kept speeds for ethernet and Wi-Fi devices only. So on a cable the Wi-Fi panel (tarang) showed a sentence in a green ring and quick settings (kendra) "Ethernet in use" over an empty chart, and a phone tethered over USB, a modem, Bluetooth or a VPN weren't there at all. The user asked for every kind of connection to look the same as Wi-Fi: its icon, name, kind, address, link speed, live speeds and graph. Docker's bridges and loopback are "connected" too (externally), and must not show.

## Decision

`live.get("wifi")` gains `connections`: every active connection NetworkManager has, worked out from the objects the one ObjectManager client already follows (no new match rule, no command, no polling), and `primary` (the UUID of NetworkManager's `PrimaryConnection`). Each says its `type` and `label` (`wifi`, `ethernet`, `usb` for a phone's RNDIS/NCM/iPhone gadget, `mobile`, `bluetooth`, `vpn`, `wireguard`, `hotspot`...; `conn_kind()`), name, interface, addresses, gateway, DNS, link speed (Wi-Fi's bitrate; `Device.Wired.Speed`, else sysfs `speed`) and duplex, MAC, driver, operator and APN for a modem, the peer for Bluetooth, the server for a VPN (from its settings: OpenVPN's remote, the others' gateway, WireGuard's endpoint). Ordered by `order_connections()`: the connection carrying the default route first, each VPN right after the connection it rides on (`via`, `via_device`). Plumbing is left out: loopback, veth, dummy, Wi-Fi P2P, Open vSwitch ports and bridges, VRF, and bridges a container runtime or VM manager made (docker0, br-<hex>, virbr0...); a bridge of your own stays.

The net history follows the same list: every interface a shown connection runs through gets its minute (a modem's `wwan0`, Bluetooth's `bnep0`, `wg0`), and `history("net")` with no device is the primary connection's.

`Panel.set_mode(icon, title)` lets a tool change its mode pill while it shows (tarang: "Network" with a cable on Ethernet).

`VYOM_SYS_NET` points the sysfs reads (counters, speed, duplex) at made-up files, for headless tests against a fake NetworkManager.

## Consequences

- Panels show any connection the same way, from memory, on the first frame (tarang, kendra); a tool reading an older Vyom finds no `connections` and keeps its old path.
- The list is part of the exported summary (`dev.vayu.Vyom.State`, `wifi.json`): a bar can draw a cable, a phone or a VPN from it. It changes only when NetworkManager says something did.
- A machine on a cable now reads its counters every 2 s as it did for Wi-Fi (ADR 13); with nothing connected, still nothing wakes.
- Modem signal and operator name live in ModemManager, which isn't followed: the operator code and APN NetworkManager has are shown instead.
