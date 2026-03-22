# =============================================================================
#  enrollment_routes.py  —  Student self-enrollment in course groups
#  Project : أكاديمية شيفرة  (Shyfra Academy)
#
#  Add _register_enrollment_routes(app) inside create_app():
#
#      _register_payment_routes(app)
#      _register_enrollment_routes(app)    ← add this line
#      _register_subscription_routes(app)
#      ...
#
#  Routes
#  ──────
#  GET  /courses                  → courses()    browse & join groups
#  POST /courses/join/<group_id>  → join_group() enroll in a group
# =============================================================================

from datetime import date
from functools import wraps

from flask import flash, redirect, render_template, url_for
from flask_login import current_user, login_required
from sqlalchemy.orm import aliased

from models import (
    Group,
    GroupMember,
    RoleEnum,
    User,
    db,
)


# ─────────────────────────────────────────────────────────────────────────────
#  Member-only guard
# ─────────────────────────────────────────────────────────────────────────────

def _member_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_member:
            flash("هذه الصفحة مخصصة للطلاب فقط.", "warning")
            return redirect(url_for("dashboard"))
        return f(*args, **kwargs)
    return decorated


# ─────────────────────────────────────────────────────────────────────────────
#  Registration function
# ─────────────────────────────────────────────────────────────────────────────

def _register_enrollment_routes(app) -> None:

    # =========================================================================
    #  GET /courses
    #  Browse all available groups and show which ones the member has joined.
    #
    #  Template variables
    #  ──────────────────
    #  all_groups          list of (Group, supervisor_name: str | None)
    #                      — every group, joined with supervisor User for name
    #  enrolled_group_ids  set[int]
    #                      — group_ids the current member is already in;
    #                        the template uses this to toggle "Join" vs "Joined"
    # =========================================================================

    @app.route("/courses", methods=["GET"])
    @login_required
    @_member_required
    def courses():
        """
        Render the course/group exploration page.

        We use an aliased User for the supervisor JOIN so SQLAlchemy doesn't
        confuse it with a potential future self-referential join on the same
        table.  The supervisor name is passed as a plain string (or None) so
        the template doesn't need a lazy-load call.
        """

        SupervisorAlias = aliased(User, name="supervisor")

        # Fetch all groups + supervisor display name in one query
        rows = (
            db.session.query(Group, SupervisorAlias)
            .outerjoin(
                SupervisorAlias,
                Group.supervisor_id == SupervisorAlias.user_id,
            )
            .order_by(Group.created_at.desc())
            .all()
        )

        # Build a list of (Group, supervisor_name_or_None) tuples
        all_groups = [
            (group, f"{sup.fname} {sup.lname}" if sup else None)
            for group, sup in rows
        ]

        # IDs the current member is already enrolled in
        enrolled_group_ids: set[int] = {
            gm.group_id
            for gm in GroupMember.query
            .filter_by(member_id=current_user.user_id)
            .all()
        }

        return render_template(
            "courses.html",
            all_groups          = all_groups,
            enrolled_group_ids  = enrolled_group_ids,
        )


    # =========================================================================
    #  POST /courses/join/<group_id>
    #  Enroll the current member in a group.
    #
    #  Guard checks
    #  ────────────
    #  1. Group must exist (404 otherwise).
    #  2. Duplicate enrollment check — flash info if already enrolled.
    #  3. Create GroupMember record with joined_date = today.
    # =========================================================================

    @app.route("/courses/join/<int:group_id>", methods=["POST"])
    @login_required
    @_member_required
    def join_group(group_id: int):
        """
        Enroll the current member in the specified group.

        We use POST (not GET) so search crawlers and browser pre-fetchers
        cannot accidentally trigger an enrollment via a link preview.
        """

        # ── 1. Group must exist ───────────────────────────────────────────
        group: Group | None = db.session.get(Group, group_id)
        if group is None:
            flash("المسار غير موجود.", "danger")
            return redirect(url_for("courses"))

        # ── 2. Duplicate enrollment check ─────────────────────────────────
        existing = GroupMember.query.filter_by(
            group_id  = group_id,
            member_id = current_user.user_id,
        ).first()

        if existing is not None:
            flash(
                f"أنت منضم إلى مسار '{group.group_name}' بالفعل.",
                "info",
            )
            return redirect(url_for("courses"))

        # ── 3. Create enrollment record ────────────────────────────────────
        new_enrollment = GroupMember(
            group_id    = group_id,
            member_id   = current_user.user_id,
            joined_date = date.today(),
        )

        try:
            db.session.add(new_enrollment)
            db.session.commit()
            flash(
                f"🎉 تم الانضمام إلى مسار '{group.group_name}' بنجاح! "
                f"يمكنك الآن متابعة المحتوى والتواصل مع المدرب.",
                "success",
            )
        except Exception as exc:
            db.session.rollback()
            app.logger.error(
                f"join_group error — user={current_user.user_id} "
                f"group={group_id}: {exc}"
            )
            flash(
                "حدث خطأ أثناء الانضمام. يرجى المحاولة مجدداً.",
                "danger",
            )

        return redirect(url_for("courses"))