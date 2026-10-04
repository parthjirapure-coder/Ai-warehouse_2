from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from pathlib import Path
from datetime import datetime
import qrcode
import uuid

BASE_DIR = Path(__file__).resolve().parent
QR_FOLDER = BASE_DIR / "static" / "qrcodes"
QR_FOLDER.mkdir(parents=True, exist_ok=True)
ISSUES_FOLDER = BASE_DIR / "static" / "issues"
ISSUES_FOLDER.mkdir(parents=True, exist_ok=True)

app = Flask(__name__)
app.config["SECRET_KEY"] = "warehouse-ai-v3-change-this"
app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{BASE_DIR / 'warehouse.db'}"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db = SQLAlchemy(app)


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(50), unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=False)
    password = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(30), nullable=False)
    qr_token = db.Column(db.String(100), unique=True, nullable=False)
    active = db.Column(db.Boolean, default=True)


class Movement(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    item = db.Column(db.String(150), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    direction = db.Column(db.String(10), nullable=False)
    note = db.Column(db.String(500), default="")
    created_by = db.Column(db.String(50), nullable=False)
    status = db.Column(db.String(20), default="Pending")
    verified_by = db.Column(db.String(50), default="")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class IssueComment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    issue_id = db.Column(db.Integer, db.ForeignKey('issue.id'), nullable=False)
    sender_id = db.Column(db.String(50), nullable=False)
    body = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Issue(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    item = db.Column(db.String(150), nullable=False)
    issue_type = db.Column(db.String(50), nullable=False)
    description = db.Column(db.String(500), default="")
    photo = db.Column(db.String(255), default="")
    created_by = db.Column(db.String(50), nullable=False)
    status = db.Column(db.String(30), default="Open")
    resolved_by = db.Column(db.String(50), default="")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    comments = db.relationship('IssueComment', backref='issue', lazy=True, order_by='IssueComment.created_at.asc()')


class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.String(50), nullable=False)
    receiver_id = db.Column(db.String(50), nullable=False)
    subject = db.Column(db.String(150), nullable=False)
    body = db.Column(db.String(2000), nullable=False)
    is_read = db.Column(db.Boolean, default=False)
    msg_type = db.Column(db.String(20), default="confidential")
    attachment = db.Column(db.String(255), default="")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    deleted_by_sender = db.Column(db.Boolean, default=False)
    deleted_by_receiver = db.Column(db.Boolean, default=False)


def qr_file(user):
    return QR_FOLDER / f"{user.user_id}.png"


def generate_qr(user):
    data = f"http://127.0.0.1:5000/qr/{user.qr_token}"
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white").convert('RGB')
    img.save(qr_file(user))


def init_db():
    with app.app_context():
        db.create_all()
        supervisor = User.query.filter_by(user_id="SUP001").first()
        if not supervisor:
            supervisor = User(
                user_id="SUP001",
                name="Main Supervisor",
                password=generate_password_hash("admin123"),
                role="supervisor",
                qr_token=str(uuid.uuid4()),
                active=True,
            )
            db.session.add(supervisor)
            db.session.commit()

        for user in User.query.all():
            if not qr_file(user).exists():
                generate_qr(user)


def me():
    if "user_id" not in session:
        return None
    return db.session.get(User, session["user_id"])


def login_required():
    return me()


def role_dashboard(user):
    if user.role == "supervisor":
        return redirect(url_for("supervisor_dashboard"))
    if user.role == "manager":
        return redirect(url_for("manager_dashboard"))
    return redirect(url_for("employee_dashboard"))


@app.route("/", methods=["GET", "POST"])
def login():
    if session.get("user_id"):
        return role_dashboard(me())

    if request.method == "POST":
        uid = request.form.get("user_id", "").strip().upper()
        password = request.form.get("password", "")
        user = User.query.filter_by(user_id=uid).first()

        if user and user.active and check_password_hash(user.password, password):
            session["user_id"] = user.id
            return role_dashboard(user)

        flash("Invalid User ID or Password.", "error")

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


def dashboard_stats():
    total_in = db.session.query(
        db.func.coalesce(db.func.sum(Movement.quantity), 0)
    ).filter(Movement.direction == "IN", Movement.status != "Deleted").scalar()

    total_out = db.session.query(
        db.func.coalesce(db.func.sum(Movement.quantity), 0)
    ).filter(Movement.direction == "OUT", Movement.status != "Deleted").scalar()

    open_issues = Issue.query.filter_by(status="Open").count()
    employees = User.query.filter_by(role="employee", active=True).count()
    managers = User.query.filter_by(role="manager", active=True).count()

    return int(total_in or 0), int(total_out or 0), open_issues, employees, managers


@app.route("/dashboard")
def dashboard():
    user = login_required()
    if not user:
        return redirect(url_for("login"))
    return role_dashboard(user)


@app.route("/export/weekly", methods=["POST"])
def export_weekly():
    user = login_required()
    if not user or user.role != "manager":
        return redirect(url_for("dashboard"))
    
    import csv, time
    from pathlib import Path
    
    movements = Movement.query.order_by(Movement.created_at.desc()).all()
    issues = Issue.query.order_by(Issue.created_at.desc()).all()
    
    filename = f"weekly_report_{int(time.time())}.csv"
    filepath = Path(app.root_path) / "static" / "reports" / filename
    
    with open(filepath, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(["--- LIVE ACTIVITY (MOVEMENTS) ---"])
        writer.writerow(["Date", "Item", "Quantity", "Direction", "Status", "Verified By"])
        for m in movements:
            writer.writerow([m.created_at.strftime("%Y-%m-%d %H:%M"), m.item, m.quantity, m.direction, m.status, m.verified_by])
            
        writer.writerow([])
        writer.writerow(["--- ISSUES & FLAGS ---"])
        writer.writerow(["Date", "Item", "Type", "Description", "Status", "Resolved By"])
        for i in issues:
            writer.writerow([i.created_at.strftime("%Y-%m-%d %H:%M"), i.item, i.issue_type, i.description, i.status, i.resolved_by])
            
    supervisors = User.query.filter_by(role="supervisor").all()
    for sup in supervisors:
        msg = Message(
            sender_id=user.user_id,
            receiver_id=sup.user_id,
            subject=f"Weekly Report ({datetime.utcnow().strftime('%d %b')})",
            body="Manager submitted the weekly activity and issues report.",
            attachment=filename,
            msg_type="confidential"
        )
        db.session.add(msg)
    db.session.commit()
    
    flash("Weekly report compiled and securely sent to Supervisors.", "success")
    return redirect(url_for("dashboard"))


@app.route("/send_report/employee", methods=["POST"])
def send_employee_report():
    user = login_required()
    if not user or user.role != "manager":
        flash("Unauthorized.", "error")
        return redirect(url_for("login"))
        
    import csv, time
    from pathlib import Path
    
    users = User.query.filter_by(role="employee").order_by(User.name).all()
    filename = f"employee_report_{int(time.time())}.csv"
    filepath = Path(app.root_path) / "static" / "reports" / filename
    
    with open(filepath, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(["Employee Name", "Employee ID", "Action Date", "Item Logged", "Quantity", "Direction", "Verification Status", "Verified By"])
        for u in users:
            movements = Movement.query.filter_by(created_by=u.user_id).order_by(Movement.created_at.desc()).all()
            for m in movements:
                writer.writerow([u.name, u.user_id, m.created_at.strftime("%Y-%m-%d %H:%M"), m.item, m.quantity, m.direction, m.status, m.verified_by])
                
    supervisors = User.query.filter_by(role="supervisor").all()
    for sup in supervisors:
        msg = Message(
            sender_id=user.user_id,
            receiver_id=sup.user_id,
            subject="Employee Report",
            body="Manager submitted the Employee Report.",
            attachment=filename,
            msg_type="confidential"
        )
        db.session.add(msg)
    db.session.commit()
    
    flash("Employee Report compiled and securely sent to Supervisors.", "success")
    return redirect(url_for("dashboard"))


@app.route("/export/users/<role>", methods=["POST"])
def export_users(role):
    user = login_required()
    if not user:
        return redirect(url_for("login"))
    
    if role not in ["employee", "manager"]:
        flash("Invalid report type.", "error")
        return redirect(url_for("dashboard"))
        
    if role == "manager" and user.role != "supervisor":
        flash("Unauthorized to export manager report.", "error")
        return redirect(url_for("dashboard"))
        
    if user.role not in ["supervisor", "manager"]:
        return redirect(url_for("dashboard"))
    
    import csv, time
    from pathlib import Path
    from flask import send_file
    
    users = User.query.filter_by(role=role).order_by(User.name).all()
    filename = f"{role}_report_{int(time.time())}.csv"
    filepath = Path(app.root_path) / "static" / "reports" / filename
    
    with open(filepath, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        if role == "employee":
            writer.writerow(["Employee Name", "Employee ID", "Action Date", "Item Logged", "Quantity", "Direction", "Verification Status", "Verified By"])
        else:
            writer.writerow(["Name", "User ID", "Status", "Logs Verified", "Issues Resolved", "Performance Score"])
        
        for u in users:
            status = "Active" if u.active else "Disabled"
            if role == "employee":
                movements = Movement.query.filter_by(created_by=u.user_id).order_by(Movement.created_at.desc()).all()
                for m in movements:
                    writer.writerow([u.name, u.user_id, m.created_at.strftime("%Y-%m-%d %H:%M"), m.item, m.quantity, m.direction, m.status, m.verified_by])
            else:
                verified = Movement.query.filter_by(verified_by=u.user_id).count()
                resolved = Issue.query.filter_by(resolved_by=u.user_id).count()
                score = (verified * 2) + (resolved * 5)
                writer.writerow([u.name, u.user_id, status, verified, resolved, score])
            
    return send_file(filepath, as_attachment=True)


@app.route("/supervisor")
def supervisor_dashboard():
    user = login_required()
    if not user:
        return redirect(url_for("login"))
    if user.role != "supervisor":
        return role_dashboard(user)

    tin, tout, issues_count, employees, managers = dashboard_stats()
    users = User.query.order_by(User.role, User.name).all()
    movements = Movement.query.order_by(Movement.id.desc()).limit(25).all()
    open_issues = Issue.query.filter_by(status="Open").order_by(Issue.id.desc()).all()
    resolved_issues = Issue.query.filter_by(status="Resolved").order_by(Issue.id.desc()).limit(15).all()
    
    # Separate normal messages and report attachments
    all_conf_messages = Message.query.filter(Message.msg_type=="confidential", Message.attachment=="").order_by(Message.id.desc()).all()
    
    unique_conversations = []
    seen_pairs = set()
    for m in all_conf_messages:
        pair = tuple(sorted([m.sender_id, m.receiver_id]))
        if pair not in seen_pairs:
            seen_pairs.add(pair)
            unique_conversations.append(m)
            if len(unique_conversations) >= 20:
                break
                
    messages = unique_conversations
    reports = Message.query.filter(Message.receiver_id==user.user_id, Message.attachment!="").order_by(Message.id.desc()).all()
    manager_reports = [r for r in reports if "Weekly" in r.subject or "Manager" in r.subject]
    employee_reports = [r for r in reports if "Employee" in r.subject]
    
    common_messages = Message.query.filter_by(msg_type="common").order_by(Message.id.desc()).limit(10).all()
    unread = Message.query.filter(Message.receiver_id==user.user_id, Message.msg_type=="confidential", Message.attachment=="", Message.is_read==False).count()
    active_users = User.query.filter_by(active=True).order_by(User.name).all()

    # Calculate Manager Performance
    manager_users = User.query.filter_by(role="manager", active=True).all()
    manager_perf = []
    for mgr in manager_users:
        verifications = Movement.query.filter_by(verified_by=mgr.user_id).count()
        resolutions = Issue.query.filter_by(resolved_by=mgr.user_id).count()
        score = (verifications * 2) + (resolutions * 5)
        manager_perf.append({
            'name': mgr.name,
            'user_id': mgr.user_id,
            'verifications': verifications,
            'resolutions': resolutions,
            'score': score
        })
    manager_perf.sort(key=lambda x: x['score'], reverse=True)

    return render_template(
        "supervisor.html",
        user=user, total_in=tin, total_out=tout, open_issues=issues_count,
        employees=employees, managers=managers, users=users, active_users=active_users,
        movements=movements, issues_list=open_issues, resolved_issues=resolved_issues,
        messages=messages, manager_reports=manager_reports, employee_reports=employee_reports, common_messages=common_messages, unread=unread,
        manager_perf=manager_perf
    )


@app.route("/manager")
def manager_dashboard():
    user = login_required()
    if not user:
        return redirect(url_for("login"))
    if user.role not in {"manager", "supervisor"}:
        return role_dashboard(user)

    tin, tout, issues, employees, managers = dashboard_stats()
    movements = Movement.query.filter(Movement.status != "Deleted").order_by(Movement.id.desc()).limit(30).all()
    open_issues = Issue.query.filter_by(status="Open").order_by(Issue.id.desc()).all()
    messages = Message.query.filter(
        db.or_(
            db.and_(Message.receiver_id == user.user_id, Message.deleted_by_receiver == False),
            db.and_(Message.sender_id == user.user_id, Message.deleted_by_sender == False)
        ),
        Message.msg_type == "confidential"
    ).order_by(Message.id.desc()).limit(15).all()
    common_messages = Message.query.filter_by(msg_type="common").order_by(Message.id.desc()).limit(10).all()
    unread = Message.query.filter_by(receiver_id=user.user_id, msg_type="confidential", is_read=False).count()
    active_users = User.query.filter_by(active=True).order_by(User.name).all()

    return render_template(
        "manager.html",
        user=user, total_in=tin, total_out=tout, open_issues=issues,
        employees=employees, managers=managers, active_users=active_users,
        movements=movements, issues_list=open_issues,
        messages=messages, common_messages=common_messages, unread=unread
    )


@app.route("/employee")
def employee_dashboard():
    user = login_required()
    if not user:
        return redirect(url_for("login"))
    if user.role != "employee":
        return role_dashboard(user)

    my_movements = Movement.query.filter(
        Movement.created_by == user.user_id,
        Movement.status != "Deleted"
    ).order_by(Movement.id.desc()).limit(20).all()

    my_issues = Issue.query.filter_by(
        created_by=user.user_id, status="Open"
    ).order_by(Issue.id.desc()).limit(10).all()

    messages = Message.query.filter(
        db.or_(
            db.and_(Message.receiver_id == user.user_id, Message.deleted_by_receiver == False),
            db.and_(Message.sender_id == user.user_id, Message.deleted_by_sender == False)
        ),
        Message.msg_type == "confidential"
    ).order_by(Message.id.desc()).limit(15).all()

    common_messages = Message.query.filter_by(msg_type="common").order_by(Message.id.desc()).limit(10).all()

    unread = Message.query.filter_by(
        receiver_id=user.user_id, msg_type="confidential", is_read=False
    ).count()

    active_users = User.query.filter(User.active == True, User.role != "supervisor").order_by(User.name).all()

    return render_template(
        "employee.html",
        user=user, movements=my_movements,
        issues=my_issues, messages=messages, 
        common_messages=common_messages, unread=unread,
        active_users=active_users
    )


@app.route("/api/dashboard")
def dashboard_api():
    user = login_required()
    if not user:
        return jsonify({"logged_in": False}), 401

    tin, tout, issues, employees, managers = dashboard_stats()
    latest = Movement.query.filter(Movement.status != "Deleted").order_by(Movement.id.desc()).first()
    unread = Message.query.filter_by(receiver_id=user.user_id, is_read=False).count()

    return jsonify({
        "logged_in": True,
        "total_in": tin,
        "total_out": tout,
        "open_issues": issues,
        "employees": employees,
        "managers": managers,
        "latest_id": latest.id if latest else 0,
        "latest_item": latest.item if latest else "",
        "latest_quantity": latest.quantity if latest else 0,
        "latest_direction": latest.direction if latest else "",
        "latest_by": latest.created_by if latest else "",
        "unread": unread,
    })


@app.route("/movement", methods=["POST"])
def movement():
    user = login_required()
    if not user:
        return redirect(url_for("login"))

    if user.role not in {"employee", "manager", "supervisor"}:
        return role_dashboard(user)

    item = request.form.get("item", "").strip()
    direction = request.form.get("direction", "IN").upper()
    note = request.form.get("note", "").strip()

    try:
        quantity = int(request.form.get("quantity", "0"))
    except ValueError:
        quantity = 0

    if not item or quantity <= 0 or direction not in {"IN", "OUT"}:
        flash("Enter a valid item, quantity and movement type.", "error")
        return role_dashboard(user)

    db.session.add(Movement(
        item=item, quantity=quantity, direction=direction,
        note=note, created_by=user.user_id
    ))
    db.session.commit()

    flash(f"{quantity} item(s) recorded as {'INCOMING' if direction == 'IN' else 'OUTGOING'}.", "success")
    return role_dashboard(user)


@app.route("/issue", methods=["POST"])
def create_issue():
    user = login_required()
    if not user:
        return redirect(url_for("login"))

    item = request.form.get("item", "").strip()
    issue_type = request.form.get("issue_type", "Other")
    description = request.form.get("description", "").strip()
    photo_file = request.files.get("photo")
    photo_name = ""

    if not item or not description:
        flash("Item and problem description are required.", "error")
        return role_dashboard(user)

    if photo_file and photo_file.filename:
        from werkzeug.utils import secure_filename
        import os
        ext = os.path.splitext(photo_file.filename)[1]
        photo_name = secure_filename(f"{uuid.uuid4().hex}{ext}")
        photo_file.save(ISSUES_FOLDER / photo_name)

    db.session.add(Issue(
        item=item, issue_type=issue_type, description=description,
        photo=photo_name, created_by=user.user_id, status="Open"
    ))
    db.session.commit()
    flash("Alert sent to Management.", "success")
    return role_dashboard(user)


@app.route("/issue/<int:issue_id>/comment", methods=["POST"])
def add_issue_comment(issue_id):
    user = login_required()
    if not user:
        return redirect(url_for("login"))
        
    if user.role == "supervisor":
        flash("Supervisors can only view conversations, not participate.", "error")
        return role_dashboard(user)
        
    body = request.form.get("body", "").strip()
    if body:
        comment = IssueComment(issue_id=issue_id, sender_id=user.user_id, body=body)
        db.session.add(comment)
        db.session.commit()
        flash("Comment added to issue.", "success")
        
    return role_dashboard(user)


@app.route("/issue/<int:issue_id>/resolve", methods=["POST"])
def resolve_issue(issue_id):
    user = login_required()
    if not user:
        return redirect(url_for("login"))
    if user.role != "manager":
        flash("Only Managers have the authority to resolve issues.", "error")
        return role_dashboard(user)

    issue = db.session.get(Issue, issue_id)
    if issue:
        issue.status = "Resolved"
        issue.resolved_by = user.user_id
        
        supervisors = User.query.filter_by(role="supervisor").all()
        for sup in supervisors:
            msg = Message(
                sender_id="SYSTEM",
                receiver_id=sup.user_id,
                subject=f"Issue Resolved: {issue.item}",
                body=f"Manager {user.user_id} has resolved the {issue.issue_type} issue reported by {issue.created_by}. The full conversation is available in your Resolved Issues Archive.",
                msg_type="confidential"
            )
            db.session.add(msg)
            
        db.session.commit()
        flash("Issue resolved.", "success")
    return role_dashboard(user)


@app.route("/message/send", methods=["POST"])
def send_message():
    user = login_required()
    if not user:
        return redirect(url_for("login"))

    msg_type = request.form.get("msg_type", "confidential").lower()
    receiver_id = request.form.get("receiver_id", "").strip().upper()
    subject = request.form.get("subject", "").strip()
    if not subject:
        subject = "Direct Message"
    body = request.form.get("body", "").strip()

    if not body:
        flash("Message body is required.", "error")
        return role_dashboard(user)

    if msg_type == "common":
        if user.role not in {"supervisor", "manager"}:
            flash("Only Managers and Supervisors can broadcast common messages.", "error")
            return role_dashboard(user)
        db.session.add(Message(
            sender_id=user.user_id,
            receiver_id="ALL",
            subject=subject,
            body=body,
            is_read=False,
            msg_type="common"
        ))
        db.session.commit()
        flash("Common message broadcasted successfully.", "success")
        return role_dashboard(user)

    receiver = User.query.filter_by(user_id=receiver_id, active=True).first()
    if not receiver:
        flash("Receiver not found or inactive.", "error")
        return role_dashboard(user)

    if receiver.user_id == user.user_id:
        flash("You cannot send a message to yourself.", "error")
        return role_dashboard(user)

    db.session.add(Message(
        sender_id=user.user_id,
        receiver_id=receiver.user_id,
        subject=subject,
        body=body,
        is_read=False,
        msg_type="confidential"
    ))
    db.session.commit()

    flash(f"Confidential message sent to {receiver.name}.", "success")
    return role_dashboard(user)

@app.route("/movement/<int:movement_id>/verify", methods=["POST"])
def verify_movement(movement_id):
    user = login_required()
    if not user or user.role != "manager":
        flash("Only Managers can verify movements.", "error")
        return redirect(url_for("login"))
    
    movement = db.session.get(Movement, movement_id)
    if movement:
        action = request.form.get("action", "Verified")
        movement.status = action
        movement.verified_by = user.user_id
        db.session.commit()
        flash(f"Movement marked as {action}.", "success")
    return role_dashboard(user)

@app.route("/movement/<int:movement_id>/delete", methods=["POST"])
def delete_movement(movement_id):
    user = login_required()
    if not user or user.role != "manager":
        flash("Unauthorized action. Only Managers can delete movements.", "error")
        return redirect(url_for("login"))
    
    movement = db.session.get(Movement, movement_id)
    if movement:
        movement.status = "Deleted"
        movement.verified_by = user.user_id
        db.session.commit()
        flash("Movement record deleted.", "success")
    return role_dashboard(user)

@app.route("/movement/<int:movement_id>/hard_delete", methods=["POST"])
def hard_delete_movement(movement_id):
    user = login_required()
    if not user or user.role != "supervisor":
        flash("Unauthorized action.", "error")
        return redirect(url_for("login"))
    
    movement = db.session.get(Movement, movement_id)
    if movement:
        db.session.delete(movement)
        db.session.commit()
        flash("Movement permanently deleted.", "success")
    return role_dashboard(user)

@app.route("/issue/<int:issue_id>/delete", methods=["POST"])
def delete_issue(issue_id):
    user = login_required()
    if not user or user.role != "supervisor":
        flash("Unauthorized action.", "error")
        return redirect(url_for("login"))
    
    issue = db.session.get(Issue, issue_id)
    if issue:
        IssueComment.query.filter_by(issue_id=issue.id).delete()
        db.session.delete(issue)
        db.session.commit()
        flash("Issue permanently deleted.", "success")
    return role_dashboard(user)


@app.route("/messages/read/<int:message_id>", methods=["POST"])
def read_message(message_id):
    user = login_required()
    if not user:
        return redirect(url_for("login"))
    msg = db.session.get(Message, message_id)
    if msg and msg.receiver_id == user.user_id:
        msg.is_read = True
        db.session.commit()
    return role_dashboard(user)

@app.route("/conversation/<u1>/<u2>")
def view_conversation(u1, u2):
    user = login_required()
    if not user:
        return redirect(url_for("login"))
    
    # Security check: Only supervisors or the actual participants can view
    if user.role != "supervisor" and user.user_id not in [u1, u2]:
        flash("Unauthorized to view this conversation.", "error")
        return role_dashboard(user)
    
    messages = Message.query.filter(
        db.or_(
            db.and_(Message.sender_id == u1, Message.receiver_id == u2),
            db.and_(Message.sender_id == u2, Message.receiver_id == u1)
        ),
        Message.msg_type == "confidential",
        Message.attachment == ""
    ).order_by(Message.created_at.asc()).all()
    
    if user.role != "supervisor":
        messages = [m for m in messages if not (
            (m.sender_id == user.user_id and m.deleted_by_sender) or 
            (m.receiver_id == user.user_id and m.deleted_by_receiver)
        )]
    
    return render_template("conversation.html", user=user, u1=u1, u2=u2, messages=messages)

@app.route("/conversation/delete/<u1>/<u2>", methods=["POST"])
def delete_conversation(u1, u2):
    user = login_required()
    if not user:
        return redirect(url_for("login"))
        
    if user.role != "supervisor" and user.user_id not in [u1, u2]:
        flash("Unauthorized to delete this conversation.", "error")
        return role_dashboard(user)
        
    messages = Message.query.filter(
        db.or_(
            db.and_(Message.sender_id == u1, Message.receiver_id == u2),
            db.and_(Message.sender_id == u2, Message.receiver_id == u1)
        ),
        Message.msg_type == "confidential"
    ).all()
    
    for msg in messages:
        if user.role == "supervisor":
            db.session.delete(msg)
        else:
            if msg.sender_id == user.user_id:
                msg.deleted_by_sender = True
            if msg.receiver_id == user.user_id:
                msg.deleted_by_receiver = True
        
    db.session.commit()
    flash("Conversation deleted successfully.", "success")
    return role_dashboard(user)

@app.route("/messages/delete/<int:message_id>", methods=["POST"])
def delete_message(message_id):
    user = login_required()
    if not user:
        return redirect(url_for("login"))

    message = db.session.get(Message, message_id)
    if message:
        if user.role == "supervisor":
            db.session.delete(message)
        elif message.sender_id == user.user_id or message.receiver_id == user.user_id:
            if message.sender_id == user.user_id:
                message.deleted_by_sender = True
            if message.receiver_id == user.user_id:
                message.deleted_by_receiver = True
        else:
            flash("Unauthorized to delete this message.", "error")
            return role_dashboard(user)

        db.session.commit()
        flash("Message deleted.", "success")
            
    return role_dashboard(user)


@app.route("/users")
def users():
    user = login_required()
    if not user:
        return redirect(url_for("login"))
    if user.role not in {"supervisor", "manager"}:
        flash("Unauthorized.", "error")
        return role_dashboard(user)

    if user.role == "manager":
        user_list = User.query.filter_by(role="employee", active=True).order_by(User.name).all()
    else:
        user_list = User.query.order_by(User.role, User.name).all()

    return render_template("users.html", user=user, users=user_list)


@app.route("/users/create", methods=["GET", "POST"])
def create_user():
    user = login_required()
    if not user:
        return redirect(url_for("login"))
    if user.role != "supervisor":
        flash("Only Supervisor can create users.", "error")
        return role_dashboard(user)

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        uid = request.form.get("user_id", "").strip().upper()
        password = request.form.get("password", "")
        role = request.form.get("role", "employee")

        if not name or not uid or not password:
            flash("Name, User ID and password are required.", "error")
            return redirect(url_for("create_user"))

        if role not in {"employee", "manager", "supervisor"}:
            flash("Invalid role.", "error")
            return redirect(url_for("create_user"))

        if User.query.filter_by(user_id=uid).first():
            flash("User ID already exists.", "error")
            return redirect(url_for("create_user"))

        new_user = User(
            user_id=uid, name=name,
            password=generate_password_hash(password),
            role=role, qr_token=str(uuid.uuid4()), active=True
        )
        db.session.add(new_user)
        db.session.commit()
        generate_qr(new_user)
        flash(f"{name} created and QR generated.", "success")
        return redirect(url_for("users"))

    return render_template("create_user.html", user=user)


@app.route("/users/<int:user_id>/delete", methods=["POST"])
def delete_user(user_id):
    user = login_required()
    if not user:
        return redirect(url_for("login"))
    if user.role != "supervisor":
        flash("Only Supervisor can delete users.", "error")
        return role_dashboard(user)

    target = db.session.get(User, user_id)
    if not target or target.user_id == "SUP001" or target.id == user.id:
        flash("The main supervisor cannot be deleted.", "error")
        return redirect(url_for("users"))

    qr = qr_file(target)
    db.session.delete(target)
    db.session.commit()
    if qr.exists():
        qr.unlink()

    flash(f"{target.name} deleted.", "success")
    return redirect(url_for("users"))


@app.route("/users/<int:user_id>/toggle", methods=["POST"])
def toggle_user(user_id):
    user = login_required()
    if not user:
        return redirect(url_for("login"))
    if user.role != "supervisor":
        flash("Only Supervisor can change user status.", "error")
        return role_dashboard(user)

    target = db.session.get(User, user_id)
    if not target or target.user_id == "SUP001":
        flash("Main supervisor cannot be disabled.", "error")
        return redirect(url_for("users"))

    target.active = not target.active
    db.session.commit()
    return redirect(url_for("users"))


@app.route("/users/<int:user_id>/qr")
def regenerate_qr(user_id):
    user = login_required()
    if not user:
        return redirect(url_for("login"))
    if user.role != "supervisor":
        flash("Only Supervisor can regenerate QR.", "error")
        return role_dashboard(user)

    target = db.session.get(User, user_id)
    if not target:
        flash("User not found.", "error")
        return redirect(url_for("users"))

    target.qr_token = str(uuid.uuid4())
    db.session.commit()
    generate_qr(target)
    flash("QR regenerated.", "success")
    return redirect(url_for("users"))


@app.route("/qr/<token>")
def qr_profile(token):
    user = User.query.filter_by(qr_token=token).first()
    if not user:
        return "<h1>Invalid QR Code</h1>", 404
    return render_template("qr_profile.html", user=user)


init_db()

try:
    from migrate_db import run_migrations
    run_migrations()
except ImportError:
    print("No migrate_db script found or it could not be imported.")

if __name__ == "__main__":
    print("=" * 60)
    print("WAREHOUSE AI V3")
    print("Supervisor: SUP001 / admin123")
    print("Open: http://127.0.0.1:5000")
    print("=" * 60)
    app.run(host="0.0.0.0", port=5000, debug=True)
