# Cloudflare Multi Dynamic DNS

A Home Assistant custom integration that keeps **A / AAAA DNS records across
multiple Cloudflare zones (domains)** in sync with your changing external IP
address — a multi-domain alternative to the built-in Cloudflare integration.

Watches your public IPv4/IPv6 and, whenever it changes, updates every record
you configured (spread over as many domains as you like) through the Cloudflare
REST API v4.

## Features

- **Multiple domains / zones in one config entry** — add as many records as you
  want, across different Cloudflare zones.
- Authentication with a scoped **API Token** (no Global API Key).
- Updates existing A / AAAA records only (never creates or deletes records).
- Leaves TTL, proxy status (orange cloud) and comments untouched.
- A sensor per record + external IPv4/IPv6 sensors, with previous-IP history
  that survives restarts.
- Optional notifications: a persistent notification, a `cloudflare_multi_updated`
  event, and/or direct `notify.*` targets (e.g. mobile push).

## Installation

### HACS (recommended)

1. HACS → Integrations → three-dot menu → **Custom repositories**.
2. Add `https://github.com/joohann/cloudflare-multi-ddns` as an **Integration**.
3. Install **Cloudflare Multi Dynamic DNS** and restart Home Assistant.

### Manual

Copy the `custom_components/cloudflare_multi` folder into your Home Assistant
`config/custom_components/` directory and restart.

## Configuration

1. Create an API Token in the Cloudflare dashboard: **My Profile → API Tokens →
   Create Token**. Give it:
   - **Zone → DNS → Edit**
   - **Zone → Zone → Read**
   - scoped to the zones you want to manage (or all zones).
2. In Home Assistant: **Settings → Devices & Services → Add Integration →
   Cloudflare Multi Dynamic DNS**.
3. Paste the API Token, then add one or more DNS records:
   - **Zone / domain** — e.g. `example.com`
   - **Record name** — `@` for the root, or a subdomain like `www` / `home`
   - **Record type** — `A` (IPv4) or `AAAA` (IPv6)
   - tick **Add another record** to add more (also across other domains).

> The record must already exist in the Cloudflare zone. This integration only
> updates the content of existing records; create them once in the dashboard.

Use the integration's **Configure** button afterwards to add/remove records,
change the check interval, or adjust notification settings.

## Notes

- Records are matched by their full name (FQDN) and type per zone.
- The check interval defaults to 10 minutes (minimum 2).
- Requires no extra Python dependencies.

## Repository layout (for publishing)

```
cloudflare-multi-ddns/
├── hacs.json
├── README.md
└── custom_components/
    └── cloudflare_multi/
        ├── __init__.py
        ├── api.py
        ├── config_flow.py
        ├── const.py
        ├── coordinator.py
        ├── manifest.json
        ├── sensor.py
        ├── strings.json
        └── translations/
```

`hacs.json` and `README.md` belong in the **repository root**, not inside
`custom_components/cloudflare_multi/`.
