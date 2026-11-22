import json, os, secrets, sqlite3
from flask import g, current_app

BASE = os.path.dirname(os.path.abspath(__file__))


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(current_app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def close_db(_=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db(path, seed=True, admin_password=None):
    """Create tables and (optionally) load the verified scholarship data."""
    from werkzeug.security import generate_password_hash
    con = sqlite3.connect(path)
    con.execute("PRAGMA foreign_keys = ON")
    with open(os.path.join(BASE, "schema.sql"), encoding="utf-8") as f:
        con.executescript(f.read())
    generated = None
    if seed:
        load_scholarships(con)
        if not con.execute("SELECT 1 FROM admins").fetchone():
            generated = admin_password or os.environ.get("ADMIN_PASSWORD") or secrets.token_urlsafe(9)
            con.execute("INSERT INTO admins (username, password_hash) VALUES (?, ?)",
                        ("admin", generate_password_hash(generated)))
    con.commit()
    con.close()
    return generated


def load_scholarships(con):
    with open(os.path.join(BASE, "data", "scholarships.json"), encoding="utf-8") as f:
        items = json.load(f)
    cols = ["name", "department", "scope", "state", "scheme_type", "description", "eligibility_text",
            "income_limit", "amount_text", "benefits", "documents", "start_date", "deadline",
            "apply_url", "source_url", "verification_status", "verification_note"]
    for it in items:
        if con.execute("SELECT 1 FROM scholarships WHERE slug=?", (it["slug"],)).fetchone():
            continue
        cur = con.execute(
            f"INSERT INTO scholarships (slug,last_verified,{','.join(cols)}) VALUES (?,?,{','.join('?'*len(cols))})",
            [it["slug"], "2026-11-22"] + [it.get(c) for c in cols])
        sid = cur.lastrowid
        for r in it["rules"]:
            con.execute("INSERT INTO eligibility_rules (scholarship_id,field,operator,value,hard,message) VALUES (?,?,?,?,?,?)",
                        (sid, r["field"], r["operator"], json.dumps(r["value"]), int(r["hard"]), r["message"]))


def rules_by_scholarship(db):
    out = {}
    for r in db.execute("SELECT * FROM eligibility_rules ORDER BY id"):
        d = dict(r)
        d["value"] = json.loads(d["value"])
        d["hard"] = bool(d["hard"])
        out.setdefault(d["scholarship_id"], []).append(d)
    return out
