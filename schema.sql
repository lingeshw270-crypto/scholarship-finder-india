PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS students (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  email TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  full_name TEXT NOT NULL,
  dob TEXT NOT NULL,
  gender TEXT NOT NULL CHECK (gender IN ('Male','Female','Other')),
  state TEXT NOT NULL,
  district TEXT NOT NULL,
  category TEXT NOT NULL CHECK (category IN ('General','SC','ST','OBC','EWS')),
  is_minority INTEGER NOT NULL DEFAULT 0,
  annual_income INTEGER NOT NULL CHECK (annual_income >= 0),
  disability_percent INTEGER NOT NULL DEFAULT 0 CHECK (disability_percent BETWEEN 0 AND 100),
  edu_level TEXT NOT NULL,
  course_name TEXT NOT NULL,
  college_name TEXT NOT NULL,
  university_name TEXT,
  academic_year INTEGER NOT NULL CHECK (academic_year BETWEEN 1 AND 6),
  prev_percentage REAL CHECK (prev_percentage BETWEEN 0 AND 100),
  marks_10 REAL CHECK (marks_10 BETWEEN 0 AND 100),
  marks_12 REAL CHECK (marks_12 BETWEEN 0 AND 100),
  admission_type TEXT NOT NULL,
  course_type TEXT NOT NULL DEFAULT 'Other',
  aicte_approved INTEGER,
  govt_school_6_12 INTEGER,
  other_scholarship INTEGER,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS admins (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS scholarships (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  slug TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  department TEXT NOT NULL,
  scope TEXT NOT NULL CHECK (scope IN ('Central','State')),
  state TEXT,
  scheme_type TEXT NOT NULL,
  description TEXT NOT NULL,
  eligibility_text TEXT NOT NULL,
  income_limit INTEGER,
  amount_text TEXT NOT NULL,
  benefits TEXT,
  documents TEXT,
  start_date TEXT,
  deadline TEXT,
  apply_url TEXT,
  source_url TEXT,
  last_verified TEXT,
  verification_status TEXT NOT NULL DEFAULT 'needs_confirmation'
     CHECK (verification_status IN ('verified','needs_confirmation')),
  verification_note TEXT,
  is_sample_data INTEGER NOT NULL DEFAULT 0,
  active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS eligibility_rules (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  scholarship_id INTEGER NOT NULL REFERENCES scholarships(id) ON DELETE CASCADE,
  field TEXT NOT NULL,
  operator TEXT NOT NULL CHECK (operator IN ('lte','gte','in','eq','not_in','manual')),
  value TEXT NOT NULL,
  hard INTEGER NOT NULL DEFAULT 1,
  message TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS saved_scholarships (
  student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
  scholarship_id INTEGER NOT NULL REFERENCES scholarships(id) ON DELETE CASCADE,
  saved_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (student_id, scholarship_id)
);
CREATE TABLE IF NOT EXISTS applications (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
  scholarship_id INTEGER NOT NULL REFERENCES scholarships(id) ON DELETE CASCADE,
  status TEXT NOT NULL DEFAULT 'Planning'
     CHECK (status IN ('Planning','Applied','Under Verification','Approved','Rejected')),
  notes TEXT,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE (student_id, scholarship_id)
);
CREATE TABLE IF NOT EXISTS documents (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
  doc_name TEXT NOT NULL,
  is_ready INTEGER NOT NULL DEFAULT 0,
  UNIQUE (student_id, doc_name)
);
