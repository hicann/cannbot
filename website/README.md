# CANNBot portal

Static two-page website designed to be mounted at `/cannbot/` without changing the existing site.

```bash
python3 -m http.server 4173 --directory website
```

- Home: `http://localhost:4173/`
- Plugin documentation: `http://localhost:4173/plugin.html?id=ops-direct-invoke`

For a subpath deployment, copy the complete `website/` directory to the server's `/cannbot/` static location. All internal assets and links are relative.
