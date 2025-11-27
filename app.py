# app_with_admin.py
import os
import sqlite3
import html
import io
import csv
from datetime import datetime
from flask import Flask, request, Response, make_response, abort

app = Flask(__name__)

# -------- CONFIG --------
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "changeme")  # set this to a strong secret on Render
DB_PATH = "events.db"

# -------- DATABASE SETUP --------
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS opens (
            id TEXT,
            ts TEXT,
            remote_addr TEXT,
            x_forwarded_for TEXT,
            real_ip TEXT,
            user_agent TEXT,
            referer TEXT
        )
    """)
    conn.commit()
    conn.close()

init_db()

def get_db():
    return sqlite3.connect(DB_PATH)

# -------- UTIL: get real IP from headers --------
def get_real_ip():
    """
    Prefer X-Forwarded-For's first entry (the client's public IP).
    Fallback to request.remote_addr if header not present.
    """
    raw_xff = request.headers.get("X-Forwarded-For", "")
    if raw_xff:
        # X-Forwarded-For can be comma-separated. First entry is client's IP.
        real_ip = raw_xff.split(",")[0].strip()
    else:
        raw_xff = ""
        real_ip = request.remote_addr or ""
    return raw_xff, real_ip

# -------- TRANSPARENT GIF BYTES (1x1) --------
TRANSPARENT_GIF = (
    b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00"
    b"\xff\xff\xff!\xf9\x04\x01\x00\x00\x00\x00,"
    b"\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02"
    b"D\x01\x00;"
)

# -------- PIXEL ENDPOINT --------
@app.route("/pixel.gif")
def pixel():
    """
    Tracking pixel endpoint.
    Example: /pixel.gif?id=123
    Stores:
      - id (from query)
      - ts (UTC)
      - remote_addr (Flask's remote_addr)
      - x_forwarded_for (raw header)
      - real_ip (first IP from X-Forwarded-For or remote_addr)
      - user_agent
      - referer
    """
    user_id = request.args.get("id", "")

    raw_xff, real_ip = get_real_ip()
    remote_addr = request.remote_addr or ""
    user_agent = request.headers.get("User-Agent", "")
    referer = request.headers.get("Referer", "")

    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO opens (id, ts, remote_addr, x_forwarded_for, real_ip, user_agent, referer) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            user_id,
            datetime.utcnow().isoformat() + "Z",
            remote_addr,
            raw_xff,
            real_ip,
            user_agent,
            referer,
        ),
    )
    conn.commit()
    conn.close()

    # Return 1x1 transparent GIF with cache headers (providers may ignore)
    resp = make_response(TRANSPARENT_GIF)
    resp.headers["Content-Type"] = "image/gif"
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    return resp

# -------- ADMIN AUTH CHECK --------
def require_admin():
    token = request.args.get("token", "")
    if ADMIN_TOKEN == "changeme" or not ADMIN_TOKEN:
        app.logger.warning("ADMIN_TOKEN is not set or left as default. Set ADMIN_TOKEN in environment for security.")
    if token != ADMIN_TOKEN:
        abort(401)

# -------- ADMIN PAGE (last 100 opens) --------
@app.route("/admin")
def admin_page():
    require_admin()
    filter_id = request.args.get("id")

    conn = get_db()
    cur = conn.cursor()
    if filter_id:
        cur.execute(
            "SELECT rowid, id, ts, remote_addr, x_forwarded_for, real_ip, user_agent, referer FROM opens WHERE id = ? ORDER BY ts DESC LIMIT 100",
            (filter_id,),
        )
    else:
        cur.execute(
            "SELECT rowid, id, ts, remote_addr, x_forwarded_for, real_ip, user_agent, referer FROM opens ORDER BY ts DESC LIMIT 100"
        )
    rows = cur.fetchall()
    conn.close()

    # Build HTML safely (escape values)
    rows_html = []
    for row in rows:
        rowid, uid, ts, remote_addr, xff, real_ip, ua, referer = row
        rows_html.append(
            "<tr>"
            f"<td>{html.escape(str(rowid))}</td>"
            f"<td>{html.escape(uid or '')}</td>"
            f"<td>{html.escape(ts or '')}</td>"
            f"<td>{html.escape(remote_addr or '')}</td>"
            f"<td>{html.escape(xff or '')}</td>"
            f"<td>{html.escape(real_ip or '')}</td>"
            f"<td>{html.escape(ua or '')}</td>"
            f"<td>{html.escape(referer or '')}</td>"
            f"<td><a href=\"/admin/delete?id={html.escape(uid or '')}&token={html.escape(ADMIN_TOKEN)}\" onclick=\"return confirm('Delete records for id={html.escape(uid or '')}?')\">Delete ID</a></td>"
            "</tr>"
        )

    filter_value = html.escape(filter_id or "")
    token_param = html.escape(ADMIN_TOKEN)

    page = f"""<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <title>Pixel Tracker — Admin</title>
    <style>
      body {{ font-family: system-ui, -apple-system, Roboto, 'Segoe UI', Arial, sans-serif; padding: 1rem; }}
      table {{ border-collapse: collapse; width: 100%; max-width: 1200px; }}
      th, td {{ border: 1px solid #ddd; padding: 6px 8px; text-align: left; font-size: 13px; vertical-align: top; }}
      th {{ background: #f6f6f6; }}
      tr:nth-child(even) {{ background: #fafafa; }}
      .meta {{ margin-bottom: 1rem; }}
      .actions {{ margin-bottom: 0.75rem; }}
    </style>
  </head>
  <body>
    <h1>Pixel Tracker — Recent Opens</h1>
    <div class="meta">Showing {len(rows)} rows (most recent). <a href="/admin/download?token={token_param}">Download CSV</a></div>
    <div class="actions">
      <form method="GET" action="/admin" style="display:inline;">
        <input type="hidden" name="token" value="{token_param}" />
        Filter id: <input name="id" value="{filter_value}" /> <button type="submit">Filter</button>
        <a href="/admin?token={token_param}">Clear</a>
      </form>
      &nbsp;&nbsp;
      <a href="/admin/clear?token={token_param}" onclick="return confirm('Delete ALL records? This cannot be undone.')">🗑️ Delete ALL Records</a>
    </div>

    <table>
      <thead>
        <tr>
          <th>rowid</th><th>id</th><th>ts (UTC)</th><th>remote_addr</th><th>X-Forwarded-For</th><th>real_ip</th><th>user_agent</th><th>referer</th><th>action</th>
        </tr>
      </thead>
      <tbody>
        {''.join(rows_html)}
      </tbody>
    </table>
  </body>
</html>"""
    return Response(page, mimetype="text/html")

# -------- CSV EXPORT --------
@app.route("/admin/download")
def admin_download():
    require_admin()
    filter_id = request.args.get("id")

    conn = get_db()
    cur = conn.cursor()
    if filter_id:
        cur.execute(
            "SELECT id, ts, remote_addr, x_forwarded_for, real_ip, user_agent, referer FROM opens WHERE id = ? ORDER BY ts DESC",
            (filter_id,),
        )
    else:
        cur.execute(
            "SELECT id, ts, remote_addr, x_forwarded_for, real_ip, user_agent, referer FROM opens ORDER BY ts DESC"
        )
    rows = cur.fetchall()
    conn.close()

    # Build CSV
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["id", "ts", "remote_addr", "x_forwarded_for", "real_ip", "user_agent", "referer"])
    for r in rows:
        writer.writerow([r[0] or "", r[1] or "", r[2] or "", r[3] or "", r[4] or "", r[5] or "", r[6] or ""])

    resp = Response(output.getvalue(), mimetype="text/csv")
    resp.headers["Content-Disposition"] = "attachment; filename=opens.csv"
    return resp

# -------- DELETE ALL RECORDS --------
@app.route("/admin/clear")
def admin_clear():
    require_admin()
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM opens")
    conn.commit()
    conn.close()
    return f"<h2>All records deleted.</h2><a href='/admin?token={html.escape(ADMIN_TOKEN)}'>Back to Admin</a>"

# -------- DELETE BY ID --------
@app.route("/admin/delete")
def admin_delete_by_id():
    require_admin()
    delete_id = request.args.get("id")
    if not delete_id:
        return "Missing id", 400
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM opens WHERE id = ?", (delete_id,))
    conn.commit()
    conn.close()
    return f"<h2>Deleted records for id={html.escape(delete_id)}</h2><a href='/admin?token={html.escape(ADMIN_TOKEN)}'>Back to Admin</a>"

# -------- ROOT --------
@app.route("/")
def index():
    return "Pixel tracker running."

# -------- RUN (local) --------
if __name__ == "__main__":
    # For local testing, optionally set ADMIN_TOKEN env var before running.
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
