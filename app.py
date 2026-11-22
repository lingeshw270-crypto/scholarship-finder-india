import io, json, os, re, secrets
from datetime import date, datetime, timedelta
from functools import wraps

from flask import (Flask, abort, flash, g, redirect, render_template, request,
                   send_file, session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

import db as dbm
from engine import COURSE_TYPES, EDU_LEVELS, calc_age, recommend, student_facts, evaluate

BASE = os.path.dirname(os.path.abspath(__file__))
STATES = ["Andhra Pradesh", "Arunachal Pradesh", "Assam", "Bihar", "Chhattisgarh", "Goa", "Gujarat", "Haryana",
          "Himachal Pradesh", "Jharkhand", "Karnataka", "Kerala", "Madhya Pradesh", "Maharashtra", "Manipur",
          "Meghalaya", "Mizoram", "Nagaland", "Odisha", "Punjab", "Rajasthan", "Sikkim", "Tamil Nadu", "Telangana",
          "Tripura", "Uttar Pradesh", "Uttarakhand", "West Bengal", "Andaman and Nicobar Islands", "Chandigarh",
          "Dadra and Nagar Haveli and Daman and Diu", "Delhi", "Jammu and Kashmir", "Ladakh", "Lakshadweep", "Puducherry"]
CATEGORIES = ["General", "SC", "ST", "OBC", "EWS"]
ADMISSION_TYPES = ["Regular", "Lateral Entry", "Management Quota", "Other"]
APP_STATUSES = ["Planning", "Applied", "Under Verification", "Approved", "Rejected"]
DEFAULT_DOCS = ["Aadhaar card", "Bank passbook (Aadhaar-seeded account)", "Income certificate", "Caste/community certificate",
                "Class 10 marksheet", "Class 12 marksheet", "Previous year marksheet", "College admission / bonafide certificate",
                "Disability certificate (if applicable)", "Passport-size photograph"]


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.update(
        DATABASE=os.path.join(BASE, "scholarships.db"),
        SECRET_KEY=_secret_key(),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        PERMANENT_SESSION_LIFETIME=timedelta(hours=2),
        MAX_CONTENT_LENGTH=1024 * 1024,
    )
    if test_config:
        app.config.update(test_config)
    app.teardown_appcontext(dbm.close_db)

    # ---------- security helpers ----------
    @app.before_request
    def csrf_protect():
        if "csrf" not in session:
            session["csrf"] = secrets.token_hex(16)
        if request.method == "POST" and not app.config.get("TESTING_NO_CSRF"):
            if not secrets.compare_digest(request.form.get("csrf", ""), session["csrf"]):
                abort(400, "Invalid or missing CSRF token. Reload the page and try again.")

    @app.after_request
    def headers(resp):
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Referrer-Policy"] = "same-origin"
        resp.headers["Cache-Control"] = "no-store" if "uid" in session or "aid" in session else resp.headers.get("Cache-Control", "no-cache")
        return resp

    app.jinja_env.globals.update(csrf_token=lambda: session.get("csrf", ""), fmt_date=fmt_date, today=date.today)

    def login_required(f):
        @wraps(f)
        def w(*a, **k):
            if "uid" not in session:
                flash("Please log in to continue.", "warning")
                return redirect(url_for("login", next=request.path))
            return f(*a, **k)
        return w

    def admin_required(f):
        @wraps(f)
        def w(*a, **k):
            if "aid" not in session:
                return redirect(url_for("admin_login"))
            return f(*a, **k)
        return w

    def current_student():
        row = dbm.get_db().execute("SELECT * FROM students WHERE id=?", (session["uid"],)).fetchone()
        if row is None:
            session.clear(); abort(401)
        return dict(row)

    # ---------- public pages ----------
    @app.route("/")
    def index():
        n = dbm.get_db().execute("SELECT COUNT(*) FROM scholarships WHERE active=1").fetchone()[0]
        return render_template("index.html", count=n)

    @app.route("/register", methods=["GET", "POST"])
    def register():
        if request.method == "POST":
            data, errors = validate_student(request.form, new=True)
            if not errors and dbm.get_db().execute("SELECT 1 FROM students WHERE email=?", (data["email"],)).fetchone():
                errors["email"] = "An account with this email already exists."
            if errors:
                return render_template("register.html", errors=errors, f=request.form, **form_ctx()), 400
            d = dbm.get_db()
            cols = [c for c in data if c != "password"]
            cur = d.execute(f"INSERT INTO students ({','.join(cols)},password_hash) VALUES ({','.join('?'*len(cols))},?)",
                            [data[c] for c in cols] + [generate_password_hash(data["password"])])
            d.executemany("INSERT INTO documents (student_id, doc_name) VALUES (?,?)", [(cur.lastrowid, n) for n in DEFAULT_DOCS])
            d.commit()
            session.clear(); session["uid"] = cur.lastrowid; session.permanent = True
            flash("Account created. Here are your scholarship results.", "success")
            return redirect(url_for("dashboard"))
        return render_template("register.html", errors={}, f={}, **form_ctx())

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            email = request.form.get("email", "").strip().lower()
            row = dbm.get_db().execute("SELECT * FROM students WHERE email=?", (email,)).fetchone()
            if row and check_password_hash(row["password_hash"], request.form.get("password", "")):
                nxt = request.args.get("next", "")
                session.clear(); session["uid"] = row["id"]; session.permanent = True
                return redirect(nxt if nxt.startswith("/") and not nxt.startswith("//") else url_for("dashboard"))
            flash("Incorrect email or password.", "danger")
        return render_template("login.html")

    @app.route("/logout", methods=["POST"])
    def logout():
        session.clear()
        return redirect(url_for("index"))

    # ---------- student area ----------
    def load_all():
        d = dbm.get_db()
        schemes = [dict(r) for r in d.execute("SELECT * FROM scholarships WHERE active=1 ORDER BY scope, name")]
        return schemes, dbm.rules_by_scholarship(d)

    @app.route("/dashboard")
    @login_required
    def dashboard():
        s = current_student()
        schemes, rules = load_all()
        results = recommend(s, schemes, rules)
        saved = {r[0] for r in dbm.get_db().execute("SELECT scholarship_id FROM saved_scholarships WHERE student_id=?", (s["id"],))}
        return render_template("dashboard.html", s=s, age=calc_age(s["dob"]), results=results, saved=saved)

    @app.route("/profile", methods=["GET", "POST"])
    @login_required
    def profile():
        s = current_student()
        if request.method == "POST":
            data, errors = validate_student(request.form, new=False)
            if errors:
                return render_template("profile.html", errors=errors, f=request.form, **form_ctx()), 400
            cols = list(data)
            d = dbm.get_db()
            d.execute(f"UPDATE students SET {','.join(c+'=?' for c in cols)} WHERE id=?", [data[c] for c in cols] + [s["id"]])
            d.commit()
            flash("Profile updated. Recommendations were recalculated.", "success")
            return redirect(url_for("dashboard"))
        return render_template("profile.html", errors={}, f=s, **form_ctx())

    @app.route("/scholarships")
    def scholarships():
        schemes, rules = load_all()
        q = request.args.get("q", "").strip().lower()
        flt = {"state": request.args.get("state", ""), "category": request.args.get("category", ""),
               "edu_level": request.args.get("level", ""), "annual_income": _int(request.args.get("income"))}
        out = []
        for sc in schemes:
            if q and q not in (sc["name"] + " " + sc["department"] + " " + sc["description"]).lower():
                continue
            if flt["state"] and sc["scope"] == "State" and sc["state"] != flt["state"]:
                continue
            if _passes_filters(flt, rules.get(sc["id"], [])):
                out.append(sc)
        return render_template("scholarships.html", items=out, states=STATES, categories=CATEGORIES,
                               levels=EDU_LEVELS, args=request.args)

    @app.route("/scholarship/<int:sid>")
    def scholarship_detail(sid):
        sc = _get_scheme(sid)
        res, saved = None, False
        if "uid" in session:
            s = current_student()
            res = evaluate(student_facts(s), sc, dbm.rules_by_scholarship(dbm.get_db()).get(sid, []))
            saved = bool(dbm.get_db().execute("SELECT 1 FROM saved_scholarships WHERE student_id=? AND scholarship_id=?", (s["id"], sid)).fetchone())
        return render_template("detail.html", sc=sc, res=res, saved=saved)

    @app.route("/scholarship/<int:sid>/pdf")
    def scholarship_pdf(sid):
        sc = _get_scheme(sid)
        return send_file(build_pdf(sc), mimetype="application/pdf", download_name=f"{sc['slug']}.pdf")

    @app.route("/compare")
    def compare():
        ids = [i for i in (_int(x) for x in request.args.getlist("id")) if i][:3]
        if len(ids) < 2:
            flash("Select 2 or 3 scholarships to compare.", "warning")
            return redirect(url_for("scholarships"))
        return render_template("compare.html", items=[_get_scheme(i) for i in ids])

    @app.route("/save/<int:sid>", methods=["POST"])
    @login_required
    def save(sid):
        _get_scheme(sid)
        d = dbm.get_db()
        d.execute("INSERT OR IGNORE INTO saved_scholarships (student_id, scholarship_id) VALUES (?,?)", (session["uid"], sid))
        d.commit(); flash("Saved to your list.", "success")
        return redirect(request.referrer or url_for("saved"))

    @app.route("/unsave/<int:sid>", methods=["POST"])
    @login_required
    def unsave(sid):
        d = dbm.get_db()
        d.execute("DELETE FROM saved_scholarships WHERE student_id=? AND scholarship_id=?", (session["uid"], sid))
        d.commit()
        return redirect(request.referrer or url_for("saved"))

    @app.route("/saved")
    @login_required
    def saved():
        rows = dbm.get_db().execute("SELECT s.* FROM scholarships s JOIN saved_scholarships v ON v.scholarship_id=s.id WHERE v.student_id=? ORDER BY v.saved_at DESC", (session["uid"],)).fetchall()
        return render_template("saved.html", items=[dict(r) for r in rows])

    @app.route("/applications", methods=["GET", "POST"])
    @login_required
    def applications():
        d = dbm.get_db()
        if request.method == "POST":
            sid, status = _int(request.form.get("scholarship_id")), request.form.get("status", "Planning")
            if status not in APP_STATUSES: abort(400)
            _get_scheme(sid)
            notes = request.form.get("notes", "")[:500]
            d.execute("""INSERT INTO applications (student_id, scholarship_id, status, notes) VALUES (?,?,?,?)
                         ON CONFLICT(student_id, scholarship_id) DO UPDATE SET status=excluded.status, notes=excluded.notes, updated_at=CURRENT_TIMESTAMP""",
                      (session["uid"], sid, status, notes))
            d.commit(); flash("Application tracker updated.", "success")
            return redirect(url_for("applications"))
        rows = d.execute("SELECT a.*, s.name, s.deadline FROM applications a JOIN scholarships s ON s.id=a.scholarship_id WHERE a.student_id=? ORDER BY a.updated_at DESC", (session["uid"],)).fetchall()
        saved_opts = d.execute("SELECT s.id, s.name FROM scholarships s JOIN saved_scholarships v ON v.scholarship_id=s.id WHERE v.student_id=?", (session["uid"],)).fetchall()
        return render_template("applications.html", rows=rows, statuses=APP_STATUSES, options=saved_opts)

    @app.route("/documents", methods=["GET", "POST"])
    @login_required
    def documents():
        d = dbm.get_db()
        if request.method == "POST":
            if request.form.get("new_doc", "").strip():
                d.execute("INSERT OR IGNORE INTO documents (student_id, doc_name) VALUES (?,?)", (session["uid"], request.form["new_doc"].strip()[:100]))
            else:
                ready = set(request.form.getlist("ready"))
                for r in d.execute("SELECT id FROM documents WHERE student_id=?", (session["uid"],)).fetchall():
                    d.execute("UPDATE documents SET is_ready=? WHERE id=? AND student_id=?", (int(str(r["id"]) in ready), r["id"], session["uid"]))
            d.commit(); return redirect(url_for("documents"))
        rows = d.execute("SELECT * FROM documents WHERE student_id=? ORDER BY id", (session["uid"],)).fetchall()
        return render_template("documents.html", rows=rows)

    @app.route("/account/delete", methods=["POST"])
    @login_required
    def delete_account():
        d = dbm.get_db(); d.execute("DELETE FROM students WHERE id=?", (session["uid"],)); d.commit()
        session.clear(); flash("Your account and data were deleted.", "info")
        return redirect(url_for("index"))

    # ---------- admin ----------
    @app.route("/admin/login", methods=["GET", "POST"])
    def admin_login():
        if request.method == "POST":
            row = dbm.get_db().execute("SELECT * FROM admins WHERE username=?", (request.form.get("username", ""),)).fetchone()
            if row and check_password_hash(row["password_hash"], request.form.get("password", "")):
                session.clear(); session["aid"] = row["id"]; session.permanent = True
                return redirect(url_for("admin_home"))
            flash("Incorrect admin credentials.", "danger")
        return render_template("admin/login.html")

    @app.route("/admin/logout", methods=["POST"])
    def admin_logout():
        session.clear(); return redirect(url_for("admin_login"))

    @app.route("/admin")
    @admin_required
    def admin_home():
        d = dbm.get_db(); one = lambda q: d.execute(q).fetchone()[0]
        stats = {"students": one("SELECT COUNT(*) FROM students"), "schemes": one("SELECT COUNT(*) FROM scholarships WHERE active=1"),
                 "unverified": one("SELECT COUNT(*) FROM scholarships WHERE active=1 AND verification_status!='verified'"),
                 "saved": one("SELECT COUNT(*) FROM saved_scholarships"), "apps": one("SELECT COUNT(*) FROM applications")}
        by_status = d.execute("SELECT status, COUNT(*) n FROM applications GROUP BY status").fetchall()
        top = d.execute("SELECT s.name, COUNT(*) n FROM applications a JOIN scholarships s ON s.id=a.scholarship_id GROUP BY s.id ORDER BY n DESC LIMIT 5").fetchall()
        return render_template("admin/home.html", stats=stats, by_status=by_status, top=top)

    @app.route("/admin/scholarships")
    @admin_required
    def admin_scholarships():
        rows = dbm.get_db().execute("SELECT * FROM scholarships ORDER BY active DESC, name").fetchall()
        return render_template("admin/scholarships.html", rows=rows)

    @app.route("/admin/scholarships/new", methods=["GET", "POST"])
    @app.route("/admin/scholarships/<int:sid>/edit", methods=["GET", "POST"])
    @admin_required
    def admin_edit(sid=None):
        d = dbm.get_db()
        sc = dict(d.execute("SELECT * FROM scholarships WHERE id=?", (sid,)).fetchone() or {}) if sid else {}
        if sid and not sc: abort(404)
        rules_json = json.dumps([{k: r[k] for k in ("field", "operator", "value", "hard", "message")}
                                 for r in dbm.rules_by_scholarship(d).get(sid, [])], indent=1, ensure_ascii=False) if sid else "[]"
        if request.method == "POST":
            f = request.form
            required = ["name", "department", "scope", "scheme_type", "description", "eligibility_text", "amount_text"]
            errs = [k for k in required if not f.get(k, "").strip()]
            try:
                rules = _parse_rules(f.get("rules", "[]"))
            except ValueError as e:
                errs.append(f"rules ({e})")
            for k in ("start_date", "deadline"):
                if f.get(k) and not _valid_date(f[k]): errs.append(k)
            if f.get("scope") not in ("Central", "State"): errs.append("scope")
            if errs:
                flash("Fix these fields: " + ", ".join(errs), "danger")
                return render_template("admin/edit.html", sc=f, sid=sid, rules_json=f.get("rules", "[]")), 400
            vals = {k: (f.get(k) or None) for k in ["name", "department", "scope", "state", "scheme_type", "description", "eligibility_text",
                    "amount_text", "benefits", "documents", "start_date", "deadline", "apply_url", "source_url", "verification_note"]}
            vals["income_limit"] = _int(f.get("income_limit"))
            vals["verification_status"] = "verified" if f.get("verification_status") == "verified" else "needs_confirmation"
            vals["last_verified"] = f.get("last_verified") or date.today().isoformat()
            vals["active"] = 1 if f.get("active") else 0
            if vals["apply_url"] and not vals["apply_url"].startswith(("https://", "http://")):
                flash("Application link must start with http(s)://", "danger")
                return render_template("admin/edit.html", sc=f, sid=sid, rules_json=f.get("rules", "[]")), 400
            if sid:
                d.execute(f"UPDATE scholarships SET {','.join(k+'=?' for k in vals)} WHERE id=?", list(vals.values()) + [sid])
                d.execute("DELETE FROM eligibility_rules WHERE scholarship_id=?", (sid,))
            else:
                vals["slug"] = re.sub(r"[^a-z0-9]+", "-", vals["name"].lower()).strip("-")[:60] + "-" + secrets.token_hex(2)
                cur = d.execute(f"INSERT INTO scholarships ({','.join(vals)}) VALUES ({','.join('?'*len(vals))})", list(vals.values()))
                sid = cur.lastrowid
            for r in rules:
                d.execute("INSERT INTO eligibility_rules (scholarship_id,field,operator,value,hard,message) VALUES (?,?,?,?,?,?)",
                          (sid, r["field"], r["operator"], json.dumps(r["value"]), int(r["hard"]), r["message"]))
            d.commit(); flash("Scholarship saved.", "success")
            return redirect(url_for("admin_scholarships"))
        return render_template("admin/edit.html", sc=sc, sid=sid, rules_json=rules_json)

    @app.route("/admin/scholarships/<int:sid>/delete", methods=["POST"])
    @admin_required
    def admin_delete(sid):
        d = dbm.get_db(); d.execute("DELETE FROM scholarships WHERE id=?", (sid,)); d.commit()
        flash("Scholarship deleted.", "info"); return redirect(url_for("admin_scholarships"))

    @app.route("/admin/students")
    @admin_required
    def admin_students():
        rows = dbm.get_db().execute("SELECT id, full_name, email, state, edu_level, created_at FROM students ORDER BY id DESC").fetchall()
        return render_template("admin/students.html", rows=rows)

    @app.route("/admin/students/<int:uid>/delete", methods=["POST"])
    @admin_required
    def admin_student_delete(uid):
        d = dbm.get_db(); d.execute("DELETE FROM students WHERE id=?", (uid,)); d.commit()
        flash("Student account deleted.", "info"); return redirect(url_for("admin_students"))

    @app.errorhandler(400)
    @app.errorhandler(401)
    @app.errorhandler(404)
    def err(e):
        return render_template("error.html", e=e), e.code

    return app


# ---------- helpers ----------
def _secret_key():
    if os.environ.get("SECRET_KEY"):
        return os.environ["SECRET_KEY"]
    p = os.path.join(BASE, ".secret_key")
    if not os.path.exists(p):
        with open(p, "w") as f: f.write(secrets.token_hex(32))
    with open(p) as f:
        return f.read().strip()


def _int(v):
    try: return int(str(v).strip())
    except (TypeError, ValueError): return None


def _float(v):
    try: return float(str(v).strip())
    except (TypeError, ValueError): return None


def _tri(v):  # yes/no/unsure -> 1/0/None
    return {"yes": 1, "no": 0}.get(v)


def _valid_date(s):
    try: datetime.strptime(s, "%Y-%m-%d"); return True
    except ValueError: return False


def fmt_date(s, missing="Not verified – check official portal"):
    if not s: return missing
    return datetime.strptime(s, "%Y-%m-%d").strftime("%d %b %Y")


def form_ctx():
    return dict(states=STATES, categories=CATEGORIES, levels=EDU_LEVELS, course_types=COURSE_TYPES, admission_types=ADMISSION_TYPES)


def _get_scheme(sid):
    row = dbm.get_db().execute("SELECT * FROM scholarships WHERE id=? AND active=1", (sid,)).fetchone()
    if not row: abort(404)
    return dict(row)


def _passes_filters(flt, rules):
    for r in rules:
        if not r["hard"] or r["operator"] == "manual": continue
        v = flt.get(r["field"])
        if v in (None, ""): continue
        try:
            from engine import _check
            if not _check(r["operator"], v, r["value"]): return False
        except TypeError:
            continue
    return True


def _parse_rules(text):
    try: rules = json.loads(text or "[]")
    except json.JSONDecodeError as e: raise ValueError("invalid JSON: " + str(e))
    if not isinstance(rules, list): raise ValueError("must be a list")
    for r in rules:
        if not isinstance(r, dict) or not {"field", "operator", "value", "hard", "message"} <= set(r):
            raise ValueError("each rule needs field, operator, value, hard, message")
        if r["operator"] not in ("lte", "gte", "eq", "in", "not_in", "manual"): raise ValueError("bad operator " + str(r["operator"]))
    return rules


def validate_student(f, new):
    e, d = {}, {}
    g_ = lambda k: f.get(k, "").strip()
    d["full_name"] = g_("full_name")
    if len(d["full_name"]) < 2: e["full_name"] = "Enter your full name."
    if new:
        d["email"] = g_("email").lower()
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", d["email"]): e["email"] = "Enter a valid email address."
        d["password"] = f.get("password", "")
        if len(d["password"]) < 8 or not re.search(r"\d", d["password"]) or not re.search(r"[A-Za-z]", d["password"]):
            e["password"] = "Use at least 8 characters with letters and a number."
    d["dob"] = g_("dob")
    try:
        age = calc_age(d["dob"])
        if not 10 <= age <= 60: e["dob"] = "Age must be between 10 and 60."
    except ValueError:
        e["dob"] = "Enter a valid date of birth."
    d["gender"] = g_("gender")
    if d["gender"] not in ("Male", "Female", "Other"): e["gender"] = "Select gender."
    d["state"] = g_("state")
    if d["state"] not in STATES: e["state"] = "Select your state."
    d["district"] = g_("district")[:60]
    if not d["district"]: e["district"] = "Enter your district."
    d["category"] = g_("category")
    if d["category"] not in CATEGORIES: e["category"] = "Select category."
    d["is_minority"] = 1 if f.get("is_minority") else 0
    d["annual_income"] = _int(f.get("annual_income"))
    if d["annual_income"] is None or d["annual_income"] < 0: e["annual_income"] = "Enter annual family income in rupees."
    d["disability_percent"] = _int(f.get("disability_percent")) or 0
    if not 0 <= d["disability_percent"] <= 100: e["disability_percent"] = "Enter 0–100."
    d["edu_level"] = g_("edu_level")
    if d["edu_level"] not in EDU_LEVELS: e["edu_level"] = "Select education level."
    d["course_name"] = g_("course_name")[:100]
    d["college_name"] = g_("college_name")[:150]
    d["university_name"] = g_("university_name")[:150]
    for k in ("course_name", "college_name"):
        if not d[k]: e[k] = "Required."
    d["course_type"] = g_("course_type") if g_("course_type") in COURSE_TYPES else "Other"
    d["academic_year"] = _int(f.get("academic_year"))
    if d["academic_year"] is None or not 1 <= d["academic_year"] <= 6: e["academic_year"] = "Enter 1–6."
    for k in ("prev_percentage", "marks_10", "marks_12"):
        d[k] = _float(f.get(k))
        if g_(k) and (d[k] is None or not 0 <= d[k] <= 100): e[k] = "Enter 0–100."
    d["admission_type"] = g_("admission_type") if g_("admission_type") in ADMISSION_TYPES else "Regular"
    d["aicte_approved"] = _tri(g_("aicte_approved"))
    d["govt_school_6_12"] = _tri(g_("govt_school_6_12"))
    d["other_scholarship"] = _tri(g_("other_scholarship"))
    return d, e


def build_pdf(sc):
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer
    from xml.sax.saxutils import escape

    def clean(t):  # standard PDF fonts lack the rupee glyph
        t = (t or "Not available").replace("₹", "Rs. ")
        return escape(t.encode("latin-1", "replace").decode("latin-1"))
    ss = getSampleStyleSheet()
    rows = [("Department", sc["department"]), ("Description", sc["description"]), ("Eligibility", sc["eligibility_text"]),
            ("Income limit", f"Rs. {sc['income_limit']:,} per annum" if sc["income_limit"] else "Not verified"),
            ("Amount", sc["amount_text"]), ("Benefits", sc["benefits"]), ("Documents", sc["documents"]),
            ("Application start", fmt_date(sc["start_date"], "Not verified")), ("Deadline", fmt_date(sc["deadline"], "Not verified")),
            ("Official website", sc["apply_url"] or "Not available"), ("Source", sc["source_url"]),
            ("Last verified", fmt_date(sc["last_verified"], "Unknown")),
            ("Verification status", "Verified" if sc["verification_status"] == "verified" else "Needs confirmation on the official portal"),
            ("Note", sc["verification_note"])]
    story = [Paragraph(clean(sc["name"]), ss["Title"]), Spacer(1, 6)]
    for k, v in rows:
        story += [Paragraph(f"<b>{clean(k)}</b>", ss["Heading4"]), Paragraph(clean(v), ss["BodyText"])]
    story += [Spacer(1, 10), Paragraph("Generated by Scholarship Finder India. Always confirm details on the official portal before applying.", ss["Italic"])]
    buf = io.BytesIO()
    SimpleDocTemplate(buf, pagesize=A4, leftMargin=18*mm, rightMargin=18*mm, topMargin=16*mm, bottomMargin=16*mm).build(story)
    buf.seek(0)
    return buf


if __name__ == "__main__":
    app = create_app()
    if not os.path.exists(app.config["DATABASE"]):
        pw = dbm.init_db(app.config["DATABASE"])
        print(f"Database created. Admin password (shown once): {pw}")
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1")
