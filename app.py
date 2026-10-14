from flask import Flask, render_template, request, redirect, url_for, session, flash
from datetime import date as date_cls

app = Flask(__name__)
app.secret_key = "secret123"

# ===== IN-MEMORY STORAGE =====
INSTRUCTOR = {"username": "teacher", "password": "1234"}

# Courses: { "course_name": [list of students] }
COURSES = {
    "BSIT 1-A": ["Alice", "Bob", "Charlie"],
    "BSIT 1-B": ["Diana", "Ethan"],
}

# Attendance records: [{date, course, students: {name: status}}]
ATTENDANCE_RECORDS = []

# Reminders: [{id, date, title, note, color, done}]
REMINDERS = []
_REMINDER_ID = [0]

def _next_reminder_id():
    _REMINDER_ID[0] += 1
    return _REMINDER_ID[0]


# ===== COURSE STATS HELPER =====
def _build_course_stats():
    """Precompute per-course stats for the courses modal."""
    course_sessions = {}
    course_last_date = {}
    course_recent = {}
    course_attendance = {}

    for rec in ATTENDANCE_RECORDS:
        c = rec["course"]
        course_sessions[c] = course_sessions.get(c, 0) + 1

        prev = course_last_date.get(c)
        if not prev or rec["date"] > prev:
            course_last_date[c] = rec["date"]

        counts = {"Present": 0, "Late": 0, "Absent": 0, "Excused": 0}
        for status in rec["students"].values():
            if status in counts:
                counts[status] += 1

        course_recent.setdefault(c, []).append({
            "date": rec["date"],
            "present": counts["Present"],
            "late":    counts["Late"],
            "absent":  counts["Absent"],
            "excused": counts["Excused"],
        })

        agg = course_attendance.setdefault(c, {
            "present": 0, "late": 0, "absent": 0, "excused": 0
        })
        agg["present"] += counts["Present"]
        agg["late"]    += counts["Late"]
        agg["absent"]  += counts["Absent"]
        agg["excused"] += counts["Excused"]

    for c in course_recent:
        course_recent[c] = sorted(
            course_recent[c], key=lambda x: x["date"], reverse=True
        )[:3]

    for c, agg in course_attendance.items():
        total = agg["present"] + agg["late"] + agg["absent"] + agg["excused"]
        if total == 0:
            agg.update({
                "present_pct": 0, "late_pct": 0,
                "absent_pct": 0, "excused_pct": 0, "rate": 0
            })
        else:
            agg["present_pct"] = round(agg["present"] / total * 100, 1)
            agg["late_pct"]    = round(agg["late"]    / total * 100, 1)
            agg["absent_pct"]  = round(agg["absent"]  / total * 100, 1)
            agg["excused_pct"] = round(agg["excused"] / total * 100, 1)
            agg["rate"] = round((agg["present"] + agg["late"]) / total * 100)

    return course_sessions, course_last_date, course_recent, course_attendance


# ===== CONTEXT PROCESSOR =====
@app.context_processor
def inject_globals():
    # Build search index: courses + students
    search_index = []
    for course, students in COURSES.items():
        search_index.append({
            "type": "course",
            "label": course,
            "sub": f"{len(students)} student(s)",
            "url": url_for("attendance", course=course),
            "icon": "📚",
        })
        for s in students:
            search_index.append({
                "type": "student",
                "label": s,
                "sub": course,
                "url": url_for("students"),
                "icon": "👤",
            })

    # Notifications: reminders + attendance sessions
    notifications = []
    today_iso = date_cls.today().isoformat()

    # Reminders (upcoming first, sorted by date)
    active_reminders = [r for r in REMINDERS if not r["done"]]
    active_reminders.sort(key=lambda r: r["date"])
    for r in active_reminders[:5]:
        is_due = r["date"] == today_iso
        is_overdue = r["date"] < today_iso
        prefix = "⏰ Overdue · " if is_overdue else ("🔔 Due today · " if is_due else "🗓 ")
        notifications.append({
            "title": prefix + r["title"],
            "sub": r["date"] + (f" · {r['note']}" if r["note"] else ""),
            "url": url_for("dashboard") + "#calendar",
            "type": "reminder",
            "color": r.get("color", "purple"),
        })

    # Attendance sessions
    for rec in reversed(ATTENDANCE_RECORDS[-3:]):
        counts = {"Present": 0, "Late": 0, "Absent": 0, "Excused": 0}
        for status in rec["students"].values():
            if status in counts:
                counts[status] += 1
        notifications.append({
            "title": f"{rec['course']} attendance saved",
            "sub": f"{rec['date']} · {counts['Present']} present, {counts['Absent']} absent",
            "url": url_for("records"),
            "type": "session",
            "color": "blue",
        })

    return {
        "courses": COURSES,
        "total_sessions": len(ATTENDANCE_RECORDS),
        "records": ATTENDANCE_RECORDS[-3:] if ATTENDANCE_RECORDS else [],
        "search_index": search_index,
        "notifications": notifications,
        "unread_count": len(notifications),
        "reminders": REMINDERS,
    }


