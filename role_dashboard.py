# =============================================================================
#  role_dashboard.py  —  Role-aware dashboard + Supervisor stats + Admin view
#  Project : أكاديمية شيفرة  (Shyfra Academy)
#
#  CHANGES IN THIS VERSION
#  ───────────────────────
#  • _supervisor_dashboard() now passes total_groups, total_students,
#    total_certificates to the template (via shared helper)
#  • New route: GET /admin/supervisor/<sup_id>  (Admin only)
#      Deep-dive performance page for a single supervisor
#
#  Routes
#  ──────
#  GET  /                               → dashboard()
#  GET  /dashboard                      → dashboard()
#  POST /issue_certificate/<m>/<g>      → issue_certificate()
#  GET  /admin/supervisor/<sup_id>      → admin_supervisor_stats()  ← NEW
# =============================================================================

import uuid
from datetime import date, timedelta
from functools import wraps

from flask import abort, flash, redirect, render_template, url_for
from flask_login import current_user, login_required
from sqlalchemy import and_, func

from models import (
    Certificate,
    Group,
    GroupMember,
    PaymentReceipt,
    PaymentTypeEnum,
    RoleEnum,
    Subscription,
    SubscriptionPlan,
    SubscriptionStatusEnum,
    User,
    db,
)


# ─────────────────────────────────────────────────────────────────────────────
#  Role guards
# ─────────────────────────────────────────────────────────────────────────────

def _supervisor_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or (
            not current_user.is_supervisor and not current_user.is_admin
        ):
            flash("هذه العملية مخصصة للمدربين فقط.", "danger")
            return redirect(url_for("dashboard"))
        return f(*args, **kwargs)
    return decorated


def _admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            flash("هذه الصفحة مخصصة للمسؤول فقط.", "danger")
            return redirect(url_for("dashboard"))
        return f(*args, **kwargs)
    return decorated


# ─────────────────────────────────────────────────────────────────────────────
#  Shared supervisor stats helper
#  Called by both _supervisor_dashboard() and admin_supervisor_stats() so
#  the calculation logic lives in exactly ONE place.
# ─────────────────────────────────────────────────────────────────────────────

def _compute_supervisor_stats(supervisor_id: int) -> dict:
    """
    Compute all performance statistics for a supervisor by user_id.

    Returns a dict with keys
    ────────────────────────
    total_groups        int   — groups where supervisor_id == arg
    total_students      int   — UNIQUE members enrolled across those groups
    total_certificates  int   — certificates issued_by == arg
    my_groups           list[Group]
    my_students         list[dict]
        keys: member, group, gm, sub (active Subscription|None), has_cert (bool)
    """

    # ── 1. Groups ─────────────────────────────────────────────────────────
    my_groups: list[Group] = (
        Group.query
        .filter_by(supervisor_id=supervisor_id)
        .order_by(Group.created_at.desc())
        .all()
    )
    total_groups: int = len(my_groups)

    # Early return: no groups → all other stats are zero
    if not my_groups:
        return {
            "total_groups"       : 0,
            "total_students"     : 0,
            "total_certificates" : 0,
            "my_groups"          : [],
            "my_students"        : [],
        }

    my_group_ids: list[int] = [g.group_id for g in my_groups]

    # ── 2. Unique students across all supervised groups ────────────────────
    #  COUNT(DISTINCT member_id) avoids double-counting a student who is
    #  enrolled in more than one of this supervisor's groups.
    total_students: int = (
        db.session.query(func.count(func.distinct(GroupMember.member_id)))
        .filter(GroupMember.group_id.in_(my_group_ids))
        .scalar() or 0
    )

    # ── 3. Certificates issued BY this supervisor (not just in their groups) ──
    #  This counts every cert the supervisor has ever signed, including for
    #  groups that may have been reassigned later.
    total_certificates: int = (
        Certificate.query
        .filter_by(issued_by=supervisor_id)
        .count()
    )

    # ── 4. Enriched student list (one row per member × group pair) ─────────
    rows = (
        db.session.query(
            User,
            Group,
            GroupMember,
            Subscription,   # may be None → outerjoin
        )
        .join(GroupMember, User.user_id   == GroupMember.member_id)
        .join(Group,       Group.group_id == GroupMember.group_id)
        .outerjoin(
            Subscription,
            and_(
                Subscription.member_id == User.user_id,
                Subscription.status    == SubscriptionStatusEnum.Active,
            ),
        )
        .filter(GroupMember.group_id.in_(my_group_ids))
        .order_by(Group.group_id.asc(), User.fname.asc())
        .all()
    )

    # Pre-build a set of (member_id, group_id) tuples for O(1) cert lookup
    issued_cert_pairs: set[tuple[int, int]] = {
        (c.member_id, c.group_id)
        for c in Certificate.query
        .filter(Certificate.group_id.in_(my_group_ids))
        .all()
    }

    # Deduplicate: a student can appear multiple times if they have more than
    # one active subscription (edge case); we keep only the first hit per pair.
    my_students: list[dict] = []
    seen: set[tuple[int, int]] = set()

    for member, group, gm, sub in rows:
        key = (member.user_id, group.group_id)
        if key in seen:
            continue
        seen.add(key)
        my_students.append({
            "member"   : member,
            "group"    : group,
            "gm"       : gm,
            "sub"      : sub,                      # None if no active sub
            "has_cert" : key in issued_cert_pairs,  # disables issue button
        })

    return {
        "total_groups"       : total_groups,
        "total_students"     : total_students,
        "total_certificates" : total_certificates,
        "my_groups"          : my_groups,
        "my_students"        : my_students,
    }


