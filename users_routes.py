# =============================================================================
#  users_routes.py  —  Route snippet for /users
#  Project : أكاديمية شيفرة  (Shyfra Academy)
# =============================================================================

from flask import render_template, request, flash, redirect, url_for
from flask_login import login_required, current_user

from models import User, RoleEnum, UserStatusEnum, db
from groups_routes import admin_required


def _register_user_routes(app) -> None:
    """Register all /users routes onto the Flask app instance."""

    # =========================================================================
    #  GET /users — List all users
    # =========================================================================

    @app.route("/users", methods=["GET"])
    @login_required
    def users():
        """
        Render the users management page.

        Template variables
        ──────────────────
        users   list[User]  — all users, ordered by role then name
        """
        from models import GroupMember, Group
        
        if current_user.is_member:
            flash("غير مصرح لك بعرض هذه الصفحة.", "danger")
            return redirect(url_for("dashboard"))
            
        if current_user.role == RoleEnum.Supervisor:
            # Only show members belonging to groups the supervisor manages
            all_users = (
                User.query
                .join(GroupMember, User.user_id == GroupMember.member_id)
                .join(Group, Group.group_id == GroupMember.group_id)
                .filter(Group.supervisor_id == current_user.user_id)
                .filter(User.role == RoleEnum.Member)
                .order_by(User.fname.asc(), User.lname.asc())
                .distinct()
                .all()
            )
        else:
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


    # =========================================================================
    #  POST /users/edit/<int:user_id> — Edit an existing user
    # =========================================================================

    @app.route("/users/edit/<int:user_id>", methods=["POST"])
    @login_required
    @admin_required
    def edit_user(user_id):
        """Handle the Edit User form submission."""
        user = User.query.get_or_404(user_id)

        fname    = request.form.get("fname", "").strip()
        lname    = request.form.get("lname", "").strip()
        email    = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        role_val = request.form.get("role", "")
        status_val = request.form.get("status", "")

        # ── Validation ───────────────────────────────────────────────────
        if not fname or not lname or not email or not role_val or not status_val:
            flash("يرجى تعبئة جميع الحقول المطلوبة لتعديل المستخدم.", "danger")
            return redirect(url_for("users"))

        try:
            role = RoleEnum(role_val)
        except ValueError:
            flash("الدور المحدد غير صالح.", "danger")
            return redirect(url_for("users"))

        try:
            status = UserStatusEnum(status_val)
        except ValueError:
            flash("الحالة المحددة غير صالحة.", "danger")
            return redirect(url_for("users"))

        # Check for email conflict
        if email != user.email:
            existing = User.query.filter(User.email.ilike(email)).first()
            if existing:
                flash(f"البريد الإلكتروني '{email}' مستخدم مسبقاً لحساب آخر.", "warning")
                return redirect(url_for("users"))

        # ── Update fields ──────────────────────────────────────────────────
        user.fname = fname
        user.lname = lname
        user.email = email
        user.role = role
        user.status = status

        if password:
            if len(password) < 8:
                flash("يجب أن تتكون كلمة المرور من 8 أحرف على الأقل.", "warning")
                return redirect(url_for("users"))
            user.set_password(password)

        try:
            db.session.commit()
            flash(f"تم تحديث بيانات المستخدم ({fname} {lname}) بنجاح. ✅", "success")
        except Exception as exc:
            db.session.rollback()
            app.logger.error(f"edit_user error: {exc}")
            flash("حدث خطأ أثناء تحديث بيانات الحساب. يرجى المحاولة مجدداً.", "danger")

        return redirect(url_for("users"))


    # =========================================================================
    #  POST /users/delete/<int:user_id> — Delete a user
    # =========================================================================

    @app.route("/users/delete/<int:user_id>", methods=["POST"])
    @login_required
    @admin_required
    def delete_user(user_id):
        """Delete an existing user."""
        from flask_login import current_user
        
        user = User.query.get_or_404(user_id)

        # Prevent self-deletion
        if user.user_id == current_user.user_id:
            flash("لا يمكنك حذف حسابك الشخصي.", "danger")
            return redirect(url_for("users"))

        try:
            # Note: depending on relationships in models.py (e.g. cascade deletes)
            # deleting a user might effect associated groups or subscriptions. 
            # Assuming SQLAlchemy handles the cascade if configured, or user wants force delete
            name = user.full_name
            db.session.delete(user)
            db.session.commit()
            flash(f"تم حذف المستخدم ({name}) نهائياً.", "success")
        except Exception as exc:
            db.session.rollback()
            app.logger.error(f"delete_user error: {exc}")
            flash("تعذر حذف المستخدم. قد يكون مرتبطاً ببيانات أخرى في النظام (مثل الاشتراكات أو المجموعات).", "danger")

        return redirect(url_for("users"))