# ===== AUTH =====
@app.route("/")
def home():
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        if username == INSTRUCTOR["username"] and password == INSTRUCTOR["password"]:
            session["instructor"] = username
            return redirect(url_for("dashboard"))
        flash("Invalid credentials. Try again.")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.pop("instructor", None)
    flash("Logged out successfully.")
    return redirect(url_for("login"))


# ===== DASHBOARD =====
@app.route("/dashboard")
def dashboard():
    if "instructor" not in session:
        return redirect(url_for("login"))

    total_students = sum(len(s) for s in COURSES.values())
    total_present = sum(
        1
        for rec in ATTENDANCE_RECORDS
        for status in rec["students"].values()
        if status == "Present"
    )

    return render_template(
        "dashboard.html",
        active_page="dashboard",
        instructor=session["instructor"],
        total_courses=len(COURSES),
        total_students=total_students,
        total_sessions=len(ATTENDANCE_RECORDS),
        total_present=total_present,
    )


# ===== COURSES =====
@app.route("/courses", methods=["GET", "POST"])
def courses():
    if "instructor" not in session:
        return redirect(url_for("login"))

    if request.method == "POST":
        action = request.form.get("action")

        if action == "add":
            name = request.form.get("course_name", "").strip()
            if name and name not in COURSES:
                COURSES[name] = []
                flash(f"✅ Course '{name}' added.")
            else:
                flash("⚠️ Course already exists or invalid.")

        elif action == "edit":
            old = request.form.get("old_name")
            new = request.form.get("new_name", "").strip()
            if old in COURSES and new and new not in COURSES:
                COURSES[new] = COURSES.pop(old)
                for rec in ATTENDANCE_RECORDS:
                    if rec["course"] == old:
                        rec["course"] = new
                flash(f"✅ Renamed '{old}' to '{new}'.")
            else:
                flash("⚠️ Rename failed.")

        elif action == "delete":
            name = request.form.get("course_name")
            if name in COURSES:
                del COURSES[name]
                ATTENDANCE_RECORDS[:] = [
                    r for r in ATTENDANCE_RECORDS if r["course"] != name
                ]
                flash(f"🗑️ Course '{name}' deleted.")

        return redirect(url_for("courses"))

    course_sessions, course_last_date, course_recent, course_attendance = _build_course_stats()

    return render_template(
        "courses.html",
        active_page="courses",
        course_sessions=course_sessions,
        course_last_date=course_last_date,
        course_recent=course_recent,
        course_attendance=course_attendance,
    )


