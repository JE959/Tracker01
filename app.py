# app_with_admin.py
import base64
import sqlite3
import os
import csv
import io
from datetime import datetime
from flask import Flask, request, Response, g, abort
import html

DB_PATH = "events.db"
app = Flask(__name__)

# 1x1 transparent GIF
TRANSPARENT_GIF = base64.b64decode(
    "R0lGODlhAQABAPAAAAAAAAAAACH5BAEAAAAALAAAAAABAAEAAAICRAEAOw=="
)

# ADMIN_TOKEN should be set as an environment variable in Render
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "changeme")

def get_db():
    db = getattr(g, "_database", None)
    if db is None:
        db = g._database = sqlite3.connect(DB_PATH, detect_types=sqlite3.PARSE_DECLTYPES)
        db.execute(
            """CREATE TABLE IF NOT EXISTS opens (
                id TEXT,
                ts TEXT,
                remote_addr TEXT,
                user_agent TEXT,
                referer TEXT
            )"""
        )
        db.commit()
    return db

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, "_database", None)
    if db is not None:
        db.close()

@app.route("/pixel.gif")
def pixel():
    email_id = request.args.get("id", "")
    ts = datetime.utcnow().isoformat() + "Z"
    remote_addr = request.remote_addr or ""
    user_agent = request.headers.get("User-Agent", "")
    referer = request.headers.get("Referer", "")

    db = get_db()
    db.execute(
        "INSERT INTO opens (id, ts, remote_addr, user_agent, referer) VALUES (?, ?, ?, ?, ?)",
        (email_id, ts, remote_addr, user_agent, referer),
    )
    db.commit()

    headers = {
        "Content-Type": "image/gif",
        "Cache-Control": "no-cache, no-store, must-revalidate, max-age=0",
        "Pragma": "no-cache",
    }
    return Response(TRANSPARENT_GIF, headers=headers)

@app.route("/")
def index():
    return "Pixel tracker running."

def check_admin_token():
    token = request.args.get("token", "")
    if not ADMIN_TOKEN or ADMIN_TOKEN == "changeme":
        app.logger.warning("ADMIN_TOKEN is not set or left as default. Set ADMIN_TOKEN in environment for security.")
    if token != ADMIN_TOKEN:
        abort(401)

@app.route("/admin")
def admin():
    check_admin_token()
    filter_id = request.args.get("id")

    db = get_db()
    if filter_id:
        cur = db.execute(
            "SELECT id, ts, remote_addr, user_agent, referer FROM opens WHERE id = ? ORDER BY ts DESC LIMIT 100",
            (filter_id,),
        )
    else:
        cur = db.execute("SELECT id, ts, remote_addr, user_agent, referer FROM opens ORDER BY ts DESC LIMIT 100")
    rows = cur.fetchall()

    html_rows = []
    for r in rows:
        eid = html.escape(r[0] or "")
        ts = html.escape(r[1] or "")
        remote = html.escape(r[2] or "")
        ua = html.escape(r[3] or "")
        referer = html.escape(r[4] or "")
        html_rows.append(f"<tr><td>{eid}</td><td>{ts}</td><td>{remote}</td><td>{ua}</td><td>{referer}</td></tr>")

    download_link = f"/admin/download?token={ADMIN_TOKEN}"
    filter_form = f"<form method=GET action='/admin'>\n<input type=hidden name=token value=\"{html.escape(ADMIN_TOKEN)}\"/>\nFilter id: <input name=id value=\"{html.escape(filter_id or '')}\"/> <button type=submit>Filter</button> <a href='/admin?token={html.escape(ADMIN_TOKEN)}'>Clear</a>\n</form>"

    page = f"""
    <!doctype html>
    <html>
      <head>
        <meta charset="utf-8" />
        <title>Pixel Tracker - Admin</title>
        <style>
          body {{ font-family: system-ui, -apple-system, Roboto, 'Segoe UI', Arial, sans-serif; padding: 1rem; }}
          table {{ border-collapse: collapse; width: 100%; max-width: 1200px; }}
          th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; font-size: 13px; }}
          th {{ background: #f6f6f6; }}
          tr:nth-child(even) {{ background: #fafafa; }}
          .meta {{ margin-bottom: 1rem; }}
        </style>
      </head>
      <body>
        <h1>Pixel Tracker — Recent Opens</h1>
        <div class="meta">Showing the latest {len(rows)} records. <a href="{download_link}">Download CSV</a></div>
        {filter_form}
        <table>
          <thead>
            <tr>
              <th>id</th>
              <th>timestamp (UTC)</th>
              <th>remote_addr</th>
              <th>user_agent</th>
              <th>referer</th>
            </tr>
          </thead>
          <tbody>
            {''.join(html_rows)}
          </tbody>
        </table>
      </body>
    </html>
    """
    return Response(page, mimetype="text/html")

@app.route("/admin/download")
def admin_download():
    check_admin_token()
    filter_id = request.args.get("id")
    db = get_db()
    if filter_id:
        cur = db.execute(
            "SELECT id, ts, remote_addr, user_agent, referer FROM opens WHERE id = ? ORDER BY ts DESC",
            (filter_id,),
        )
    else:
        cur = db.execute("SELECT id, ts, remote_addr, user_agent, referer FROM opens ORDER BY ts DESC")
    rows = cur.fetchall()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["id", "ts", "remote_addr", "user_agent", "referer"])
    for r in rows:
        writer.writerow([(r[0] or ""), (r[1] or ""), (r[2] or ""), (r[3] or ""), (r[4] or "")])

    resp = Response(output.getvalue(), mimetype="text/csv")
    resp.headers["Content-Disposition"] = "attachment; filename=opens.csv"
    return resp

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