# ─────────────────────────────────────────────────────────────────────────────
#  Registration function — called from create_app()
# ─────────────────────────────────────────────────────────────────────────────

def _register_role_dashboard_routes(app) -> None:

    # =========================================================================
    #  GET /  and  GET /dashboard
    # =========================================================================

    @app.route("/")
    @app.route("/dashboard")
    @login_required
    def dashboard():
        if current_user.role == RoleEnum.Admin:
            return _admin_dashboard()
        elif current_user.role == RoleEnum.Supervisor:
            return _supervisor_dashboard()
        else:
            return _member_dashboard()

    # =========================================================================
    #  POST /issue_certificate/<member_id>/<group_id>
    # =========================================================================

    @app.route(
        "/issue_certificate/<int:member_id>/<int:group_id>",
        methods=["POST"],
    )
    @login_required
    @_supervisor_required
    def issue_certificate(member_id: int, group_id: int):

        member: User | None = db.session.get(User, member_id)
        if member is None or not member.is_member:
            flash("الطالب غير موجود أو غير صالح.", "danger")
            return redirect(url_for("dashboard"))

        group: Group | None = db.session.get(Group, group_id)
        if group is None:
            flash("المجموعة غير موجودة.", "danger")
            return redirect(url_for("dashboard"))

        if current_user.is_supervisor and group.supervisor_id != current_user.user_id:
            flash("لا يمكنك إصدار شهادات لمجموعة لا تشرف عليها.", "danger")
            return redirect(url_for("dashboard"))

        enrolled = GroupMember.query.filter_by(
            group_id=group_id, member_id=member_id
        ).first()
        if enrolled is None:
            flash(
                f"الطالب {member.full_name} غير مسجَّل في "
                f"مجموعة '{group.group_name}'.", "warning",
            )
            return redirect(url_for("dashboard"))

        existing = Certificate.query.filter_by(
            member_id=member_id, group_id=group_id
        ).first()
        if existing is not None:
            flash(
                f"الطالب {member.full_name} يمتلك شهادةً بالفعل "
                f"لمجموعة '{group.group_name}' "
                f"(رمز: {existing.certificate_code}).", "warning",
            )
            return redirect(url_for("dashboard"))

        today        = date.today()
        random_token = uuid.uuid4().hex[:6].upper()
        cert_code    = (
            f"CERT-{today.year}"
            f"-{group_id:03d}"
            f"-{member_id:04d}"
            f"-{random_token}"
        )

        new_cert = Certificate(
            member_id        = member_id,
            group_id         = group_id,
            issued_by        = current_user.user_id,
            issue_date       = today,
            certificate_code = cert_code,
        )

        try:
            db.session.add(new_cert)
            db.session.commit()
            flash(
                f"✅ تم إصدار شهادة للطالب {member.full_name} "
                f"في مجموعة '{group.group_name}'. "
                f"رمز الشهادة: {cert_code}", "success",
            )
        except Exception as exc:
            db.session.rollback()
            app.logger.error(
                f"issue_certificate error — member={member_id}, group={group_id}: {exc}"
            )
            flash("حدث خطأ أثناء إصدار الشهادة. يرجى المحاولة مجدداً.", "danger")

        return redirect(url_for("dashboard"))

    # =========================================================================
    #  GET /admin/supervisor/<sup_id>   ← NEW
    #
    #  Admin-only deep-dive into a single supervisor's performance.
    #  Uses the same _compute_supervisor_stats() helper as the dashboard so
    #  numbers are always consistent.
    #
    #  Guard checks (in order)
    #  ───────────────────────
    #  1. Caller must be Admin  (@_admin_required)
    #  2. Target user must exist
    #  3. Target user must have role == Supervisor
    #     (prevents viewing member/admin stats via URL manipulation)
    #
    #  Template variables
    #  ──────────────────
    #  supervisor          User
    #  total_groups        int
    #  total_students      int
    #  total_certificates  int
    #  my_groups           list[Group]
    #  my_students         list[dict]   (same structure as dashboard)
    # =========================================================================

    @app.route("/admin/supervisor/<int:sup_id>", methods=["GET"])
    @login_required
    @_admin_required
    def admin_supervisor_stats(sup_id: int):
        """
        Admin-only: render a detailed performance report for one supervisor.
        """

        # ── Fetch the supervisor user ──────────────────────────────────────
        supervisor: User | None = db.session.get(User, sup_id)

        if supervisor is None:
            flash(f"المستخدم رقم {sup_id} غير موجود.", "danger")
            return redirect(url_for("users"))

        if supervisor.role != RoleEnum.Supervisor:
            flash(
                f"المستخدم '{supervisor.full_name}' ليس مدرباً — "
                f"دوره: {supervisor.role.value}.", "warning",
            )
            return redirect(url_for("users"))

        # ── Compute stats ──────────────────────────────────────────────────
        stats = _compute_supervisor_stats(supervisor_id=sup_id)

        return render_template(
        "supervisor_stats.html",
        supervisor         = supervisor,
        total_groups       = stats["total_groups"],
        total_students     = stats["total_students"],
        total_certificates = stats["total_certificates"],
        sup_groups         = stats["my_groups"],     # <--- قم بتغيير my_groups إلى sup_groups
        sup_students       = stats["my_students"],   # <--- قم بتغيير my_students إلى sup_students
    )


