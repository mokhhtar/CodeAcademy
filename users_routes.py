# =============================================================================
#  users_routes.py  —  Route snippet for /users
#  Project : أكاديمية شيفرة  (Shyfra Academy)
# =============================================================================

from flask import render_template, request, flash, redirect, url_for
from flask_login import login_required

from models import User, RoleEnum, UserStatusEnum, db
from groups_routes import admin_required


def _register_user_routes(app) -> None:
    """Register all /users routes onto the Flask app instance."""

    # =========================================================================
    #  GET /users — List all users
    # =========================================================================

    @app.route("/users", methods=["GET"])
    @login_required
    @admin_required
    def users():
        """
        Render the users management page.

        Template variables
        ──────────────────
        users   list[User]  — all users, ordered by role then name
        """
        all_users = (
            User.query
            .order_by(User.role.asc(), User.fname.asc(), User.lname.asc())
            .all()
        )

        return render_template("users.html", users=all_users)


    # =========================================================================
    #  POST /users/add — Create a new user
    # =========================================================================

    @app.route("/users/add", methods=["POST"])
    @login_required
    @admin_required
    def add_user():
        """Handle the Add User form submission."""
        fname    = request.form.get("fname", "").strip()
        lname    = request.form.get("lname", "").strip()
        email    = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        role_val = request.form.get("role", "")

        # ── Validation ───────────────────────────────────────────────────
        if not fname or not lname or not email or not password or not role_val:
            flash("جميع الحقول مطلوبة لإضافة مستخدم جديد.", "danger")
            return redirect(url_for("users"))

        if len(password) < 8:
            flash("يجب أن تتكون كلمة المرور من 8 أحرف على الأقل.", "warning")
            return redirect(url_for("users"))

        try:
            role = RoleEnum(role_val)
        except ValueError:
            flash("الدور المحدد غير صالح.", "danger")
            return redirect(url_for("users"))

        # Check for existing email (case-insensitive)
        existing = User.query.filter(User.email.ilike(email)).first()
        if existing:
            flash(f"البريد الإلكتروني '{email}' مستخدم مسبقاً لحساب آخر.", "warning")
            return redirect(url_for("users"))

        # ── Create and persist ────────────────────────────────────────────
        new_user = User(
            fname  = fname,
            lname  = lname,
            email  = email,
            role   = role,
            status = UserStatusEnum.Active  # new users are active by default
        )
        new_user.set_password(password)

        try:
            db.session.add(new_user)
            db.session.commit()
            
            # Map role to Arabic for flash message
            role_ar = {"Admin": "مدير", "Supervisor": "مدرب", "Member": "طالب"}.get(role.value, "")
            flash(f"تم إنشاء حساب الـ {role_ar} ({fname} {lname}) بنجاح. ✅", "success")
        except Exception as exc:
            db.session.rollback()
            app.logger.error(f"add_user error: {exc}")
            flash("حدث خطأ أثناء إنشاء الحساب. يرجى المحاولة مجدداً.", "danger")

        return redirect(url_for("users"))
