"""
0Lith Cyber Range — Intentionally Vulnerable Web Application
=============================================================
Flask app avec vulnérabilités contrôlées via env vars pour simulations
Purple Team. NE JAMAIS déployer en production ou sur un réseau accessible.

Variables d'environnement :
    VULN_SQLI        : true/false — SQLi sur /search (défaut: true)
    VULN_XSS         : true/false — XSS réfléchi sur /comment (défaut: true)
    VULN_AUTH_BYPASS : true/false — /admin sans auth (défaut: true)
    ACCESS_LOG_PATH  : chemin du log d'accès (défaut: /var/log/webapp.log)
    FLAG_VALUE       : valeur du flag (injecté par Purple/scenario_generator)

Vecteurs d'exploitation :
    SQLi  → /search?q=' UNION SELECT 1,flag_value,1,1 FROM flags --
    XSS   → /comment?text=<script>alert(document.cookie)</script>
    Auth  → /admin  (pas d'en-tête Authorization requis)
"""

from __future__ import annotations

import html as html_mod
import logging
import os
import sqlite3
import time
from datetime import datetime, timezone
from flask import Flask, g, request, Response

# ---------------------------------------------------------------------------
# Configuration depuis env vars
# ---------------------------------------------------------------------------

VULN_SQLI        = os.environ.get("VULN_SQLI",        "true").lower() == "true"
VULN_XSS         = os.environ.get("VULN_XSS",         "true").lower() == "true"
VULN_AUTH_BYPASS = os.environ.get("VULN_AUTH_BYPASS",  "true").lower() == "true"
ACCESS_LOG_PATH  = os.environ.get("ACCESS_LOG_PATH",   "/var/log/webapp.log")
FLAG_VALUE       = os.environ.get("FLAG_VALUE",         "FLAG{0lith_cyber_range_pwned}")

DB_PATH       = "/tmp/webapp.db"
MAX_QUERY_LEN = 500
ADMIN_TOKEN   = "Bearer admin-token-2024"

# ---------------------------------------------------------------------------
# Logging (Apache Combined Log Format → fichier + stderr)
# ---------------------------------------------------------------------------

logging.basicConfig(level=logging.INFO, format="%(message)s")
access_logger = logging.getLogger("access")
access_logger.propagate = False

try:
    _fh = logging.FileHandler(ACCESS_LOG_PATH)
except (PermissionError, OSError):
    _fh = logging.StreamHandler()

access_logger.addHandler(_fh)
access_logger.addHandler(logging.StreamHandler())

# ---------------------------------------------------------------------------
# Base de données SQLite (fichier dans tmpfs /tmp)
# ---------------------------------------------------------------------------

def init_db() -> None:
    """Crée les tables et insère les données factices + flag caché."""
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(f"""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            username TEXT NOT NULL,
            password TEXT NOT NULL,
            role     TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS products (
            id          INTEGER PRIMARY KEY,
            name        TEXT NOT NULL,
            price       REAL NOT NULL,
            description TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS flags (
            id         INTEGER PRIMARY KEY,
            flag_value TEXT NOT NULL
        );
        DELETE FROM users;
        DELETE FROM products;
        DELETE FROM flags;
        INSERT INTO users VALUES (1, 'admin',   'Adm1n@C0mp4ny!',  'admin');
        INSERT INTO users VALUES (2, 'alice',   'alice2024!',       'user');
        INSERT INTO users VALUES (3, 'bob',     'b0bRul3s99',       'user');
        INSERT INTO users VALUES (4, 'charlie', 'charlie_pass',     'user');
        INSERT INTO products VALUES (1, 'Laptop Pro',         1299.99, 'High-performance laptop');
        INSERT INTO products VALUES (2, 'Wireless Mouse',       29.99, 'Ergonomic wireless mouse');
        INSERT INTO products VALUES (3, 'Mechanical Keyboard',  89.99, 'RGB mechanical keyboard');
        INSERT INTO products VALUES (4, 'USB-C Hub',            49.99, '7-in-1 USB-C hub');
        INSERT INTO products VALUES (5, 'Monitor 27in',        399.99, '4K IPS monitor');
        INSERT INTO flags VALUES (1, '{FLAG_VALUE}');
    """)
    conn.commit()
    conn.close()


