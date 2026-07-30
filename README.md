# smart-analytics

Minimal, privacy-focused web analytics. Self-hosted, no cookies, no tracking IDs.

![Dashboard](docs/dashboard.png)

## Quick Start

```bash
# Install
uv tool install smart-analytics

# Configure (create a .env file or set environment variables)
export TINY_ANALYTICS_PASSWORD="your-secret-password"
export TINY_ANALYTICS_SECRET_KEY="$(openssl rand -hex 32)"

# Run
smart-analytics
```

Add this to your site:
```html
<script src="https://your-analytics-domain/snippet.js" defer></script>
```

That's it. View your dashboard at `http://localhost:8000/`.

### One-liner (no install)

```bash
uvx smart-analytics
```

### From source

```bash
git clone https://github.com/fireboltby/smart-analytics.git
cd smart-analytics
uv sync
uv run smart-analytics
```

<details>
<summary>Using pip instead of uv</summary>

```bash
pip install smart-analytics
smart-analytics
```

Or from source:
```bash
git clone https://github.com/fireboltby/smart-analytics.git
cd smart-analytics
python -m venv .venv && source .venv/bin/activate
pip install -e .
smart-analytics
```
</details>

---

## Features

- **Privacy-first**: No cookies, no fingerprinting, no personal data stored
- **Lightweight**: Single Python file + templates
- **Bot filtering**: Automatic detection and separation of bot traffic
- **Time on page**: Tracks actual engagement, not just page loads
- **Geo & device breakdown**: See where your visitors come from and what they use
- **Dark mode UI**: Easy on the eyes

## Screenshots

<details>
<summary>Login</summary>

![Login](docs/login.png)
</details>

<details>
<summary>Logs view</summary>

![Logs](docs/logs.jpg)
</details>

## How It Works

1. **Visitor hits your page** → snippet.js fires a POST to `/t`
2. **Server hashes IP+UA** → creates anonymous visitor ID (never stored raw)
3. **On page leave** → beacon sends time-on-page to `/d`
4. **Dashboard** → aggregates and visualizes the data

No cookies. No localStorage. No tracking across sites.

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `TINY_ANALYTICS_PASSWORD` | `changeme` | Dashboard login password |
| `TINY_ANALYTICS_SECRET_KEY` | `change-this...` | Session signing key (generate a random string) |
| `TINY_ANALYTICS_ALLOWED_ORIGINS` | `[]` | Restrict tracking to specific domains (empty = allow all) |
| `TINY_ANALYTICS_DB_PATH` | `./tiny_analytics.db` | SQLite database location |
| `TINY_ANALYTICS_HOST` | `0.0.0.0` | Host to bind to |
| `TINY_ANALYTICS_PORT` | `8000` | Port to listen on |

## Deployment

### Systemd

```ini
[Unit]
Description=smart-analytics
After=network.target

[Service]
User=www-data
WorkingDirectory=/opt/smart-analytics
Environment="TINY_ANALYTICS_PASSWORD=your-password"
Environment="TINY_ANALYTICS_SECRET_KEY=your-secret-key"
ExecStart=/usr/local/bin/smart-analytics
Restart=always

[Install]
WantedBy=multi-user.target
```

### Behind nginx

```nginx
location / {
    proxy_pass http://127.0.0.1:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

### Cloudflare

smart-analytics reads `cf-connecting-ip` and `cf-ipcountry` headers automatically for accurate geo and IP data behind Cloudflare.

## CLI Options

```
smart-analytics [OPTIONS]

Options:
  --host TEXT     Host to bind to [default: 0.0.0.0]
  --port INTEGER  Port to listen on [default: 8000]
  --help          Show this message and exit
```

## API

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/t` | POST | Record a pageview |
| `/d` | POST | Update time-on-page |
| `/snippet.js` | GET | Tracking script |
| `/` | GET | Dashboard (auth required) |
| `/logs` | GET | Raw logs view (auth required) |

## License

MIT
