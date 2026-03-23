# =============================================================================
#  subscriptions_routes.py  —  Route snippet to integrate into app.py
#  Project : أكاديمية شيفرة  (Shyfra Academy)
#
#  Paste _register_subscription_routes(app) into create_app(), after the
#  existing route-registration calls:
#
#      _register_auth_routes(app)
#      _register_dashboard_routes(app)
#      _register_subscription_routes(app)   ← add this line
#      _register_core_routes(app)
#
#  All models, db, login_manager are assumed to be already imported.
# =============================================================================

from datetime import date
from dateutil.relativedelta import relativedelta   # pip install python-dateutil

from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from models import (
    PaymentReceipt,
    PaymentTypeEnum,
    Subscription,
    SubscriptionPlan,
    SubscriptionStatusEnum,
    User,
    RoleEnum,
    db,
)


# ─────────────────────────────────────────────────────────────────────────────
#  Allowed status transitions
#  Only these values are accepted from the URL parameter.
#  'Expired' is intentionally excluded — expiry is set by the system,
#  not manually by a user action.
# ─────────────────────────────────────────────────────────────────────────────
_ALLOWED_MANUAL_STATUSES: frozenset[str] = frozenset({
    "Active",
    "Suspended",
    "Canceled",
})


def _register_subscription_routes(app) -> None:
    """Register all /subscriptions routes onto the Flask app instance."""

    # =========================================================================
    #  1.  GET /subscriptions
    #      List all subscriptions, joined with member and plan data.
    #      Supports optional ?status= filter and ?q= name/email search.
    # =========================================================================

    @app.route("/subscriptions", methods=["GET"])
    @login_required
    def subscriptions():
        """
        Render the full subscription list with optional server-side filtering.

        Query parameters
        ────────────────
        status  : filter by subscription status  (Active | Expired | Suspended | Canceled)
        q       : search substring in member first name, last name, or email

        Template variables
        ──────────────────
        subscriptions   list of (Subscription, User, SubscriptionPlan) tuples
        status_filter   str   – currently applied status filter (or '')
        search_query    str   – currently applied search term   (or '')
        status_choices  list  – all SubscriptionStatusEnum values (for filter UI)
        today           date  – current date for days-remaining calculations
        """

        status_filter: str = request.args.get("status", "").strip()
        search_query:  str = request.args.get("q",      "").strip()

        # ── Base query: always JOIN member + plan so template needs no lazy loads
        query = (
            db.session.query(Subscription, User, SubscriptionPlan)
            .join(User,             Subscription.member_id == User.user_id)
            .join(SubscriptionPlan, Subscription.plan_id   == SubscriptionPlan.plan_id)
        )

        # ── Member isolation: students only see their own subscriptions ───
        if current_user.is_member:
            query = query.filter(Subscription.member_id == current_user.user_id)
        # ── Supervisor isolation: supervisors only see their students 
        elif current_user.role == RoleEnum.Supervisor:
            from models import GroupMember, Group
            query = (
                query
                .join(GroupMember, Subscription.member_id == GroupMember.member_id)
                .join(Group, Group.group_id == GroupMember.group_id)
                .filter(Group.supervisor_id == current_user.user_id)
                .distinct()
            )
        # ── Optional: filter by status ────────────────────────────────────
        if status_filter:
            try:
                status_enum = SubscriptionStatusEnum(status_filter)
                query = query.filter(Subscription.status == status_enum)
            except ValueError:
                # Unknown status value — ignore silently, show all
                status_filter = ""

        # ── Optional: search by member name or email (case-insensitive) ──
        if search_query:
            like = f"%{search_query}%"
            query = query.filter(
                db.or_(
                    User.fname.ilike(like),
                    User.lname.ilike(like),
                    User.email.ilike(like),
                )
            )

        # ── Ordering: Active first, then by end_date ascending (most urgent) ─
        query = query.order_by(
            db.case(
                (Subscription.status == SubscriptionStatusEnum.Active, 0),
                (Subscription.status == SubscriptionStatusEnum.Suspended, 1),
                (Subscription.status == SubscriptionStatusEnum.Expired, 2),
                else_=3,
            ),
            Subscription.end_date.asc(),
        )

        all_subscriptions = query.all()

        return render_template(
            "subscriptions.html",
            subscriptions  = all_subscriptions,
            status_filter  = status_filter,
            search_query   = search_query,
            status_choices = list(SubscriptionStatusEnum),
            today          = date.today(),
        )


    # =========================================================================
    #  2.  POST /subscriptions/<sub_id>/status/<new_status>
    #      Change the status of a subscription (Active / Suspended / Canceled).
    #      'Expired' is excluded — the system sets that automatically.
    # =========================================================================

    @app.route(
        "/subscriptions/<int:sub_id>/status/<string:new_status>",
        methods=["POST"],
    )
    @login_required
    def update_subscription_status(sub_id: int, new_status: str):
        """
        Update a subscription's status.

        Security notes
        ──────────────
        • Only Admin / Supervisor can change statuses.
          Members cannot mutate their own subscriptions this way.
        • new_status is validated against _ALLOWED_MANUAL_STATUSES before
          any DB write — prevents arbitrary enum injection via URL.
        • We use .get_or_404() so non-existent sub_ids return 404, not 500.

        Transition rules
        ────────────────
        Any status → Active    : allowed (reactivation)
        Any status → Suspended : allowed (pause)
        Any status → Canceled  : allowed (hard stop; irreversible in UI)
        Any status → Expired   : NOT allowed via this endpoint (system-only)
        """

        # ── Role guard ────────────────────────────────────────────────────
        if not current_user.is_admin:
            flash("تعديل الاشتراكات مخصص للإدارة فقط.", "danger")
            return redirect(url_for("subscriptions"))

        # ── Validate new_status against allowlist ─────────────────────────
        if new_status not in _ALLOWED_MANUAL_STATUSES:
            flash(
                f"حالة الاشتراك '{new_status}' غير مقبولة. "
                f"القيم المسموح بها: {', '.join(_ALLOWED_MANUAL_STATUSES)}.",
                "danger",
            )
            return redirect(url_for("subscriptions"))

        # ── Fetch subscription (404 if missing) ───────────────────────────
        sub: Subscription = db.get_or_404(
            Subscription, sub_id,
            description=f"الاشتراك رقم {sub_id} غير موجود."
        )

        # ── Guard: no-op if status is already the target ──────────────────
        target_enum = SubscriptionStatusEnum(new_status)
        if sub.status == target_enum:
            flash("الاشتراك في هذه الحالة بالفعل. لا يوجد تغيير.", "info")
            return redirect(url_for("subscriptions"))

        # ── Guard: prevent reactivating a Canceled subscription ───────────
        #  Once canceled, a new subscription record should be created instead.
        if sub.status == SubscriptionStatusEnum.Canceled and new_status == "Active":
            flash(
                "لا يمكن إعادة تفعيل اشتراك ملغى. "
                "أنشئ اشتراكاً جديداً للعضو.",
                "warning",
            )
            return redirect(url_for("subscriptions"))

        # ── Apply change ──────────────────────────────────────────────────
        old_status_label = sub.status.value
        sub.status       = target_enum

        try:
            db.session.commit()
            # Build a human-readable Arabic label for the flash message
            _ar_labels = {
                "Active":    "نشط ✅",
                "Suspended": "معلّق ⏸",
                "Canceled":  "ملغى ❌",
            }
            flash(
                f"تم تغيير حالة الاشتراك #{sub_id} "
                f"من '{old_status_label}' إلى '{_ar_labels.get(new_status, new_status)}'.",
                "success",
            )
        except Exception as exc:
            db.session.rollback()
            app.logger.error(f"Status update failed for sub {sub_id}: {exc}")
            flash("حدث خطأ أثناء تحديث حالة الاشتراك. يرجى المحاولة مجدداً.", "danger")

        return redirect(url_for("subscriptions"))


    # =========================================================================
    #  3.  POST /subscriptions/<sub_id>/renew
    #      Renew a subscription:
    #        • Extend end_date by plan's duration_months
    #        • Create a new PaymentReceipt (payment_type = 'Renewal')
    #        • Set status back to 'Active' if it was Expired or Suspended
    # =========================================================================

    @app.route("/subscriptions/<int:sub_id>/renew", methods=["POST"])
    @login_required
    def renew_subscription(sub_id: int):
        """
        Renew a subscription by one plan-duration cycle.

        Business logic
        ──────────────
        end_date calculation
            We extend from max(end_date, today) so that:
            • A future-dated active sub is extended FORWARD from end_date.
            • An expired/suspended sub (end_date < today) restarts from TODAY,
              not from a date in the past — avoids creating phantom "free" time.

        Receipt
            A new Payments_Receipts row is always created with the plan's
            current price.  The `amount_paid` can be overridden via a
            POST field `custom_amount` (e.g. discounts) — falls back to
            plan price if not supplied or invalid.

        Status
            Only Expired and Suspended subscriptions have their status changed
            back to Active.  An already-Active subscription stays Active
            (normal early renewal).  Canceled subscriptions are blocked.
        """

        # ── Role guard ────────────────────────────────────────────────────
        if not current_user.is_admin:
            flash("تجديد الاشتراكات مخصص للإدارة فقط.", "danger")
            return redirect(url_for("subscriptions"))

        # ── Fetch subscription + plan in one query ────────────────────────
        result = (
            db.session.query(Subscription, SubscriptionPlan)
            .join(SubscriptionPlan, Subscription.plan_id == SubscriptionPlan.plan_id)
            .filter(Subscription.subscription_id == sub_id)
            .first()
        )

        if result is None:
            flash(f"الاشتراك رقم {sub_id} غير موجود.", "danger")
            return redirect(url_for("subscriptions"))

        sub: Subscription        = result[0]
        plan: SubscriptionPlan   = result[1]

        # ── Guard: cannot renew a Canceled subscription ────────────────────
        if sub.status == SubscriptionStatusEnum.Canceled:
            flash(
                "لا يمكن تجديد اشتراك ملغى. "
                "أنشئ اشتراكاً جديداً للعضو.",
                "warning",
            )
            return redirect(url_for("subscriptions"))

        # ── Calculate new end_date ─────────────────────────────────────────
        today = date.today()

        # Extend from end_date if it's still in the future; otherwise from today
        base_date    = sub.end_date if sub.end_date >= today else today
        new_end_date = base_date + relativedelta(months=plan.duration_months)

        # ── Determine amount paid ──────────────────────────────────────────
        # Accept an optional custom_amount from the POST body (for discounts)
        raw_amount = request.form.get("custom_amount", "").strip()
        try:
            amount_paid = float(raw_amount) if raw_amount else float(plan.price)
            if amount_paid < 0:
                raise ValueError("Negative amount")
        except (ValueError, TypeError):
            amount_paid = float(plan.price)   # fall back to plan price silently

        # ── Apply changes inside a single transaction ──────────────────────
        try:
            # 1. Extend the subscription
            old_end_date  = sub.end_date
            sub.end_date  = new_end_date

            # 2. Reactivate if expired or suspended
            reactivated = False
            if sub.status in (SubscriptionStatusEnum.Expired,
                              SubscriptionStatusEnum.Suspended):
                sub.status  = SubscriptionStatusEnum.Active
                reactivated = True

            # 3. Create the renewal receipt
            receipt = PaymentReceipt(
                subscription_id = sub.subscription_id,
                amount_paid     = amount_paid,
                payment_date    = today,
                payment_type    = PaymentTypeEnum.Renewal,
                notes           = (
                    f"تجديد تلقائي بواسطة {current_user.full_name} "
                    f"— من {old_end_date} إلى {new_end_date}"
                ),
            )
            db.session.add(receipt)
            db.session.commit()

            # ── Build success message ──────────────────────────────────────
            msg = (
                f"تم تجديد الاشتراك #{sub_id} بنجاح. "
                f"تاريخ الانتهاء الجديد: {new_end_date.strftime('%Y-%m-%d')}. "
                f"المبلغ المسجَّل: {amount_paid:,.2f} دج."
            )
            if reactivated:
                msg += " تم إعادة تفعيل الاشتراك. ✅"

            flash(msg, "success")

        except Exception as exc:
            db.session.rollback()
            app.logger.error(f"Renewal failed for sub {sub_id}: {exc}")
            flash(
                "حدث خطأ أثناء تجديد الاشتراك. "
                "تم التراجع عن جميع التغييرات. يرجى المحاولة مجدداً.",
                "danger",
            )

        return redirect(url_for("subscriptions"))