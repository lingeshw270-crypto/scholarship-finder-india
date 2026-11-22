"""Create the database and load verified scholarship data:  python seed.py"""
import os, sys
from db import init_db

path = os.environ.get("DATABASE", os.path.join(os.path.dirname(os.path.abspath(__file__)), "scholarships.db"))
pw = init_db(path)
print(f"Database ready: {path}")
if pw:
    print(f"Admin created ->  username: admin   password: {pw}\n(Save it now; it is not stored in plain text.)")
else:
    print("Admin already exists; password unchanged.")