def get_db() -> sqlite3.Connection:
    """Connexion SQLite par requête Flask (thread-safe via app context)."""
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


# ---------------------------------------------------------------------------
# Flask app
# ---------------------------------------------------------------------------

app = Flask(__name__)


@app.teardown_appcontext
def close_db(_: Exception | None = None) -> None:
    db = g.pop("db", None)
    if db is not None:
        db.close()


@app.before_request
def _start_timer() -> None:
    g.start_time = time.time()


@app.after_request
def _log_access(response: Response) -> Response:
    """Log Apache-like après chaque requête."""
    duration_ms = int((time.time() - g.get("start_time", time.time())) * 1000)
    ts = datetime.now(timezone.utc).strftime("%d/%b/%Y:%H:%M:%S +0000")
    line = (
        f'{request.remote_addr} - - [{ts}] '
        f'"{request.method} {request.full_path.rstrip("?")} HTTP/1.1" '
        f'{response.status_code} {response.content_length or 0} {duration_ms}ms'
    )
    access_logger.info(line)
    return response


# ---------------------------------------------------------------------------
# HTML helpers
# ---------------------------------------------------------------------------

_CSS = """
<style>
  body { font-family: monospace; background:#1a1a2e; color:#e0e0e0; padding:20px; }
  h1   { color:#e94560; }
  a    { color:#0f3460; background:#e94560; padding:4px 8px;
         text-decoration:none; border-radius:3px; margin-right:4px; }
  table { border-collapse:collapse; width:100%; margin-top:10px; }
  th,td { border:1px solid #333; padding:8px; text-align:left; }
  th    { background:#16213e; }
  .tag-on  { color:#ff6b6b; font-size:12px; }
  .tag-off { color:#51cf66; font-size:12px; }
  form  { margin:10px 0; }
  input, textarea { background:#16213e; color:#e0e0e0; border:1px solid #0f3460; padding:6px; }
  .flag { color:#ffd700; background:#333; padding:4px 8px; }
</style>
"""


def _page(title: str, body: str) -> str:
    tags = " ".join([
        f'<span class="tag-on">[SQLi ON]</span>'  if VULN_SQLI        else '<span class="tag-off">[SQLi OFF]</span>',
        f'<span class="tag-on">[XSS ON]</span>'   if VULN_XSS         else '<span class="tag-off">[XSS OFF]</span>',
        f'<span class="tag-on">[Auth OFF]</span>' if VULN_AUTH_BYPASS  else '<span class="tag-off">[Auth ON]</span>',
    ])
    nav = '<a href="/">Home</a> <a href="/products">Products</a> <a href="/search">Search</a> <a href="/comment">Comment</a> <a href="/admin">Admin</a>'
    return f"<!DOCTYPE html><html><head><title>{title}</title>{_CSS}</head><body><h1>0Lith Test Shop</h1><p>{nav}</p><p>{tags}</p><hr>{body}</body></html>"


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/health")
def health() -> Response:
    return Response('{"status":"ok","service":"vuln-webapp"}', content_type="application/json")


@app.route("/")
def index() -> str:
    return _page("Home", "<h2>Welcome to 0Lith Test Shop</h2><p>An intentionally vulnerable web app for Purple Team training.</p>")


@app.route("/products")
def products() -> str:
    rows = get_db().execute("SELECT id,name,price,description FROM products ORDER BY id").fetchall()
    trs = "".join(f"<tr><td>{r[0]}</td><td>{r[1]}</td><td>${r[2]:.2f}</td><td>{r[3]}</td></tr>" for r in rows)
    return _page("Products", f"<h2>Product Catalog</h2><table><tr><th>ID</th><th>Name</th><th>Price</th><th>Description</th></tr>{trs}</table>")