# ─────────────────────────────────────────────────────────────────────────────
#  Private dashboard builders
# ─────────────────────────────────────────────────────────────────────────────

def _admin_dashboard():
    today             = date.today()
    month_start       = today.replace(day=1)
    EXPIRY_ALERT_DAYS = 15

    active_monthly: int = (
        db.session.query(func.count(Subscription.subscription_id))
        .join(SubscriptionPlan, Subscription.plan_id == SubscriptionPlan.plan_id)
        .filter(
            Subscription.status == SubscriptionStatusEnum.Active,
            SubscriptionPlan.duration_months == 1,
        ).scalar() or 0
    )

    active_yearly: int = (
        db.session.query(func.count(Subscription.subscription_id))
        .join(SubscriptionPlan, Subscription.plan_id == SubscriptionPlan.plan_id)
        .filter(
            Subscription.status == SubscriptionStatusEnum.Active,
            SubscriptionPlan.duration_months == 12,
        ).scalar() or 0
    )

    total_active    = active_monthly + active_yearly

    total_expired: int = (
        db.session.query(func.count(Subscription.subscription_id))
        .filter(Subscription.status == SubscriptionStatusEnum.Expired)
        .scalar() or 0
    )

    total_suspended: int = (
        db.session.query(func.count(Subscription.subscription_id))
        .filter(Subscription.status == SubscriptionStatusEnum.Suspended)
        .scalar() or 0
    )

    total_canceled: int = (
        db.session.query(func.count(Subscription.subscription_id))
        .filter(Subscription.status == SubscriptionStatusEnum.Canceled)
        .scalar() or 0
    )

    renewals_this_month: int = (
        db.session.query(func.count(PaymentReceipt.receipt_id))
        .filter(
            PaymentReceipt.payment_type == PaymentTypeEnum.Renewal,
            PaymentReceipt.payment_date >= month_start,
            PaymentReceipt.payment_date <= today,
        ).scalar() or 0
    )

    revenue_this_month: float = float(
        db.session.query(func.coalesce(func.sum(PaymentReceipt.amount_paid), 0))
        .filter(
            PaymentReceipt.payment_date >= month_start,
            PaymentReceipt.payment_date <= today,
        ).scalar() or 0.0
    )

    alert_threshold = today + timedelta(days=EXPIRY_ALERT_DAYS)
    expiring_soon = (
        db.session.query(
            Subscription,
            User.fname, User.lname, User.email,
            SubscriptionPlan.plan_name,
        )
        .join(User,             Subscription.member_id == User.user_id)
        .join(SubscriptionPlan, Subscription.plan_id   == SubscriptionPlan.plan_id)
        .filter(
            Subscription.status   == SubscriptionStatusEnum.Active,
            Subscription.end_date >= today,
            Subscription.end_date <= alert_threshold,
        )
        .order_by(Subscription.end_date.asc())
        .all()
    )

    return render_template(
        "dashboard.html",
        active_monthly      = active_monthly,
        active_yearly       = active_yearly,
        total_active        = total_active,
        total_expired       = total_expired,
        total_suspended     = total_suspended,
        total_canceled      = total_canceled,
        renewals_this_month = renewals_this_month,
        revenue_this_month  = revenue_this_month,
        expiring_soon       = expiring_soon,
        alerts_count        = len(expiring_soon),
        today               = today,
        EXPIRY_ALERT_DAYS   = EXPIRY_ALERT_DAYS,
    )


