"""Rule-based eligibility engine.

Statuses:
  eligible       - every hard rule passed, no open checks, and the scheme's rules are verified.
  potential      - nothing failed, but information is missing, a check needs manual
                   verification, or the scheme's rules are not fully verified.
  not_eligible   - at least one hard rule failed (reasons listed).
"""
from datetime import date, datetime

EDU_LEVELS = ["Class 9-10", "Class 11-12", "Diploma", "Undergraduate", "Postgraduate", "PhD"]
COURSE_TYPES = ["Technical/Engineering", "Medical", "Management", "Law", "Arts/Science/Commerce", "Other"]
FRESH_ENTRY_TYPES = ("Lateral Entry",)


def calc_age(dob_str, today=None):
    today = today or date.today()
    dob = datetime.strptime(dob_str, "%Y-%m-%d").date()
    return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))


def student_facts(student, today=None):
    """Flatten a student row into the fields rules can reference."""
    f = dict(student)
    f["age"] = calc_age(f["dob"], today) if f.get("dob") else None
    year = f.get("academic_year")
    f["fresh_entry"] = (year == 1) or (year == 2 and f.get("admission_type") in FRESH_ENTRY_TYPES)
    return f


def _check(op, actual, expected):
    if op == "lte": return actual <= expected
    if op == "gte": return actual >= expected
    if op == "eq": return actual == expected
    if op == "in": return actual in expected
    if op == "not_in": return actual not in expected
    raise ValueError(f"Unknown operator {op}")


def evaluate(facts, scholarship, rules, today=None):
    today = today or date.today()
    failed, verify, passed = [], [], []
    for r in rules:
        if r["operator"] == "manual":
            verify.append(r["message"])
            continue
        actual = facts.get(r["field"])
        if actual is None or actual == "":
            verify.append(f"Missing information ({r['field'].replace('_', ' ')}): {r['message']}")
            continue
        ok = _check(r["operator"], actual, r["value"])
        if ok:
            passed.append(r["message"])
        elif r["hard"]:
            failed.append(r["message"])
        else:
            verify.append(r["message"])
    if failed:
        status = "not_eligible"
    elif verify:
        status = "potential"
    elif scholarship["verification_status"] != "verified":
        status = "potential"
        verify.append("This scheme's rules could not be fully verified. Confirm on the official portal before applying.")
    else:
        status = "eligible"
    if status == "potential" and scholarship["verification_status"] != "verified" and not any("could not be fully verified" in v for v in verify):
        verify.append("This scheme's rules could not be fully verified. Confirm on the official portal before applying.")
    closed = False
    if scholarship.get("deadline"):
        closed = datetime.strptime(scholarship["deadline"], "%Y-%m-%d").date() < today
    return {"status": status, "failed": failed, "verify": verify, "passed": passed, "closed": closed}


def recommend(student, scholarships, rules_by_sid, today=None):
    facts = student_facts(student, today)
    out = {"eligible": [], "potential": [], "not_eligible": []}
    for s in scholarships:
        if s["scope"] == "State" and s["state"] and s["state"] != facts.get("state"):
            continue  # state schemes of other states are not relevant, not "not eligible"
        res = evaluate(facts, s, rules_by_sid.get(s["id"], []), today)
        out[res["status"]].append({"scholarship": s, **res})
    return out
