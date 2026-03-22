# =============================================================================
#  payment_routes.py  —  Self-service mock payment gateway (Member only)
#  Project : أكاديمية شيفرة  (Shyfra Academy)
#
#  Add _register_payment_routes(app) inside create_app() AFTER the role
#  dashboard and BEFORE core routes:
#
#      _register_role_dashboard_routes(app)
#      _register_payment_routes(app)          ← add this line
#      _register_subscription_routes(app)
#      ...
#
#  Requirements
#  ────────────
#  pip install python-dateutil          (for relativedelta month arithmetic)
#
#  Routes
#  ──────
#  GET  /checkout         → checkout()         show plan selection page
#  POST /process_payment  → process_payment()  create/renew subscription
# =============================================================================

from datetime import date
from functools import wraps

from dateutil.relativedelta import relativedelta          # month-safe arithmetic

from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from models import (
    PaymentReceipt,
    PaymentTypeEnum,
    Subscription,
    SubscriptionPlan,
    SubscriptionStatusEnum,
    db,
)


# ─────────────────────────────────────────────────────────────────────────────
#  Member-only guard decorator
#  Stacks on top of @login_required — apply in order shown below.
# ─────────────────────────────────────────────────────────────────────────────

def _member_required(f):
    """Restrict a route to users with the Member role only."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_member:
            flash("هذه الصفحة مخصصة للطلاب فقط.", "warning")
            return redirect(url_for("dashboard"))
        return f(*args, **kwargs)
    return decorated


# ─────────────────────────────────────────────────────────────────────────────
#  Registration function — called from create_app()
# ─────────────────────────────────────────────────────────────────────────────

def _register_payment_routes(app) -> None:

    # =========================================================================
    #  GET /checkout
    #  Show the plan-selection / mock payment page for Members.
    #
    #  Template variables
    #  ──────────────────
    #  active_plans        list[SubscriptionPlan]  — plans with is_active=True,
    #                                                ordered short→long duration
    #  current_subscription  Subscription | None   — member's most recent sub
    #                                                (any status), so the
    #                                                template can show context
    #                                                ("Renewing" vs "New")
    # =========================================================================

    @app.route("/checkout", methods=["GET"])
    @login_required
    @_member_required
    def checkout():
        """
        Render the mock checkout page.

        We query only is_active plans so hidden / deprecated plans are never
        shown to students even if they know the URL.
        """

        active_plans: list[SubscriptionPlan] = (
            SubscriptionPlan.query
            .filter_by(is_active=True)
            .order_by(SubscriptionPlan.duration_months.asc())
            .all()
        )

        # Most recent subscription for this member (any status) so the
        # template can render a "you are renewing" vs "new subscription" message.
        current_subscription: Subscription | None = (
            Subscription.query
            .filter_by(member_id=current_user.user_id)
            .order_by(Subscription.start_date.desc())
            .first()
        )

        return render_template(
            "checkout.html",
            active_plans         = active_plans,
            current_subscription = current_subscription,
        )


    # =========================================================================
    #  POST /process_payment
    #  Mock payment processor — creates or updates a Subscription record
    #  and always generates a PaymentReceipt.
    #
    #  Form fields
    #  ───────────
    #  plan_id : int  (required — ID of the chosen SubscriptionPlan)
    #
    #  Business logic summary
    #  ──────────────────────
    #
    #  Case A — NO existing subscription at all:
    #      → Create Subscription(start=today, end=today+months, status=Active)
    #      → PaymentReceipt(type=New)
    #
    #  Case B — Existing subscription, status Active:
    #      → Keep current plan_id OR switch to new plan (user's choice)
    #      → Extend: new_end = current_end + relativedelta(months=duration)
    #        (extends FORWARD from end_date — early renewal is honoured)
    #      → PaymentReceipt(type=Renewal)
    #
    #  Case C — Existing subscription, status Expired or Canceled:
    #      → Restart: start=today, end=today+months, status=Active
    #      → PaymentReceipt(type=Renewal)  ← still a renewal on the same record
    #
    #  Case D — Existing subscription, status Suspended:
    #      → Treat as renewal: start=today, end=today+months, status=Active
    #        (the suspended period is "forgiven" — simpler UX for a project)
    #      → PaymentReceipt(type=Renewal)
    #
    #  In all cases we UPDATE the existing Subscription record if one exists,
    #  so that the member's receipt history stays linked to a single contract.
    # =========================================================================

    @app.route("/process_payment", methods=["POST"])
    @login_required
    @_member_required
    def process_payment():
        """
        Handle mock payment form submission.

        Security notes
        ──────────────
        • plan_id is validated against the DB (must exist AND be is_active).
          A student cannot pay for a hidden plan by crafting a POST request.
        • We never trust the price from the form — price is always read from
          the DB plan record.
        • relativedelta is used for month arithmetic so "1 month from Jan 31"
          correctly yields Feb 28/29, not an invalid date.
        """

        today = date.today()

        # ── 1. Read and validate plan_id ──────────────────────────────────
        raw_plan_id = request.form.get("plan_id", "").strip()

        if not raw_plan_id or not raw_plan_id.isdigit():
            flash("يرجى اختيار خطة اشتراك صالحة.", "danger")
            return redirect(url_for("checkout"))

        plan: SubscriptionPlan | None = SubscriptionPlan.query.filter_by(
            plan_id=int(raw_plan_id),
            is_active=True,
        ).first()

        if plan is None:
            flash("الخطة المختارة غير متاحة. يرجى اختيار خطة أخرى.", "danger")
            return redirect(url_for("checkout"))

        # ── 2. Look up member's most-recent subscription (any status) ─────
        #  We deliberately pick the latest one (newest start_date) so that
        #  a member who has had multiple subscriptions continues the most
        #  recent one rather than accidentally resurrecting an old one.
        existing_sub: Subscription | None = (
            Subscription.query
            .filter_by(member_id=current_user.user_id)
            .order_by(Subscription.start_date.desc())
            .first()
        )

        # ── 3. Compute dates and determine payment type ────────────────────
        if existing_sub is None:
            # ── Case A: brand-new subscriber ─────────────────────────────
            new_start      = today
            new_end        = today + relativedelta(months=plan.duration_months)
            payment_type   = PaymentTypeEnum.New
            notes          = f"اشتراك جديد — خطة {plan.plan_name}"

            new_sub = Subscription(
                member_id  = current_user.user_id,
                plan_id    = plan.plan_id,
                start_date = new_start,
                end_date   = new_end,
                status     = SubscriptionStatusEnum.Active,
            )
            db.session.add(new_sub)
            db.session.flush()          # assign subscription_id before receipt

            target_sub = new_sub

        else:
            # ── Cases B / C / D: existing subscription ────────────────────
            payment_type = PaymentTypeEnum.Renewal

            current_status = existing_sub.status

            if current_status == SubscriptionStatusEnum.Active:
                # Case B — extend forward from current end_date
                base_date = existing_sub.end_date
                new_end   = base_date + relativedelta(months=plan.duration_months)
                notes     = (
                    f"تجديد — خطة {plan.plan_name} "
                    f"(تمديد من {base_date} إلى {new_end})"
                )
                existing_sub.end_date = new_end

            else:
                # Cases C & D — Expired / Canceled / Suspended → restart today
                new_start = today
                new_end   = today + relativedelta(months=plan.duration_months)
                notes     = (
                    f"إعادة تفعيل — خطة {plan.plan_name} "
                    f"(بدء جديد من {today})"
                )
                existing_sub.start_date = new_start
                existing_sub.end_date   = new_end

            # Always switch to the chosen plan and reactivate
            existing_sub.plan_id = plan.plan_id
            existing_sub.status  = SubscriptionStatusEnum.Active

            target_sub = existing_sub

        # ── 4. Create the payment receipt ─────────────────────────────────
        #  Price is ALWAYS read from the DB plan — never from the form.
        receipt = PaymentReceipt(
            subscription_id = target_sub.subscription_id,
            amount_paid     = plan.price,
            payment_date    = today,
            payment_type    = payment_type,
            notes           = notes,
        )
        db.session.add(receipt)

        # ── 5. Commit everything atomically ───────────────────────────────
        try:
            db.session.commit()

            # Build a context-aware success message
            if payment_type == PaymentTypeEnum.New:
                flash(
                    f"🎉 تم الدفع وتفعيل اشتراكك بنجاح! "
                    f"خطة {plan.plan_name} — تنتهي في "
                    f"{target_sub.end_date.strftime('%Y-%m-%d')}.",
                    "success",
                )
            else:
                flash(
                    f"✅ تم الدفع وتجديد اشتراكك بنجاح! "
                    f"خطة {plan.plan_name} — تاريخ الانتهاء الجديد: "
                    f"{target_sub.end_date.strftime('%Y-%m-%d')}.",
                    "success",
                )

        except Exception as exc:
            db.session.rollback()
            app.logger.error(
                f"process_payment error — user={current_user.user_id} "
                f"plan={plan.plan_id}: {exc}"
            )
            flash(
                "حدث خطأ أثناء معالجة الدفع. لم يتم خصم أي مبلغ. "
                "يرجى المحاولة مجدداً.",
                "danger",
            )
            return redirect(url_for("checkout"))

        # ── 6. Redirect to member dashboard ───────────────────────────────
        return redirect(url_for("dashboard"))