# ===== STUDENTS =====
@app.route("/students", methods=["GET", "POST"])
def students():
    if "instructor" not in session:
        return redirect(url_for("login"))

    if request.method == "POST":
        action = request.form.get("action")
        course = request.form.get("course")

        if course not in COURSES:
            flash("⚠️ Course not found.")
            return redirect(url_for("students"))

        if action == "add":
            name = request.form.get("student_name", "").strip()
            if name and name not in COURSES[course]:
                COURSES[course].append(name)
                flash(f"✅ Student '{name}' added to {course}.")

        elif action == "edit":
            old = request.form.get("old_name")
            new = request.form.get("new_name", "").strip()
            if old in COURSES[course] and new:
                idx = COURSES[course].index(old)
                COURSES[course][idx] = new
                for rec in ATTENDANCE_RECORDS:
                    if rec["course"] == course and old in rec["students"]:
                        rec["students"][new] = rec["students"].pop(old)
                flash(f"✅ Renamed '{old}' to '{new}'.")

        elif action == "delete":
            name = request.form.get("student_name")
            if name in COURSES[course]:
                COURSES[course].remove(name)
                for rec in ATTENDANCE_RECORDS:
                    if rec["course"] == course:
                        rec["students"].pop(name, None)
                flash(f"🗑️ Removed '{name}' from {course}.")

        return redirect(url_for("students", course=course))

    return render_template("students.html", active_page="students")


# ===== ATTENDANCE =====
@app.route("/attendance", methods=["GET", "POST"])
def attendance():
    if "instructor" not in session:
        return redirect(url_for("login"))

    selected_course = request.args.get("course") or (next(iter(COURSES), None))

    if request.method == "POST":
        form_date = request.form.get("date")
        course = request.form.get("course")

        if not form_date or course not in COURSES:
            flash("⚠️ Invalid session details.")
            return redirect(url_for("attendance"))

        students_status = {}
        for idx, student in enumerate(COURSES[course], start=1):
            status = request.form.get(f"status_{idx}", "Present")
            if status not in ("Present", "Late", "Absent", "Excused"):
                status = "Present"
            students_status[student] = status

        ATTENDANCE_RECORDS.append({
            "date": form_date,
            "course": course,
            "students": students_status,
        })
        flash(f"✅ Attendance saved for {course}!")
        return redirect(url_for("records"))

    return render_template(
        "attendance.html",
        active_page="attendance",
        selected_course=selected_course,
        today=date_cls.today().isoformat(),
    )


# ===== RECORDS =====
@app.route("/records")
def records():
    if "instructor" not in session:
        return redirect(url_for("login"))

    summary = {}
    for rec in ATTENDANCE_RECORDS:
        for student, status in rec["students"].items():
            key = (rec["course"], student)
            summary.setdefault(key, {"Present": 0, "Late": 0, "Absent": 0, "Excused": 0})
            summary[key][status] += 1

    sorted_records = sorted(ATTENDANCE_RECORDS, key=lambda r: r["date"], reverse=True)

    return render_template(
        "records.html",
        active_page="records",
        records=sorted_records,
        summary=summary,
    )


# ===== REMINDERS =====
@app.route("/reminders/add", methods=["POST"])
def reminders_add():
    if "instructor" not in session:
        return redirect(url_for("login"))

    date = request.form.get("date", "").strip()
    title = request.form.get("title", "").strip()
    note = request.form.get("note", "").strip()
    color = request.form.get("color", "purple")

    if not date or not title:
        flash("⚠️ Date and title are required.")
        return redirect(url_for("dashboard") + "#calendar")

    REMINDERS.append({
        "id": _next_reminder_id(),
        "date": date,
        "title": title,
        "note": note,
        "color": color,
        "done": False,
    })
    flash(f"✅ Reminder '{title}' added for {date}.")
    return redirect(url_for("dashboard") + "#calendar")


@app.route("/reminders/<int:rid>/delete", methods=["POST"])
def reminders_delete(rid):
    if "instructor" not in session:
        return redirect(url_for("login"))

    global REMINDERS
    REMINDERS = [r for r in REMINDERS if r["id"] != rid]
    flash("🗑️ Reminder removed.")
    return redirect(url_for("dashboard") + "#calendar")


@app.route("/reminders/<int:rid>/toggle", methods=["POST"])
def reminders_toggle(rid):
    if "instructor" not in session:
        return redirect(url_for("login"))

    for r in REMINDERS:
        if r["id"] == rid:
            r["done"] = not r["done"]
            break
    return redirect(url_for("dashboard") + "#calendar")


if __name__ == "__main__":
    app.run(debug=True)