@app.route("/search")
def search() -> str:
    """
    VULN_SQLI=true : concaténation directe dans la requête SQL.
    Payload : /search?q=' UNION SELECT 1,flag_value,1,1 FROM flags --
    """
    q = request.args.get("q", "").strip()

    form = '<form action="/search" method="get"><input type="text" name="q" placeholder="Search products..." size="40"><input type="submit" value="Search"></form>'

    if not q:
        return _page("Search", f"<h2>Product Search</h2>{form}")
    if len(q) > MAX_QUERY_LEN:
        return _page("Search", "<p>Query too long.</p>"), 400

    db = get_db()

    if VULN_SQLI:
        # VULN: string concat — SQLi possible
        raw_sql = f"SELECT id,name,price,description FROM products WHERE name LIKE '%{q}%'"
        try:
            rows = db.execute(raw_sql).fetchall()
        except sqlite3.OperationalError as e:
            return _page("Search", f"<p>DB error: {html_mod.escape(str(e))}</p>"), 500
    else:
        # SAFE: parameterized query
        rows = db.execute(
            "SELECT id,name,price,description FROM products WHERE name LIKE ?",
            (f"%{q}%",),
        ).fetchall()

    trs = "".join(f"<tr><td>{r[0]}</td><td>{r[1]}</td><td>{r[2]}</td><td>{r[3]}</td></tr>" for r in rows) \
          or "<tr><td colspan='4'>No results.</td></tr>"
    return _page("Search", f"<h2>Results for: <em>{html_mod.escape(q)}</em></h2>{form}<table><tr><th>ID</th><th>Name</th><th>Price</th><th>Description</th></tr>{trs}</table>")


@app.route("/comment", methods=["GET", "POST"])
def comment() -> str:
    """
    VULN_XSS=true : contenu affiché sans échappement HTML.
    Payload : /comment?text=<script>alert(document.cookie)</script>
    """
    text = (request.form if request.method == "POST" else request.args).get("text", "")
    form = '<form action="/comment" method="post"><textarea name="text" rows="4" cols="60" placeholder="Write your comment..."></textarea><br><br><input type="submit" value="Post Comment"></form>'
    display = ""

    if text:
        content = text if VULN_XSS else html_mod.escape(text)  # VULN or SAFE
        display = f'<p>Comment posted!</p><div style="border:1px solid #444;padding:10px;margin:10px 0">{content}</div>'

    return _page("Comments", f"<h2>Leave a Comment</h2>{form}{display}")


@app.route("/admin")
def admin() -> str | tuple:
    """
    VULN_AUTH_BYPASS=true : accessible sans authentification.
    VULN_AUTH_BYPASS=false : requiert Authorization: Bearer admin-token-2024
    """
    if not VULN_AUTH_BYPASS:
        if request.headers.get("Authorization", "") != ADMIN_TOKEN:
            return _page("Admin — Forbidden", "<h2>403 Forbidden</h2>"), 403

    db    = get_db()
    users = db.execute("SELECT id,username,password,role FROM users ORDER BY id").fetchall()
    flags = db.execute("SELECT flag_value FROM flags").fetchall()

    trs      = "".join(f"<tr><td>{u[0]}</td><td>{u[1]}</td><td>{u[2]}</td><td>{u[3]}</td></tr>" for u in users)
    flags_html = "".join(f'<p class="flag">{f[0]}</p>' for f in flags)
    return _page(
        "Admin Panel",
        f"<h2>Admin Panel</h2><h3>Users</h3><table><tr><th>ID</th><th>Username</th><th>Password</th><th>Role</th></tr>{trs}</table><h3>Flags</h3>{flags_html}",
    )


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=8080, threaded=True)
