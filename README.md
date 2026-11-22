# Scholarship Finder India

Flask + SQLite web app that matches a student's profile against Indian government scholarship rules and sorts results into
**Eligible / Potentially eligible / Not eligible** (with reasons). A scheme is only ever "Eligible" when every rule passed,
nothing needs manual checking, and the scheme's rules are marked *verified* from an official source.

## Run locally on Windows (PowerShell)
```powershell
cd scholarship_finder
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python seed.py          # creates scholarships.db and prints the admin password ONCE
python app.py           # open http://127.0.0.1:5000
```
Admin login: http://127.0.0.1:5000/admin/login  (username `admin`, password printed by `seed.py`;
or set `ADMIN_PASSWORD` before running `seed.py`). Bootstrap, Font Awesome and Google Fonts load from CDNs, so you need internet in the browser.

## Run the tests
```powershell
python -m unittest discover -s tests -v
```

## Project structure
```
app.py            routes, auth, CSRF, validation, admin, PDF export
engine.py         rule-based eligibility engine (pure Python)
db.py, schema.sql database access, tables, seeding
seed.py           create DB + load data/scholarships.json
data/scholarships.json   scheme records and their machine-readable rules
templates/, static/      Bootstrap 5 UI (white and navy)
tests/test_app.py        engine + application tests
docs/DOCUMENTATION.md    report, diagrams, limitations, future work
```

## Data policy (important)
`data/scholarships.json` was compiled from official pages (education.gov.in, AICTE, myScheme, PIB, TN government sites) and
cross-checked with news coverage on 22 Nov 2026. Each record carries `verification_status`, `source_url`, `last_verified` and a
`verification_note`. Anything unconfirmed shows as "Not verified – check official portal". **Always re-verify on
https://scholarships.gov.in before relying on a result**; scheme rules, amounts and deadlines change every year.
The admin panel lets you add/edit schemes and rules as you verify more of them.

## Security notes
Password hashing (Werkzeug scrypt/pbkdf2), parameterised SQL everywhere, CSRF token on every POST, HttpOnly + SameSite cookies,
2-hour sessions, separate student/admin sessions, security headers, Jinja auto-escaping, URL scheme check on admin links, and
student data is visible only to the student (admins see minimal fields). Before real deployment add HTTPS, `SECRET_KEY` env var,
login rate-limiting and `SESSION_COOKIE_SECURE=True`.
