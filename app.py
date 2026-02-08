import sqlite3
from flask import Flask, render_template, request, redirect, session, jsonify
from datetime import date

app = Flask(__name__)
app.secret_key = "freelance-flow-secret"

# ---------------- DATABASE ----------------

def get_db_connection():
    conn = sqlite3.connect("database.db")
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db_connection()



    conn.execute("""
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER,
    user_id INTEGER,
    message TEXT,
    timestamp TEXT
)
""")


    conn.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL
    )
    """)

    conn.execute("""
    CREATE TABLE IF NOT EXISTS projects (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        created_by INTEGER
    )
    """)

    conn.execute("""
    CREATE TABLE IF NOT EXISTS project_members (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER,
        user_id INTEGER
    )
    """)

    conn.execute("""
    CREATE TABLE IF NOT EXISTS tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER,
        title TEXT,
        status TEXT,
        due_date TEXT
    )
    """)

    conn.commit()
    conn.close()


init_db()

# ---------------- AUTH ----------------

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        conn = get_db_connection()
        conn.execute(
            "INSERT INTO users (username, password) VALUES (?, ?)",
            (request.form["username"], request.form["password"])
        )
        conn.commit()
        conn.close()
        return redirect("/login")
    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        conn = get_db_connection()
        user = conn.execute(
            "SELECT * FROM users WHERE username=? AND password=?",
            (request.form["username"], request.form["password"])
        ).fetchone()
        conn.close()

        if user:
            session["user_id"] = user["id"]
            return redirect("/dashboard")

        return "Invalid credentials"

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")

# ---------------- DASHBOARD ----------------

@app.route("/")
def root():
    return redirect("/dashboard")


@app.route("/dashboard")
def dashboard():
    if "user_id" not in session:
        return redirect("/login")

    conn = get_db_connection()

    project_count = conn.execute("""
        SELECT COUNT(*) FROM project_members WHERE user_id=?
    """, (session["user_id"],)).fetchone()[0]

    pending_tasks = conn.execute("""
        SELECT COUNT(*) FROM tasks 
        WHERE status!='Completed' 
        AND project_id IN (
            SELECT project_id FROM project_members WHERE user_id=?
        )
    """, (session["user_id"],)).fetchone()[0]

    conn.close()

    return render_template(
        "dashboard.html",
        project_count=project_count,
        pending_tasks=pending_tasks
    )

# ---------------- CLIENTS ----------------

@app.route("/clients")
def clients():
    if "user_id" not in session:
        return redirect("/login")

    conn = get_db_connection()

    clients = conn.execute("""
        SELECT DISTINCT u.id, u.username
        FROM users u
        JOIN project_members pm ON u.id = pm.user_id
        WHERE pm.project_id IN (
            SELECT project_id FROM project_members WHERE user_id=?
        )
        AND u.id != ?
    """, (session["user_id"], session["user_id"])).fetchall()

    conn.close()
    return render_template("clients.html", clients=clients)


@app.route("/client-projects/<int:client_id>")
def client_projects(client_id):
    if "user_id" not in session:
        return redirect("/login")

    conn = get_db_connection()

    projects = conn.execute("""
        SELECT p.*
        FROM projects p
        JOIN project_members pm1 ON p.id = pm1.project_id
        JOIN project_members pm2 ON p.id = pm2.project_id
        WHERE pm1.user_id=? AND pm2.user_id=?
    """, (session["user_id"], client_id)).fetchall()

    conn.close()
    return render_template("projects.html", projects=projects)

# ---------------- PROJECTS ----------------

@app.route("/projects")
def projects():
    if "user_id" not in session:
        return redirect("/login")

    conn = get_db_connection()
    projects = conn.execute("""
        SELECT p.*
        FROM projects p
        JOIN project_members pm ON p.id = pm.project_id
        WHERE pm.user_id=?
    """, (session["user_id"],)).fetchall()
    conn.close()

    return render_template("projects.html", projects=projects)


@app.route("/create-project", methods=["POST"])
def create_project():
    data = request.get_json()

    conn = get_db_connection()
    cur = conn.execute(
        "INSERT INTO projects (title, created_by) VALUES (?, ?)",
        (data["title"], session["user_id"])
    )
    project_id = cur.lastrowid

    conn.execute(
        "INSERT INTO project_members (project_id, user_id) VALUES (?, ?)",
        (project_id, session["user_id"])
    )

    conn.commit()
    conn.close()

    return jsonify({"message": "Project created"})


@app.route("/invite-user", methods=["POST"])
def invite_user():
    data = request.get_json()

    conn = get_db_connection()
    user = conn.execute(
        "SELECT id FROM users WHERE username=?",
        (data["username"],)
    ).fetchone()

    if not user:
        conn.close()
        return jsonify({"error": "User not found"}), 404

    conn.execute(
        "INSERT INTO project_members (project_id, user_id) VALUES (?, ?)",
        (data["project_id"], user["id"])
    )

    conn.commit()
    conn.close()
    return jsonify({"message": "Client invited"})


from datetime import datetime

@app.route("/chat/<int:project_id>")
def chat_page(project_id):
    if "user_id" not in session:
        return redirect("/login")

    conn = get_db_connection()

    # check access
    access = conn.execute(
        "SELECT 1 FROM project_members WHERE project_id=? AND user_id=?",
        (project_id, session["user_id"])
    ).fetchone()

    if not access:
        conn.close()
        return "Access denied"

    messages = conn.execute("""
        SELECT m.message, m.timestamp, u.username
        FROM messages m
        JOIN users u ON m.user_id = u.id
        WHERE m.project_id=?
        ORDER BY m.id ASC
    """, (project_id,)).fetchall()

    conn.close()
    return render_template("chat.html", messages=messages, project_id=project_id)


@app.route("/send-message", methods=["POST"])
def send_message():
    if "user_id" not in session:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json()

    conn = get_db_connection()

    # access check
    access = conn.execute(
        "SELECT 1 FROM project_members WHERE project_id=? AND user_id=?",
        (data["project_id"], session["user_id"])
    ).fetchone()

    if not access:
        conn.close()
        return jsonify({"error": "Access denied"}), 403

    conn.execute(
        "INSERT INTO messages (project_id, user_id, message, timestamp) VALUES (?, ?, ?, ?)",
        (data["project_id"], session["user_id"], data["message"],
         datetime.now().strftime("%Y-%m-%d %H:%M"))
    )

    conn.commit()
    conn.close()
    return jsonify({"message": "sent"})

# ---------------- RUN ----------------

if __name__ == "__main__":
    app.run(debug=True)
