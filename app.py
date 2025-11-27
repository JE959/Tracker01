import os
import sqlite3
from flask import Flask, request, send_file, make_response, Response
from datetime import datetime

app = Flask(__name__)

# -------- CONFIG --------
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "changeme")   # MUST set this in Render

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
            user_agent TEXT
        )
    """)
    conn.commit()
    conn.close()

init_db()

def get_db():
    return sqlite3.connect(DB_PATH)


# -------- PIXEL ENDPOINT --------
@app.route("/pixel.gif")
def pixel():
    user_id = request.args.get("id", "")

    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO opens (id, ts, remote_addr, user_agent) VALUES (?, ?, ?, ?)",
        (
            user_id,
            datetime.utcnow().isoformat(),
            request.remote_addr,
            request.headers.get("User-Agent", "")
        )
    )
    conn.commit()
    conn.close()

    # Return a 1x1 transparent GIF
    gif_bytes = (
        b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00"
        b"\xff\xff\xff!\xf9\x04\x01\x00\x00\x00\x00,"
        b"\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02"
        b"D\x01\x00;"
    )

    response = make_response(gif_bytes)
    response.headers["Content-Type"] = "image/gif"
    return response


# -------- ADMIN PAGE --------
@app.route("/admin")
def admin_page():
    token = request.args.get("token")
    if token != ADMIN_TOKEN:
        return "Unauthorized", 401

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT rowid, id, ts, remote_addr, user_agent FROM opens ORDER BY ts DESC LIMIT 100")
    rows = cur.fetchall()
    conn.close()

    # HTML table
    html = """
    <h1>Tracking Admin</h1>
    <p><a href="/admin/download?token={token}">Download CSV</a></p>
    <p><a href="/admin/clear?token={token}">🗑️ Delete ALL Records</a></p>

    <table border="1" cellpadding="5">
      <tr>
        <th>rowid</th><th>ID</th><th>Timestamp</th><th>IP</th><th>User-Agent</th><th>Delete</th>
      </tr>
    """.format(token=token)

    for rowid, uid, ts, ip, ua in rows:
        html += f"""
        <tr>
          <td>{rowid}</td>
          <td>{uid}</td>
          <td>{ts}</td>
          <td>{ip}</td>
          <td>{ua}</td>
          <td><a href="/admin/delete?id={uid}&token={token}">Delete This ID</a></td>
        </tr>
        """

    html += "</table>"
    return html


# -------- CSV EXPORT --------
@app.route("/admin/download")
def download_csv():
    token = request.args.get("token")
    if token != ADMIN_TOKEN:
        return "Unauthorized", 401

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id, ts, remote_addr, user_agent FROM opens ORDER BY ts DESC")
    rows = cur.fetchall()
    conn.close()

    csv_data = "id,timestamp,ip,user_agent\n"
    for row in rows:
        id_val, ts, ip, ua = row
        ua = ua.replace(",", " ")  # prevent CSV break
        csv_data += f"{id_val},{ts},{ip},{ua}\n"

    return Response(
        csv_data,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment;filename=opens.csv"}
    )


# -------- DELETE ALL RECORDS --------
@app.route("/admin/clear")
def clear_records():
    token = request.args.get("token")
    if token != ADMIN_TOKEN:
        return "Unauthorized", 401

    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM opens")
    conn.commit()
    conn.close()

    return "<h2>All records deleted.</h2><a href='/admin?token=" + token + "'>Back to Admin</a>"


# -------- DELETE BY ID --------
@app.route("/admin/delete")
def delete_by_id():
    token = request.args.get("token")
    if token != ADMIN_TOKEN:
        return "Unauthorized", 401

    delete_id = request.args.get("id")
    if not delete_id:
        return "Missing id", 400

    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM opens WHERE id = ?", (delete_id,))
    conn.commit()
    conn.close()

    return f"<h2>Deleted records for id={delete_id}</h2><a href='/admin?token={token}'>Back to Admin</a>"


# -------- HOME --------
@app.route("/")
def index():
    return "Pixel tracker running."


# -------- RUN LOCAL --------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)

