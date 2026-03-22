# =============================================================================
#  receipt_routes.py  —  Route snippet to integrate into app.py
#  Project : أكاديمية شيفرة  (Shyfra Academy)
#
#  Add _register_receipt_routes(app) inside create_app(), e.g.:
#
#      _register_auth_routes(app)
#      _register_dashboard_routes(app)
#      _register_subscription_routes(app)
#      _register_receipt_routes(app)        ← add this line
#      _register_core_routes(app)
#
#  Static assets note (from project structure)
#  ───────────────────────────────────────────
#  All CSS/JS are served LOCALLY — no CDN calls needed:
#      static/css/bootstrap.rtl.min.css
#      static/css/fontawesome.css
#      static/css/fonts.css
#      static/js/bootstrap.bundle.min.js
#      static/webfonts/   ← FontAwesome icon fonts
#      static/fonts/      ← IBM Plex Sans Arabic + JetBrains Mono
# =============================================================================

from flask import abort, flash, redirect, render_template, url_for
from flask_login import current_user, login_required

from models import (
    PaymentReceipt,
    Subscription,
    SubscriptionPlan,
    User,
    db,
)


def _register_receipt_routes(app) -> None:
    """Register all receipt and print routes onto the Flask app instance."""

    # =========================================================================
    #  1.  GET /member/<member_id>/receipts
    #      Full receipt history for one member.
    #      Joined with Subscriptions + Subscription_Plans + Users so the
    #      template needs zero additional lazy-load queries.
    # =========================================================================

    @app.route("/member/<int:member_id>/receipts", methods=["GET"])
    @login_required
    def member_receipts(member_id: int):
        """
        Display the complete payment / receipt history for a single member.

        Access rules
        ────────────
        Admin       → can view any member's receipts.
        Supervisor  → can view receipts of members in their own groups.
                      (simplified here: allowed for now, scope later via blueprint)
        Member      → can ONLY view their own receipts.

        Template variables
        ──────────────────
        member          User object (the member being viewed)
        receipts        list of (PaymentReceipt, Subscription, SubscriptionPlan)
        total_paid      float – sum of all amount_paid for this member
        viewer          current_user – for role-based UI decisions in template
        """

        # ── Fetch the member (404 if not found) ──────────────────────────
        member: User = db.get_or_404(
            User, member_id,
            description=f"العضو رقم {member_id} غير موجود."
        )

        # ── Access control: members can only see their own receipts ───────
        if current_user.is_member and current_user.user_id != member_id:
            flash("ليس لديك صلاحية لعرض إيصالات هذا العضو.", "danger")
            return redirect(url_for("dashboard"))

        # ── Fetch receipt history — single JOIN query ─────────────────────
        #  Order: newest payment first so the most recent receipt is at top.
        receipts = (
            db.session.query(PaymentReceipt, Subscription, SubscriptionPlan, User)
            .join(
                Subscription,
                PaymentReceipt.subscription_id == Subscription.subscription_id,
            )
            .join(
                SubscriptionPlan,
                Subscription.plan_id == SubscriptionPlan.plan_id,
            )
            .join(
                User,
                Subscription.member_id == User.user_id,
            )
            .filter(Subscription.member_id == member_id)
            .order_by(PaymentReceipt.payment_date.desc())
            .all()
        )

        # ── Aggregate: total amount paid by this member (all time) ────────
        total_paid: float = sum(
            float(receipt.amount_paid) for receipt, _, __, ___ in receipts
        )

        return render_template(
            "receipts.html",
            receipts      = receipts,
            search_query  = "",
            type_filter   = "",
            total_revenue = total_paid,
            viewer_role   = current_user.role.value,
        )


    # =========================================================================
    #  2.  GET /receipt/<receipt_id>/print
    #      Fetch one receipt and render a clean, print-ready page.
    #      This route intentionally renders a STANDALONE template
    #      (print_receipt.html does NOT extend base.html) so that
    #      window.print() produces a clean A4 document without the
    #      sidebar or navbar appearing on paper.
    # =========================================================================

    @app.route("/receipt/<int:receipt_id>/print", methods=["GET"])
    @login_required
    def print_receipt(receipt_id: int):
        """
        Render a single, printable receipt page.

        Design decision: standalone template
        ─────────────────────────────────────
        The template does NOT extend base.html.  This means:
        • No sidebar, no topbar, no flash-message container.
        • The browser's Print dialog (window.print()) captures only the
          receipt content → clean A4 output.
        • CSS @media print rules in the template hide the "Print" button
          itself so it never appears on paper.

        Access rules
        ────────────
        Admin / Supervisor → can print any receipt.
        Member             → can only print their own receipts.

        Template variables
        ──────────────────
        receipt         PaymentReceipt ORM object
        subscription    Subscription ORM object
        plan            SubscriptionPlan ORM object
        member          User ORM object (the paying member)
        receipt_number  str – human-readable ref (e.g. "REC-00003")
        """

        # ── Fetch receipt + related data in one query ─────────────────────
        result = (
            db.session.query(PaymentReceipt, Subscription, SubscriptionPlan, User)
            .join(
                Subscription,
                PaymentReceipt.subscription_id == Subscription.subscription_id,
            )
            .join(
                SubscriptionPlan,
                Subscription.plan_id == SubscriptionPlan.plan_id,
            )
            .join(
                User,
                Subscription.member_id == User.user_id,
            )
            .filter(PaymentReceipt.receipt_id == receipt_id)
            .first()
        )

        # ── 404 if receipt doesn't exist ──────────────────────────────────
        if result is None:
            abort(404)

        receipt, subscription, plan, member = result

        # ── Access control ────────────────────────────────────────────────
        if current_user.is_member and current_user.user_id != member.user_id:
            flash("ليس لديك صلاحية لطباعة هذا الإيصال.", "danger")
            return redirect(url_for("dashboard"))

        # ── Human-readable receipt reference number ────────────────────────
        receipt_number: str = f"REC-{receipt.receipt_id:05d}"

        return render_template(
            "print_receipt.html",
            receipt        = receipt,
            subscription   = subscription,
            plan           = plan,
            member         = member,
            receipt_number = receipt_number,
        )