# =============================================================================
#  role_dashboard.py  —  Dynamic Dashboard Routing
#  Project : أكاديمية شيفرة  (Shyfra Academy)
# =============================================================================

from flask import render_template, flash, redirect, url_for  # تمت إضافة النواقص هنا
from flask_login import login_required, current_user
from datetime import date, timedelta
from sqlalchemy import func

from models import (
    db,
    User,
    Group,
    GroupMember,
    Subscription,
    SubscriptionPlan,
    SubscriptionStatusEnum,
    PaymentReceipt,
    PaymentTypeEnum,
    Certificate,
    RoleEnum  # تمت إضافة هذه
)

# تأكد من جلب صلاحية المدير إذا كانت في ملف آخر، أو تأكد من وجودها
from groups_routes import admin_required as _admin_required 


def _register_role_dashboard_routes(app):
    """
    Register the main dashboard routes and delegate to the appropriate
    helper function based on the user's role.
    """
    @app.route('/')
    @app.route('/dashboard')
    @login_required
    def dashboard():
        if current_user.role.value == 'Admin':
            return _admin_dashboard()
        elif current_user.role.value == 'Supervisor':
            return _supervisor_dashboard()
        elif current_user.role.value == 'Member':
            return _member_dashboard()
        else:
            return "Role not recognized", 403


    # =========================================================================
    #  GET /admin/member/<member_id>   ← إحصائيات المتدرب
    #  يجب أن يكون هذا المسار هنا بالداخل!
    # =========================================================================
    @app.route("/admin/member/<int:member_id>", methods=["GET"])
    @login_required
    @_admin_required
    def admin_member_stats(member_id: int):
        # 1. جلب بيانات الطالب
        member = db.session.get(User, member_id)

        if member is None:
            flash(f"المستخدم رقم {member_id} غير موجود.", "danger")
            return redirect(url_for("users"))

        if member.role != RoleEnum.Member:
            flash(
                f"المستخدم '{member.full_name}' ليس طالباً — "
                f"دوره: {member.role.value}.", "warning",
            )
            return redirect(url_for("users"))

        # 2. جلب المجموعات التي ينتمي إليها الطالب
        enrolled_groups = (
            db.session.query(Group, GroupMember)
            .join(GroupMember, Group.group_id == GroupMember.group_id)
            .filter(GroupMember.member_id == member_id)
            .order_by(GroupMember.joined_date.desc())
            .all()
        )

        # 3. جلب سجل الاشتراكات الخاص بالطالب
        subscriptions = (
            db.session.query(Subscription, SubscriptionPlan)
            .join(SubscriptionPlan, Subscription.plan_id == SubscriptionPlan.plan_id)
            .filter(Subscription.member_id == member_id)
            .order_by(Subscription.end_date.desc())
            .all()
        )

        # 4. جلب الشهادات
        certificates = Certificate.query.filter_by(member_id=member_id).all()
        
        cert_dict = {cert.group_id: cert for cert in certificates}

        return render_template(
            "member_stats.html",
            member=member,
            enrolled_groups=enrolled_groups,
            subscriptions=subscriptions,
            total_groups=len(enrolled_groups),
            total_subs=len(subscriptions),
            total_certs=len(certificates),
            cert_dict=cert_dict,
            today=date.today()
        )

    # =========================================================================
    #  GET /admin/supervisor/<sup_id>   ← إحصائيات المدرب
    # =========================================================================
    @app.route("/admin/supervisor/<int:sup_id>", methods=["GET"])
    @login_required
    @_admin_required
    def admin_supervisor_stats(sup_id: int):
        # 1. جلب بيانات المدرب
        supervisor = db.session.get(User, sup_id)

        if supervisor is None:
            flash(f"المستخدم رقم {sup_id} غير موجود.", "danger")
            return redirect(url_for("users"))

        if supervisor.role != RoleEnum.Supervisor:
            flash(
                f"المستخدم '{supervisor.full_name}' ليس مدرباً — "
                f"دوره: {supervisor.role.value}.", "warning",
            )
            return redirect(url_for("users"))

        # 2. جلب مجموعات المدرب
        sup_groups = Group.query.filter_by(supervisor_id=sup_id).all()
        total_groups = len(sup_groups)

        # 3. جلب طلاب المدرب
        sup_students_raw = (
            db.session.query(GroupMember, User, Group)
            .join(User, GroupMember.member_id == User.user_id)
            .join(Group, GroupMember.group_id == Group.group_id)
            .filter(Group.supervisor_id == sup_id)
            .order_by(Group.group_id, User.fname)
            .all()
        )

        total_students = len(sup_students_raw)
        total_certificates = Certificate.query.filter_by(issued_by=sup_id).count()

        # Build student records with sub & cert context
        sup_students = []
        for gm, member, group in sup_students_raw:
            # Latest subscription
            sub = (
                Subscription.query.filter_by(member_id=member.user_id)
                .order_by(Subscription.end_date.desc())
                .first()
            )
            # Cert status for this specific group
            has_cert = (
                Certificate.query.filter_by(
                    member_id=member.user_id,
                    group_id=group.group_id
                ).first() is not None
            )

            sup_students.append({
                'member':   member,
                'group':    group,
                'gm':       gm,
                'sub':      sub,
                'has_cert': has_cert
            })

        return render_template(
            "supervisor_stats.html",
            supervisor        = supervisor,
            total_groups      = total_groups,
            total_students    = total_students,
            total_certificates = total_certificates,
            sup_groups        = sup_groups,
            sup_students      = sup_students,
            today             = date.today()
        )

