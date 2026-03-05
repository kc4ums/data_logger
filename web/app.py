from __future__ import annotations
from flask import Flask, jsonify, render_template, request
from logger import database

app = Flask(__name__, template_folder="templates", static_folder="static")


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/plcs")
def api_plcs():
    """Return all PLCs with their latest tag values, grouped by PLC."""
    rows = database.get_latest()

    plcs: dict = {}
    for row in rows:
        pid = row["plc_id"]
        if pid not in plcs:
            plcs[pid] = {
                "id": pid,
                "name": row["plc_name"],
                "ip": row["plc_ip"],
                "tags": [],
            }
        plcs[pid]["tags"].append({
            "id": row["tag_id"],
            "name": row["tag_name"],
            "unit": row["unit"],
            "data_type": row["data_type"],
            "register_type": row["register_type"],
            "value": row["value"],
            "quality": row["quality"],
            "ts": row["ts"],
        })

    return jsonify(list(plcs.values()))


@app.route("/api/tags/<int:tag_id>/history")
def api_tag_history(tag_id: int):
    minutes = request.args.get("minutes", 60, type=int)
    rows = database.get_history(tag_id, minutes)
    return jsonify(rows)


@app.route("/api/alarms")
def api_alarms():
    return jsonify(database.get_alarms())
