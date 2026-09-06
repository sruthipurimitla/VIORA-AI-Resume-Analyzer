from flask import Flask, render_template, request, redirect, url_for, session, flash
import os
import re
import json
import requests

from dotenv import load_dotenv
from werkzeug.security import generate_password_hash, check_password_hash

load_dotenv()


# ============================================================
# FLASK APP
# ============================================================

app = Flask(__name__)

app.secret_key = os.getenv(
    "FLASK_SECRET_KEY",
    "viora_secret_key_change_this"
)

UPLOAD_FOLDER = "uploads"

ALLOWED_EXTENSIONS = {
    "pdf",
    "docx"
}

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024

os.makedirs(UPLOAD_FOLDER, exist_ok=True)


# ============================================================
# OLLAMA CLOUD CONFIGURATION
# ============================================================

OLLAMA_API_KEY = os.getenv("OLLAMA_API_KEY", "").strip()

OLLAMA_MODEL = os.getenv(
    "OLLAMA_MODEL",
    "gpt-oss:20b-cloud"
)

OLLAMA_URL = os.getenv(
    "OLLAMA_URL",
    "https://ollama.com/api/chat"
)


# ============================================================
# TIDB CONFIGURATION
# ============================================================

TIDB_DATABASE_URL = os.getenv(
    "TIDB_DATABASE_URL",
    ""
).strip()

TIDB_HOST = os.getenv("TIDB_HOST", "").strip()
TIDB_PORT = int(os.getenv("TIDB_PORT", "4000"))
TIDB_USER = os.getenv("TIDB_USER", "").strip()
TIDB_PASSWORD = os.getenv("TIDB_PASSWORD", "").strip()
TIDB_DB_NAME = os.getenv(
    "TIDB_DB_NAME",
    "test"
).strip()

CA_PATH = os.getenv(
    "CA_PATH",
    ""
).strip()


# ============================================================
# DATABASE
# ============================================================

def get_db_connection():

    try:

        import pymysql

        connection_config = {
            "host": TIDB_HOST,
            "port": TIDB_PORT,
            "user": TIDB_USER,
            "password": TIDB_PASSWORD,
            "database": TIDB_DB_NAME,
            "autocommit": True,
            "charset": "utf8mb4",
            "connect_timeout": 15,
            "read_timeout": 30,
            "write_timeout": 30
        }

        # TiDB Cloud TLS configuration
        if CA_PATH:

            connection_config["ssl_verify_cert"] = True
            connection_config["ssl_verify_identity"] = True
            connection_config["ssl_ca"] = CA_PATH

        else:

            # Request encrypted connection.
            connection_config["ssl"] = {}

        return pymysql.connect(**connection_config)

    except Exception as e:

        print("TiDB connection error:", e)

        return None


