# =============================================================================
#  groups_routes.py  —  Route snippet to integrate into app.py
#  Project : أكاديمية شيفرة  (Shyfra Academy)
#
#  Add _register_group_routes(app) inside create_app():
#
#      _register_auth_routes(app)
#      _register_dashboard_routes(app)
#      _register_subscription_routes(app)
#      _register_receipt_routes(app)
#      _register_certificate_routes(app)
#      _register_list_routes(app)
#      _register_group_routes(app)           ← add this line
#      _register_core_routes(app)
#
#  All routes are restricted to Admin role only.
#  Supervisors and Members will be redirected with a danger flash.
# =============================================================================

from functools import wraps

from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from models import Group, RoleEnum, User, db


# ─────────────────────────────────────────────────────────────────────────────
#  Reusable Admin-only decorator
#  Stacks on top of @login_required — apply in this order:
#      @login_required
#      @admin_required
# ─────────────────────────────────────────────────────────────────────────────

def admin_required(f):
    """Decorator that restricts a route to users with the Admin role."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_admin:
            flash("هذه الصفحة مخصصة للمسؤول فقط.", "danger")
            return redirect(url_for("dashboard"))
        return f(*args, **kwargs)
    return decorated


def _get_supervisors():
    """Return all active Supervisor users — used to populate the dropdown."""
    return (
        User.query
        .filter_by(role=RoleEnum.Supervisor)
        .order_by(User.fname)
        .all()
    )


def _register_group_routes(app) -> None:
    """Register all /groups CRUD routes onto the Flask app instance."""

    # =========================================================================
    #  1.  GET /groups
    #      List all groups with their supervisor and member count.
    # =========================================================================

    @app.route("/groups", methods=["GET"])
    @login_required
    def groups():
        """
        Render the groups management page.

        Template variables
        ──────────────────
        groups        list of Group ORM objects  (supervisor eager-loaded)
        supervisors   list of User  objects with Supervisor role
                      (pre-fetched so the Add modal's <select> is populated
                       without a second request)
        """
        if current_user.is_member:
            flash("هذه الصفحة مخصصة للإدارة فقط.", "warning")
            return redirect(url_for("courses"))
        if current_user.role == RoleEnum.Supervisor:
            all_groups = (
                Group.query
                .filter_by(supervisor_id=current_user.user_id)
                .order_by(Group.created_at.desc())
                .all()
            )
        else:
            all_groups = (
                Group.query
                .order_by(Group.created_at.desc())
                .all()
            )
            
        supervisors = _get_supervisors() if current_user.is_admin else []

        return render_template(
            "groups.html",
            groups      = all_groups,
            supervisors = supervisors,
        )


    # =========================================================================
    #  2.  POST /groups/add
    #      Create a new group from the modal form submission.
    # =========================================================================

    @app.route("/groups/add", methods=["POST"])
    @login_required
    def add_group():
        """
        Handle the "Add Group" modal form.

        Form fields
        ───────────
        group_name    : str  (required)
        description   : str  (optional)
        supervisor_id : int  (optional — may be blank / unassigned)
        """
        group_name    = request.form.get("group_name",    "").strip()
        description   = request.form.get("description",   "").strip()
        supervisor_id = request.form.get("supervisor_id", "").strip()

        # ── Validation ────────────────────────────────────────────────────
        if current_user.is_member:
            flash("غير مصرح لك بإنشاء مجموعة.", "danger")
            return redirect(url_for("groups"))

        if not group_name:
            flash("اسم المجموعة مطلوب.", "danger")
            return redirect(url_for("groups"))

        # ── Duplicate name check ──────────────────────────────────────────
        existing = Group.query.filter(
            Group.group_name.ilike(group_name)
        ).first()
        if existing:
            flash(f"توجد مجموعة باسم '{group_name}' مسبقاً.", "warning")
            return redirect(url_for("groups"))

        # ── Resolve optional supervisor FK ────────────────────────────────
        if current_user.role == RoleEnum.Supervisor:
            resolved_supervisor_id = current_user.user_id
        else:
            resolved_supervisor_id = int(supervisor_id) if supervisor_id else None

        new_group = Group(
            group_name    = group_name,
            description   = description or None,
            supervisor_id = resolved_supervisor_id,
        )

        try:
            db.session.add(new_group)
            db.session.commit()
            flash(f"تم إنشاء المجموعة '{group_name}' بنجاح. ✅", "success")
        except Exception as exc:
            db.session.rollback()
            app.logger.error(f"add_group error: {exc}")
            flash("حدث خطأ أثناء إنشاء المجموعة. يرجى المحاولة مجدداً.", "danger")

        return redirect(url_for("groups"))


    # =========================================================================
    #  3.  GET + POST /groups/edit/<group_id>
    #      Edit an existing group's name, description, or supervisor.
    # =========================================================================

    @app.route("/groups/edit/<int:group_id>", methods=["GET", "POST"])
    @login_required
    @admin_required
    def edit_group(group_id: int):
        """
        GET  → render the edit modal pre-filled with existing data.
        POST → apply changes and redirect back to /groups.

        Template variables (GET)
        ────────────────────────
        group         Group ORM object to edit
        supervisors   list of Supervisor User objects (for <select>)
        """
        group = db.get_or_404(
            Group, group_id,
            description=f"المجموعة رقم {group_id} غير موجودة."
        )

        if request.method == "POST":
            group_name    = request.form.get("group_name",    "").strip()
            description   = request.form.get("description",   "").strip()
            supervisor_id = request.form.get("supervisor_id", "").strip()

            # ── Validation ────────────────────────────────────────────────
            if not group_name:
                flash("اسم المجموعة مطلوب.", "danger")
                return redirect(url_for("edit_group", group_id=group_id))

            # ── Duplicate name check (exclude current group) ───────────────
            duplicate = Group.query.filter(
                Group.group_name.ilike(group_name),
                Group.group_id != group_id,
            ).first()
            if duplicate:
                flash(f"توجد مجموعة أخرى باسم '{group_name}' مسبقاً.", "warning")
                return redirect(url_for("edit_group", group_id=group_id))

            # ── Apply changes ─────────────────────────────────────────────
            group.group_name    = group_name
            group.description   = description or None
            group.supervisor_id = int(supervisor_id) if supervisor_id else None

            try:
                db.session.commit()
                flash(f"تم تحديث المجموعة '{group_name}' بنجاح. ✅", "success")
                return redirect(url_for("groups"))
            except Exception as exc:
                db.session.rollback()
                app.logger.error(f"edit_group error: {exc}")
                flash("حدث خطأ أثناء تحديث المجموعة.", "danger")
                return redirect(url_for("edit_group", group_id=group_id))

        # ── GET: render standalone edit page (or re-use groups.html modal) ─
        supervisors = _get_supervisors()
        return render_template(
            "groups.html",
            groups      = Group.query.order_by(Group.created_at.desc()).all(),
            supervisors = supervisors,
            edit_group  = group,      # signals the template to open edit modal
        )


    # =========================================================================
    #  4.  POST /groups/delete/<group_id>
    #      Delete a group (CASCADE removes Group_Members + Certificates).
    #      Uses POST (not GET) to prevent CSRF via link-following.
    # =========================================================================

    @app.route("/groups/delete/<int:group_id>", methods=["POST"])
    @login_required
    @admin_required
    def delete_group(group_id: int):
        """
        Delete a group by ID.

        Cascade effects (defined in the schema)
        ────────────────────────────────────────
        • Group_Members rows  → deleted via ON DELETE CASCADE
        • Certificates rows   → deleted via ON DELETE CASCADE
        • Subscriptions       → NOT affected (member is still a member)
        • supervisor FK       → SET NULL on the referenced User  (no user deleted)
        """
        group = db.get_or_404(
            Group, group_id,
            description=f"المجموعة رقم {group_id} غير موجودة."
        )
        group_name = group.group_name

        try:
            db.session.delete(group)
            db.session.commit()
            flash(
                f"تم حذف المجموعة '{group_name}' وجميع بيانات أعضائها "
                f"وشهاداتها المرتبطة بها. 🗑️",
                "success",
            )
        except Exception as exc:
            db.session.rollback()
            app.logger.error(f"delete_group error: {exc}")
            flash("حدث خطأ أثناء حذف المجموعة. يرجى المحاولة مجدداً.", "danger")

        return redirect(url_for("groups"))