def _supervisor_dashboard():
    """
    Supervisor's own dashboard.

    Delegates entirely to _compute_supervisor_stats() so the numbers shown
    here are always identical to what the Admin sees on /admin/supervisor/<id>.
    """

    stats = _compute_supervisor_stats(supervisor_id=current_user.user_id)

    return render_template(
        "dashboard.html",
        # ── NEW: performance counters for the stat-card row ──────────────
        total_groups        = stats["total_groups"],
        total_students      = stats["total_students"],
        total_certificates  = stats["total_certificates"],
        # ── Existing: lists for the table / group cards ──────────────────
        my_groups           = stats["my_groups"],
        my_students         = stats["my_students"],
    )


def _member_dashboard():
    member_id: int = current_user.user_id
    today: date    = date.today()

    member_subscription: Subscription | None = (
        Subscription.query
        .filter_by(member_id=member_id, status=SubscriptionStatusEnum.Active)
        .order_by(Subscription.start_date.desc())
        .first()
    )
    if member_subscription is None:
        member_subscription = (
            Subscription.query
            .filter_by(member_id=member_id)
            .order_by(Subscription.start_date.desc())
            .first()
        )

    member_groups: list[Group] = (
        Group.query
        .join(GroupMember, Group.group_id == GroupMember.group_id)
        .filter(GroupMember.member_id == member_id)
        .order_by(Group.created_at.desc())
        .all()
    )

    member_receipts_count: int = (
        db.session.query(func.count(PaymentReceipt.receipt_id))
        .join(Subscription,
              PaymentReceipt.subscription_id == Subscription.subscription_id)
        .filter(Subscription.member_id == member_id)
        .scalar() or 0
    )

    member_certs_count: int = (
        Certificate.query.filter_by(member_id=member_id).count()
    )

    return render_template(
        "dashboard.html",
        member_subscription   = member_subscription,
        member_groups         = member_groups,
        member_receipts_count = member_receipts_count,
        member_certs_count    = member_certs_count,
        today                 = today,
    )