def init_database():

    connection = get_db_connection()

    if connection is None:

        print(
            "WARNING: TiDB could not be connected."
        )

        return False

    try:

        with connection.cursor() as cursor:

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    name VARCHAR(150) NOT NULL,
                    email VARCHAR(255) NOT NULL UNIQUE,
                    password VARCHAR(255) NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS resumes (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    user_id INT NOT NULL,
                    filename VARCHAR(255) NOT NULL,
                    target_role VARCHAR(150) NOT NULL,
                    resume_text LONGTEXT,
                    analysis_json LONGTEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id)
                        REFERENCES users(id)
                        ON DELETE CASCADE
                )
                """
            )

        connection.close()

        print("TiDB database initialized.")

        return True

    except Exception as e:

        print(
            "Database initialization error:",
            e
        )

        try:
            connection.close()
        except Exception:
            pass

        return False


# ============================================================
# FILE HELPERS
# ============================================================

def allowed_file(filename):

    return (
        "." in filename
        and
        filename.rsplit(".", 1)[1].lower()
        in ALLOWED_EXTENSIONS
    )


def safe_filename(filename):

    filename = os.path.basename(filename)

    filename = re.sub(
        r"[^A-Za-z0-9._-]",
        "_",
        filename
    )

    return filename


# ============================================================
# RESUME TEXT EXTRACTION
# ============================================================

def extract_text_from_file(filepath):

    extension = (
        filepath
        .rsplit(".", 1)[1]
        .lower()
    )

    try:

        # -------------------------
        # PDF
        # -------------------------

        if extension == "pdf":

            try:

                from pypdf import PdfReader

            except ImportError:

                from PyPDF2 import PdfReader

            reader = PdfReader(filepath)

            text = ""

            for page in reader.pages:

                page_text = page.extract_text()

                if page_text:

                    text += page_text + "\n"

            return text.strip()


        # -------------------------
        # DOCX
        # -------------------------

        elif extension == "docx":

            from docx import Document

            document = Document(filepath)

            text = ""

            for paragraph in document.paragraphs:

                if paragraph.text.strip():

                    text += (
                        paragraph.text.strip()
                        + "\n"
                    )

            return text.strip()


    except Exception as e:

        print(
            "Resume extraction error:",
            e
        )

        return ""


    return ""


# ============================================================
# ROLE SKILLS
# ============================================================

ROLE_SKILLS = {

    "python developer": [
        "python",
        "flask",
        "django",
        "sql",
        "git",
        "api"
    ],

    "backend developer": [
        "python",
        "java",
        "node.js",
        "sql",
        "api",
        "git",
        "database"
    ],

    "data analyst": [
        "python",
        "sql",
        "pandas",
        "numpy",
        "excel",
        "power bi",
        "data analysis"
    ],

    "web developer": [
        "html",
        "css",
        "javascript",
        "react",
        "git",
        "api"
    ],

    "frontend developer": [
        "html",
        "css",
        "javascript",
        "react",
        "git"
    ],

    "java developer": [
        "java",
        "sql",
        "git",
        "api",
        "spring"
    ],

    "machine learning engineer": [
        "python",
        "machine learning",
        "pandas",
        "numpy",
        "tensorflow",
        "sql"
    ],

    "software developer": [
        "python",
        "java",
        "sql",
        "git",
        "api"
    ]
}


def normalize_role(role):

    role = role.lower().strip()

    role = re.sub(
        r"\s+",
        " ",
        role
    )

    aliases = {

        "python dev": "python developer",

        "python programmer":
            "python developer",

        "backend dev":
            "backend developer",

        "data analyst intern":
            "data analyst",

        "web dev":
            "web developer",

        "frontend dev":
            "frontend developer",

        "java dev":
            "java developer",

        "ml engineer":
            "machine learning engineer"
    }

    return aliases.get(
        role,
        role
    )


def get_role_skills(target_role):

    normalized_role = normalize_role(
        target_role
    )

    if normalized_role in ROLE_SKILLS:

        return ROLE_SKILLS[
            normalized_role
        ]

    # Partial matching
    for role, skills in ROLE_SKILLS.items():

        if (
            role in normalized_role
            or normalized_role in role
        ):

            return skills

    # Generic technical role
    return [
        "programming",
        "sql",
        "git",
        "api"
    ]


# ============================================================
# OLLAMA AI
# ============================================================

def ask_ollama(resume_text, target_role):

    if not OLLAMA_API_KEY:

        raise RuntimeError(
            "OLLAMA_API_KEY is missing from .env"
        )


    prompt = f"""
You are VIORA, an AI career and resume analysis assistant.

Analyze the resume below for the target job role.

TARGET ROLE:
{target_role}

RESUME:
-------------------------
{resume_text[:30000]}
-------------------------

Return ONLY valid JSON.

Use exactly this structure:

{{
  "summary": "A detailed but concise summary of the candidate and their suitability for the target role.",

  "skills": [
    "skill 1",
    "skill 2"
  ],

  "strengths": [
    "strength 1",
    "strength 2"
  ],

  "missing_skills": [
    "skill 1",
    "skill 2"
  ],

  "career_suggestions": [
    "career suggestion 1",
    "career suggestion 2",
    "career suggestion 3"
  ],

  "project_ideas": [
    "project idea 1",
    "project idea 2",
    "project idea 3"
  ],

  "interview_prep": [
    "interview question 1",
    "interview question 2",
    "interview question 3",
    "interview question 4"
  ],

  "areas_to_improve": [
    "area 1",
    "area 2"
  ]
}}

