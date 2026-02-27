# Security model

- Gateway binds to `127.0.0.1` on VPS; not exposed publicly.
- Windows node connects via SSH local port-forward.
- Explicit user consent: node/hotkeys allow immediate stop.
- No secrets in repo; env-based configuration.

