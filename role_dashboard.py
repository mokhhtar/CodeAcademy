# =============================================================================
#  role_dashboard.py  —  Replace _register_dashboard_routes(app) in app.py
#  Project : أكاديمية شيفرة  (Shyfra Academy)
#
#  This file provides:
#    • A role-aware GET / and GET /dashboard route
#    • POST /issue_certificate/<member_id>/<group_id>  (Supervisor only)
#
#  Replace the existing _register_dashboard_routes(app) call in create_app()
#  with _register_role_dashboard_routes(app).
# =============================================================================

import uuid
from datetime import date, timedelta

from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import func

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


def _register_role_dashboard_routes(app) -> None:
    """
    Register the role-aware dashboard and certificate-issue routes.
    Replaces the previous _register_dashboard_routes(app).
    """

    # ─────────────────────────────────────────────────────────────────────────
    #  Shared constant
    # ─────────────────────────────────────────────────────────────────────────
    EXPIRY_ALERT_DAYS = 15

    # =========================================================================
    #  GET /  and  GET /dashboard
    #  Dispatches to a role-specific data-fetching helper and renders
    #  dashboard.html with a `role_type` discriminator so the template
    #  can render the correct section.
    # =========================================================================

    @app.route("/")
    @app.route("/dashboard")
    @login_required
    def dashboard():
        role = current_user.role

        if role == RoleEnum.Admin:
            ctx = _build_admin_context()
        elif role == RoleEnum.Supervisor:
            ctx = _build_supervisor_context()
        else:
            ctx = _build_member_context()

        # role_type is always present — template switches on it
        ctx["role_type"] = role.value
        ctx["today"]     = date.today()

        return render_template("dashboard.html", **ctx)


    # ─────────────────────────────────────────────────────────────────────────
    #  ADMIN context builder
    # ─────────────────────────────────────────────────────────────────────────

    def _build_admin_context() -> dict:
        """
        Full platform statistics for the Admin dashboard.

        Keys returned
        ─────────────
        active_monthly      int
        active_yearly       int
        total_active        int
        total_expired       int
        total_suspended     int
        total_canceled      int
        renewals_this_month int
        revenue_this_month  float
        expiring_soon       list[(Subscription, fname, lname, email, plan_name)]
        alerts_count        int
        """
        today       = date.today()
        month_start = today.replace(day=1)

        active_monthly: int = (
            db.session.query(func.count(Subscription.subscription_id))
            .join(SubscriptionPlan, Subscription.plan_id == SubscriptionPlan.plan_id)
            .filter(
                Subscription.status == SubscriptionStatusEnum.Active,
                SubscriptionPlan.duration_months == 1,
            )
            .scalar() or 0
        )

        active_yearly: int = (
            db.session.query(func.count(Subscription.subscription_id))
            .join(SubscriptionPlan, Subscription.plan_id == SubscriptionPlan.plan_id)
            .filter(
                Subscription.status == SubscriptionStatusEnum.Active,
                SubscriptionPlan.duration_months == 12,
            )
            .scalar() or 0
        )

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
            )
            .scalar() or 0
        )

        revenue_this_month: float = float(
            db.session.query(
                func.coalesce(func.sum(PaymentReceipt.amount_paid), 0)
            )
            .filter(
                PaymentReceipt.payment_date >= month_start,
                PaymentReceipt.payment_date <= today,
            )
            .scalar() or 0.0
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

        return dict(
            active_monthly      = active_monthly,
            active_yearly       = active_yearly,
            total_active        = active_monthly + active_yearly,
            total_expired       = total_expired,
            total_suspended     = total_suspended,
            total_canceled      = total_canceled,
            renewals_this_month = renewals_this_month,
            revenue_this_month  = revenue_this_month,
            expiring_soon       = expiring_soon,
            alerts_count        = len(expiring_soon),
            EXPIRY_ALERT_DAYS   = EXPIRY_ALERT_DAYS,
        )


    # ─────────────────────────────────────────────────────────────────────────
    #  SUPERVISOR context builder
    # ─────────────────────────────────────────────────────────────────────────

    def _build_supervisor_context() -> dict:
        """
        Groups and member roster for the Supervisor dashboard.

        Keys returned
        ─────────────
        supervised_groups       list[Group]
        group_members           dict[group_id → list[(User, Subscription|None)]]
        total_students          int
        total_certificates_issued int
        EXPIRY_ALERT_DAYS       int
        """
        supervisor_id = current_user.user_id

        # Groups where this user is the supervisor
        supervised_groups = (
            Group.query
            .filter_by(supervisor_id=supervisor_id)
            .order_by(Group.created_at.desc())
            .all()
        )

        # For each group, fetch enrolled members and their active subscription
        group_members: dict = {}
        total_students = 0

        for group in supervised_groups:
            rows = (
                db.session.query(User, Subscription)
                .join(GroupMember, User.user_id == GroupMember.member_id)
                .outerjoin(
                    Subscription,
                    db.and_(
                        Subscription.member_id == User.user_id,
                        Subscription.status    == SubscriptionStatusEnum.Active,
                    ),
                )
                .filter(GroupMember.group_id == group.group_id)
                .order_by(User.fname)
                .all()
            )
            group_members[group.group_id] = rows
            total_students += len(rows)

        # Certificates this supervisor has issued
        total_certs_issued: int = (
            Certificate.query
            .filter_by(issued_by=supervisor_id)
            .count()
        )

        # Members who completed the course (have a certificate) — for quick
        # reference so the supervisor knows who still needs one
        issued_cert_pairs: set = set(
            db.session.query(Certificate.member_id, Certificate.group_id)
            .filter_by(issued_by=supervisor_id)
            .all()
        )

        return dict(
            supervised_groups        = supervised_groups,
            group_members            = group_members,
            total_students           = total_students,
            total_certificates_issued= total_certs_issued,
            issued_cert_pairs        = issued_cert_pairs,
            EXPIRY_ALERT_DAYS        = EXPIRY_ALERT_DAYS,
        )


    # ─────────────────────────────────────────────────────────────────────────
    #  MEMBER context builder
    # ─────────────────────────────────────────────────────────────────────────

    def _build_member_context() -> dict:
        """
        Personal subscription data for the Member/Student dashboard.

        Keys returned
        ─────────────
        active_subscription     Subscription | None
        days_remaining          int | None
        alert_level             str | None   ('danger' | 'warning' | 'success')
        enrolled_groups         list[Group]
        latest_receipts         list[PaymentReceipt]  (max 3)
        member_certificates     list[Certificate]
        EXPIRY_ALERT_DAYS       int
        """
        uid = current_user.user_id

        # Active subscription (most recently created if multiple)
        active_sub: Subscription | None = (
            Subscription.query
            .filter_by(member_id=uid, status=SubscriptionStatusEnum.Active)
            .order_by(Subscription.created_at.desc())
            .first()
        )

        days_remaining: int | None = None
        alert_level:    str | None = None

        if active_sub:
            days_remaining = (active_sub.end_date - date.today()).days
            if days_remaining <= 5:
                alert_level = "danger"
            elif days_remaining <= EXPIRY_ALERT_DAYS:
                alert_level = "warning"
            else:
                alert_level = "success"

        # Groups the member is enrolled in
        enrolled_groups: list = (
            Group.query
            .join(GroupMember, Group.group_id == GroupMember.group_id)
            .filter(GroupMember.member_id == uid)
            .all()
        )

        # Latest 3 payment receipts (across all subscriptions)
        latest_receipts: list = (
            db.session.query(PaymentReceipt)
            .join(Subscription,
                  PaymentReceipt.subscription_id == Subscription.subscription_id)
            .filter(Subscription.member_id == uid)
            .order_by(PaymentReceipt.payment_date.desc())
            .limit(3)
            .all()
        )

        member_receipts_count: int = (
            db.session.query(func.count(PaymentReceipt.receipt_id))
            .join(Subscription, PaymentReceipt.subscription_id == Subscription.subscription_id)
            .filter(Subscription.member_id == uid)
            .scalar() or 0
        )

        # Member's certificates
        member_certificates: list = (
            Certificate.query
            .filter_by(member_id=uid)
            .order_by(Certificate.issue_date.desc())
            .all()
        )
        
        member_certs_count = len(member_certificates)

        return dict(
            member_subscription   = active_sub,
            days_remaining        = days_remaining,
            alert_level           = alert_level,
            enrolled_groups       = enrolled_groups,
            latest_receipts       = latest_receipts,
            member_receipts_count = member_receipts_count,
            member_certificates   = member_certificates,
            member_certs_count    = member_certs_count,
            EXPIRY_ALERT_DAYS     = EXPIRY_ALERT_DAYS,
        )


    # =========================================================================
    #  POST /issue_certificate/<member_id>/<group_id>
    #  Supervisor issues a certificate of completion to a specific student
    #  in one of their supervised groups.
    # =========================================================================

    @app.route(
        "/issue_certificate/<int:member_id>/<int:group_id>",
        methods=["POST"],
    )
    @login_required
    def issue_certificate(member_id: int, group_id: int):
        """
        Issue a completion certificate for a member in a group.

        Access rules
        ────────────
        • Only Supervisors and Admins may issue certificates.
        • A Supervisor can only issue for groups they supervise.
        • Duplicate check: one certificate per (member, group) pair.

        Certificate code format
        ───────────────────────
        CERT-<GROUP_ID>-<YEAR>-<8-char UUID hex>
        e.g. CERT-001-2025-A3F7C1B2
        """

        # ── Role guard ────────────────────────────────────────────────────
        if current_user.is_member:
            flash("ليس لديك صلاحية لإصدار الشهادات.", "danger")
            return redirect(url_for("dashboard"))

        # ── Fetch and validate group ──────────────────────────────────────
        group: Group = db.get_or_404(
            Group, group_id,
            description=f"المجموعة رقم {group_id} غير موجودة."
        )

        # Supervisors can only issue for their own groups
        if (
            current_user.is_supervisor
            and group.supervisor_id != current_user.user_id
        ):
            flash("لا يمكنك إصدار شهادة لمجموعة لست مشرفها.", "danger")
            return redirect(url_for("dashboard"))

        # ── Fetch member ──────────────────────────────────────────────────
        member: User = db.get_or_404(
            User, member_id,
            description=f"العضو رقم {member_id} غير موجود."
        )

        # ── Check the member is enrolled in this group ─────────────────────
        enrollment = GroupMember.query.filter_by(
            member_id=member_id, group_id=group_id
        ).first()

        if not enrollment:
            flash(
                f"الطالب '{member.full_name}' ليس مسجلاً في هذه المجموعة.",
                "warning",
            )
            return redirect(url_for("dashboard"))

        # ── Duplicate certificate guard ────────────────────────────────────
        existing_cert = Certificate.query.filter_by(
            member_id=member_id, group_id=group_id
        ).first()

        if existing_cert:
            flash(
                f"الطالب '{member.full_name}' حاصل مسبقاً على شهادة "
                f"لمسار '{group.group_name}'.",
                "info",
            )
            return redirect(url_for("dashboard"))

        # ── Generate unique certificate code ──────────────────────────────
        year = date.today().year
        unique_hex = uuid.uuid4().hex[:8].upper()
        cert_code  = f"CERT-{group_id:03d}-{year}-{unique_hex}"

        # ── Create and persist ────────────────────────────────────────────
        new_cert = Certificate(
            member_id        = member_id,
            group_id         = group_id,
            issued_by        = current_user.user_id,
            issue_date       = date.today(),
            certificate_code = cert_code,
        )

        try:
            db.session.add(new_cert)
            db.session.commit()
            flash(
                f"✅ تم إصدار شهادة بنجاح للطالب '{member.full_name}' "
                f"في مسار '{group.group_name}'. "
                f"رمز الشهادة: {cert_code}",
                "success",
            )
        except Exception as exc:
            db.session.rollback()
            app.logger.error(
                f"issue_certificate error — member={member_id} "
                f"group={group_id}: {exc}"
            )
            flash(
                "حدث خطأ أثناء إصدار الشهادة. يرجى المحاولة مجدداً.",
                "danger",
            )

        return redirect(url_for("dashboard"))