# ══════════════════════════════════════════════════════════════════════════
#  1. ADMIN DASHBOARD
# ══════════════════════════════════════════════════════════════════════════
def _admin_dashboard():
    today = date.today()
    month_start = today.replace(day=1)
    EXPIRY_ALERT_DAYS = 15

    # ── Dynamic active-subscriptions breakdown by plan name ───────────
    plan_stats: list[tuple[str, int]] = (
        db.session.query(
            SubscriptionPlan.plan_name,
            func.count(Subscription.subscription_id).label("cnt"),
        )
        .join(SubscriptionPlan, Subscription.plan_id == SubscriptionPlan.plan_id)
        .filter(Subscription.status == SubscriptionStatusEnum.Active)
        .group_by(SubscriptionPlan.plan_name)
        .order_by(func.count(Subscription.subscription_id).desc())
        .all()
    )

    total_active: int = sum(count for _, count in plan_stats)

    # ── Other aggregate stats ─────────────────────────────
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

    # ── Expiring-soon renewal alerts ──────────────────────────────────
    alert_threshold = today + timedelta(days=EXPIRY_ALERT_DAYS)
    expiring_soon = (
        db.session.query(
            Subscription,
            User.fname,
            User.lname,
            User.email,
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
        plan_stats          = plan_stats,
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


# ══════════════════════════════════════════════════════════════════════════
#  2. SUPERVISOR DASHBOARD
# ══════════════════════════════════════════════════════════════════════════
def _supervisor_dashboard():
    user_id = current_user.user_id
    today = date.today()

    # Get Supervisor's Groups
    my_groups = Group.query.filter_by(supervisor_id=user_id).all()
    total_groups = len(my_groups)

    # Get Students in Supervisor's Groups
    my_students_raw = (
        db.session.query(GroupMember, User, Group)
        .join(User, GroupMember.member_id == User.user_id)
        .join(Group, GroupMember.group_id == Group.group_id)
        .filter(Group.supervisor_id == user_id)
        .order_by(Group.group_id, User.fname)
        .all()
    )

    total_students = len(my_students_raw)
    total_certificates = Certificate.query.filter_by(issued_by=user_id).count()

    # Build the students list with subscription and certificate status
    my_students = []
    for gm, member, group in my_students_raw:
        # Get latest subscription
        sub = Subscription.query.filter_by(member_id=member.user_id).order_by(Subscription.end_date.desc()).first()
        # Check if cert is issued for this specific group
        has_cert = Certificate.query.filter_by(member_id=member.user_id, group_id=group.group_id).first() is not None
        
        my_students.append({
            'member': member,
            'group': group,
            'gm': gm,
            'sub': sub,
            'has_cert': has_cert
        })

    return render_template(
        "dashboard.html",
        total_groups=total_groups,
        total_students=total_students,
        total_certificates=total_certificates,
        my_groups=my_groups,
        my_students=my_students,
        today=today
    )


# ══════════════════════════════════════════════════════════════════════════
#  3. MEMBER DASHBOARD
# ══════════════════════════════════════════════════════════════════════════
def _member_dashboard():
    user_id = current_user.user_id
    today = date.today()

    # Latest subscription
    member_subscription = Subscription.query.filter_by(member_id=user_id).order_by(Subscription.end_date.desc()).first()

    # Enrolled groups
    member_groups = (
        db.session.query(Group)
        .join(GroupMember, Group.group_id == GroupMember.group_id)
        .filter(GroupMember.member_id == user_id)
        .all()
    )

    # Quick stats
    member_receipts_count = PaymentReceipt.query.join(Subscription).filter(Subscription.member_id == user_id).count()
    member_certs_count = Certificate.query.filter_by(member_id=user_id).count()

    return render_template(
        "dashboard.html",
        member_subscription=member_subscription,
        member_groups=member_groups,
        member_receipts_count=member_receipts_count,
        member_certs_count=member_certs_count,
        today=today
    )
    