IMPORTANT RULES:

1. Only list skills that are actually present in the resume under "skills".
2. Do not invent experience, jobs, certifications, or projects.
3. Missing skills should be relevant to the target role.
4. Consider projects and academic work as practical experience when appropriate.
5. Keep recommendations realistic for a student or early-career candidate.
6. Do not give a generic response.
7. Base the analysis specifically on the resume.
"""


    headers = {

        "Authorization":
            f"Bearer {OLLAMA_API_KEY}",

        "Content-Type":
            "application/json"
    }


    payload = {

        "model": OLLAMA_MODEL,

        "messages": [
            {
                "role": "user",
                "content": prompt
            }
        ],

        "stream": False,

        "format": "json"
    }


    response = requests.post(
        OLLAMA_URL,
        headers=headers,
        json=payload,
        timeout=120
    )


    response.raise_for_status()

    data = response.json()

    content = (
        data
        .get("message", {})
        .get("content", "")
        .strip()
    )


    if not content:

        raise RuntimeError(
            "Ollama returned an empty response."
        )


    # Remove accidental markdown fences
    content = re.sub(
        r"^```json\s*",
        "",
        content,
        flags=re.IGNORECASE
    )

    content = re.sub(
        r"\s*```$",
        "",
        content
    )


    try:

        return json.loads(content)

    except json.JSONDecodeError:

        # Try extracting JSON object
        match = re.search(
            r"\{.*\}",
            content,
            re.DOTALL
        )

        if match:

            return json.loads(
                match.group(0)
            )

        raise RuntimeError(
            "AI returned invalid JSON."
        )


# ============================================================
# CLEAN AI DATA
# ============================================================

def clean_list(value):

    if value is None:

        return []


    if isinstance(value, list):

        result = []

        for item in value:

            item = str(item).strip()

            if item:

                result.append(item)

        return list(
            dict.fromkeys(result)
        )


    if isinstance(value, str):

        lines = value.splitlines()

        cleaned = []

        for line in lines:

            line = re.sub(
                r"^[\s•\-*0-9.)]+",
                "",
                line
            ).strip()

            if line:

                cleaned.append(line)

        return list(
            dict.fromkeys(cleaned)
        )


    return []


def normalize_skill(skill):

    skill = skill.lower().strip()

    skill = re.sub(
        r"[^\w+#. -]",
        "",
        skill
    )

    return skill


# ============================================================
# CALCULATE SCORES
# ============================================================

def calculate_scores(
    ai_data,
    target_role
):

    skills = clean_list(
        ai_data.get("skills")
    )

    ai_missing = clean_list(
        ai_data.get("missing_skills")
    )

    normalized_found = {
        normalize_skill(skill)
        for skill in skills
    }

    required_skills = get_role_skills(
        target_role
    )


    # -------------------------
    # Match score
    # -------------------------

    matched = []

    missing = []


    for required in required_skills:

        required_normalized = (
            normalize_skill(required)
        )

        found = False

        for skill in normalized_found:

            if (
                required_normalized == skill
                or
                required_normalized in skill
                or
                skill in required_normalized
            ):

                found = True
                break


        if found:

            matched.append(required)

        else:

            missing.append(required)


    if required_skills:

        match_score = round(
            (
                len(matched)
                /
                len(required_skills)
            )
            * 100
        )

    else:

        match_score = 0


    # -------------------------
    # Missing skills
    # -------------------------

    if missing:

        missing_skills = missing

    elif ai_missing:

        missing_skills = ai_missing

    else:

        missing_skills = []


    # -------------------------
    # Overall score
    # -------------------------

    strength_count = len(
        clean_list(
            ai_data.get("strengths")
        )
    )

    project_count = len(
        clean_list(
            ai_data.get("project_ideas")
        )
    )

    skill_score = min(
        30,
        len(skills) * 3
    )

    strength_score = min(
        20,
        strength_count * 4
    )

    project_score = min(
        10,
        project_count * 2
    )

    overall_score = round(
        (
            match_score * 0.40
            +
            skill_score
            +
            strength_score
            +
            project_score
        )
    )

    overall_score = max(
        0,
        min(
            100,
            overall_score
        )
    )


    return (
        overall_score,
        match_score,
        missing_skills
    )


# ============================================================
# COMPLETE RESUME ANALYSIS
# ============================================================

def analyze_resume(
    resume_text,
    target_role
):

    if not resume_text.strip():

        raise ValueError(
            "Could not extract text from the resume."
        )


    ai_data = ask_ollama(
        resume_text,
        target_role
    )


    skills = clean_list(
        ai_data.get("skills")
    )

    strengths = clean_list(
        ai_data.get("strengths")
    )

    career_suggestions = clean_list(
        ai_data.get(
            "career_suggestions"
        )
    )

    project_ideas = clean_list(
        ai_data.get(
            "project_ideas"
        )
    )

    interview_prep = clean_list(
        ai_data.get(
            "interview_prep"
        )
    )

    areas_to_improve = clean_list(
        ai_data.get(
            "areas_to_improve"
        )
    )


    (
        overall_score,
        match_score,
        missing_skills
    ) = calculate_scores(
        ai_data,
        target_role
    )


    summary = str(
        ai_data.get(
            "summary",
            ""
        )
    ).strip()


    if not summary:

        summary = (
            "VIORA analyzed your resume "
            f"for the {target_role} role."
        )


    # Make sure useful defaults exist
    if not strengths:

        strengths = [
            "Relevant skills identified "
            "from your resume."
        ]


    if not career_suggestions:

        career_suggestions = [
            f"Continue developing skills "
            f"for {target_role}.",
            "Build practical projects.",
            "Keep your GitHub profile updated."
        ]


    if not project_ideas:

        project_ideas = [
            f"Build a practical {target_role} project.",
            "Create an AI-powered application.",
            "Build a project using a real-world API."
        ]


    if not interview_prep:

        interview_prep = [
            f"Why are you interested in {target_role}?",
            "Explain one of your projects.",
            "What technical skill are you improving?",
            "Describe a technical problem you solved."
        ]


    return {

        "overall_score":
            overall_score,

        "match_score":
            match_score,

        "strengths":
            strengths,

        "skills":
            skills,

        "current_skills":
            skills,

        "missing_skills":
            missing_skills,

        "career_suggestions":
            career_suggestions,

        "project_ideas":
            project_ideas,

        "interview_prep":
            interview_prep,

        "interview_preparation":
            interview_prep,

        "areas_to_improve":
            areas_to_improve,

        "summary":
            summary
    }


# ============================================================
# HOME
# ============================================================

@app.route("/")
def home():

    return render_template(
        "index.html"
    )


# ============================================================
# SIGNUP
# ============================================================

@app.route(
    "/signup",
    methods=["GET", "POST"]
)
def signup():

    if request.method == "POST":

        name = request.form.get(
            "name",
            ""
        ).strip()

        email = request.form.get(
            "email",
            ""
        ).strip().lower()

        password = request.form.get(
            "password",
            ""
        ).strip()


        if not name or not email or not password:

            flash(
                "Please fill in all fields."
            )

            return redirect(
                url_for("signup")
            )


        if len(password) < 6:

            flash(
                "Password must contain at least 6 characters."
            )

            return redirect(
                url_for("signup")
            )


        connection = get_db_connection()


        # --------------------------------
        # TiDB signup
        # --------------------------------

        if connection:

            try:

                with connection.cursor() as cursor:

                    cursor.execute(
                        """
                        SELECT id
                        FROM users
                        WHERE email = %s
                        """,
                        (email,)
                    )

                    existing = cursor.fetchone()


                    if existing:

                        flash(
                            "An account with this email already exists."
                        )

                        connection.close()

                        return redirect(
                            url_for("login")
                        )


                    password_hash = (
                        generate_password_hash(
                            password
                        )
                    )


                    cursor.execute(
                        """
                        INSERT INTO users
                        (name, email, password)
                        VALUES (%s, %s, %s)
                        """,
                        (
                            name,
                            email,
                            password_hash
                        )
                    )


                    user_id = cursor.lastrowid


                connection.close()


                session["user_id"] = user_id
                session["user_name"] = name
                session["user_email"] = email


                return redirect(
                    url_for("dashboard")
                )


            except Exception as e:

                print(
                    "Signup database error:",
                    e
                )

                try:
                    connection.close()
                except Exception:
                    pass


        # --------------------------------
        # Temporary session fallback
        # --------------------------------

        session["user_id"] = None
        session["user_name"] = name
        session["user_email"] = email


        return redirect(
            url_for("dashboard")
        )


    return render_template(
        "signup.html"
    )


# ============================================================
# LOGIN
# ============================================================

@app.route(
    "/login",
    methods=["GET", "POST"]
)
def login():

    if request.method == "POST":

        email = request.form.get(
            "email",
            ""
        ).strip().lower()

        password = request.form.get(
            "password",
            ""
        ).strip()


        if not email or not password:

            flash(
                "Please enter your email and password."
            )

            return redirect(
                url_for("login")
            )


        connection = get_db_connection()


        # --------------------------------
        # TiDB login
        # --------------------------------

        if connection:

            try:

                with connection.cursor() as cursor:

                    cursor.execute(
                        """
                        SELECT id, name, email, password
                        FROM users
                        WHERE email = %s
                        """,
                        (email,)
                    )

                    user = cursor.fetchone()


                connection.close()


                if user:

                    if check_password_hash(
                        user["password"],
                        password
                    ):

                        session["user_id"] = user["id"]
                        session["user_name"] = user["name"]
                        session["user_email"] = user["email"]

                        return redirect(
                            url_for("dashboard")
                        )


                    flash(
                        "Incorrect email or password."
                    )

                    return redirect(
                        url_for("login")
                    )


            except Exception as e:

                print(
                    "Login database error:",
                    e
                )

                try:
                    connection.close()
                except Exception:
                    pass


        # --------------------------------
        # Session fallback
        # --------------------------------

        session["user_id"] = None
        session["user_email"] = email
        session["user_name"] = (
            email.split("@")[0]
        )


        return redirect(
            url_for("dashboard")
        )


    return render_template(
        "login.html"
    )


# ============================================================
# LOGOUT
# ============================================================

@app.route("/logout")
def logout():

    session.clear()

    return redirect(
        url_for("home")
    )


# ============================================================
# DASHBOARD
# ============================================================

@app.route("/dashboard")
def dashboard():

    if "user_email" not in session:

        return redirect(
            url_for("login")
        )


    user_name = session.get(
        "user_name",
        "Career Explorer"
    )


    return render_template(
        "dashboard.html",
        user_name=user_name
    )


# ============================================================
# UPLOAD RESUME
# ============================================================

@app.route(
    "/upload",
    methods=["GET", "POST"]
)
def upload():

    if "user_email" not in session:

        return redirect(
            url_for("login")
        )


    if request.method == "POST":

        resume = request.files.get(
            "resume"
        )

        target_role = request.form.get(
            "target_role",
            ""
        ).strip()


        # -------------------------
        # Validate file
        # -------------------------

        if not resume or not resume.filename:

            flash(
                "Please select your resume."
            )

            return redirect(
                url_for("upload")
            )


        if not allowed_file(
            resume.filename
        ):

            flash(
                "Only PDF and DOCX files are supported."
            )

            return redirect(
                url_for("upload")
            )


        if not target_role:

            flash(
                "Please enter your target job role."
            )

            return redirect(
                url_for("upload")
            )


        # -------------------------
        # Save file
        # -------------------------

        filename = safe_filename(
            resume.filename
        )


        filepath = os.path.join(
            app.config["UPLOAD_FOLDER"],
            filename
        )


        resume.save(filepath)


        # -------------------------
        # Extract text
        # -------------------------

        resume_text = (
            extract_text_from_file(
                filepath
            )
        )


        if not resume_text.strip():

            flash(
                "I couldn't read any text from this resume. "
                "Please try another PDF or DOCX file."
            )

            return redirect(
                url_for("upload")
            )


        # -------------------------
        # AI analysis
        # -------------------------

        try:

            analysis = analyze_resume(
                resume_text,
                target_role
            )


        except Exception as e:

            print(
                "AI analysis error:",
                e
            )

            flash(
                f"AI analysis failed: {str(e)}"
            )

            return redirect(
                url_for("upload")
            )


        # -------------------------
        # Store in session
        # -------------------------

        session["analysis"] = analysis
        session["target_role"] = target_role


        # -------------------------
        # Save to TiDB
        # -------------------------

        user_id = session.get(
            "user_id"
        )


        if user_id:

            connection = get_db_connection()


            if connection:

                try:

                    with connection.cursor() as cursor:

                        cursor.execute(
                            """
                            INSERT INTO resumes
                            (
                                user_id,
                                filename,
                                target_role,
                                resume_text,
                                analysis_json
                            )
                            VALUES
                            (%s, %s, %s, %s, %s)
                            """,
                            (
                                user_id,
                                filename,
                                target_role,
                                resume_text,
                                json.dumps(
                                    analysis,
                                    ensure_ascii=False
                                )
                            )
                        )


                    connection.close()


                except Exception as e:

                    print(
                        "Resume database save error:",
                        e
                    )

                    try:
                        connection.close()
                    except Exception:
                        pass


        return redirect(
            url_for("results")
        )


    return render_template(
        "upload.html"
    )


# ============================================================
# RESULTS
# ============================================================

@app.route("/results")
def results():

    if "user_email" not in session:

        return redirect(
            url_for("login")
        )


    analysis = session.get(
        "analysis"
    )


    if not analysis:

        return redirect(
            url_for("upload")
        )


    target_role = session.get(
        "target_role",
        "Your Target Role"
    )


    return render_template(
        "results.html",
        analysis=analysis,
        target_role=target_role
    )


# ============================================================
# DATABASE TEST
# ============================================================

@app.route("/test-db")
def test_db():

    connection = get_db_connection()


    if connection is None:

        return {
            "status": "error",
            "message": "Could not connect to TiDB."
        }


    try:

        with connection.cursor() as cursor:

            cursor.execute(
                "SELECT 1 AS test"
            )

            result = cursor.fetchone()


        connection.close()


        return {
            "status": "success",
            "message": "VIORA is connected to TiDB.",
            "result": result
        }


    except Exception as e:

        try:
            connection.close()
        except Exception:
            pass


        return {
            "status": "error",
            "message": str(e)
        }


# ============================================================
# AI TEST
# ============================================================

@app.route("/test-ai")
def test_ai():

    if not OLLAMA_API_KEY:

        return {
            "status": "error",
            "message":
                "OLLAMA_API_KEY is missing."
        }


    try:

        test_data = ask_ollama(
            """
            Resume:
            Python, Flask, SQL, Git,
            HTML, CSS and JavaScript.
            Student with academic projects.
            """,
            "Python Developer"
        )


        return {
            "status": "success",
            "message":
                "VIORA AI connection is working.",
            "analysis":
                test_data
        }


    except Exception as e:

        return {
            "status": "error",
            "message": str(e)
        }


# ============================================================
# START APPLICATION
# ============================================================

if __name__ == "__main__":

    print()
    print("======================================")
    print("        VIORA AI RESUME ANALYZER")
    print("======================================")
    print()


    # Initialize TiDB
    init_database()


    print(
        f"Ollama model: {OLLAMA_MODEL}"
    )

    print(
        "Server: http://127.0.0.1:5000"
    )

    print()


    app.run(
        debug=True,
        host="127.0.0.1",
        port=5000
    )