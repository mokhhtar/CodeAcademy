# =============================================================================
#  list_routes.py  —  Index / List routes for Receipts and Certificates
#  Project : أكاديمية شيفرة  (Shyfra Academy)
#
#  These are the routes that the sidebar links point to.
#  They are separate from the per-member and print routes.
#
#  Add _register_list_routes(app) inside create_app():
#
#      _register_auth_routes(app)
#      _register_dashboard_routes(app)
#      _register_subscription_routes(app)
#      _register_receipt_routes(app)
#      _register_certificate_routes(app)
#      _register_list_routes(app)            ← add this line
#      _register_core_routes(app)
#
#  Sidebar links should point to:
#      url_for('all_receipts')       → /receipts
#      url_for('certificates')       → /certificates   (already defined below,
#                                        replaces the one in certificate_routes)
# =============================================================================

from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy.orm import aliased

from models import (
    Certificate,
    Group,
    PaymentReceipt,
    RoleEnum,
    Subscription,
    SubscriptionPlan,
    User,
    db,
)


def _register_list_routes(app) -> None:
    """Register the two sidebar index routes onto the Flask app instance."""

    # =========================================================================
    #  1.  GET /receipts
    #      Global receipt list — all members (Admin/Supervisor) or own only
    #      (Member).  Supports optional ?q= search and ?type= filter.
    # =========================================================================

    @app.route("/receipts", methods=["GET"])
    @login_required
    def all_receipts():
        """
        Render the full receipt / payment history list.

        Access rules
        ────────────
        Admin / Supervisor → see all receipts across every member.
        Member             → sees ONLY their own receipts.

        Query parameters
        ────────────────
        q       : search substring in member name or email
        type    : filter by payment_type ('New' | 'Renewal')

        Template variables
        ──────────────────
        receipts        list of (PaymentReceipt, Subscription,
                                 SubscriptionPlan, User)
        search_query    str  – active search term
        type_filter     str  – active payment_type filter
        total_revenue   float – sum of all amount_paid in current result set
        viewer_role     str  – current_user role value for UI decisions
        """

        search_query: str = request.args.get("q",    "").strip()
        type_filter:  str = request.args.get("type", "").strip()

        # ── Base query: single JOIN fetches everything the template needs ──
        query = (
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
        )

        # ── Role-based scoping ────────────────────────────────────────────
        if current_user.role == RoleEnum.Member:
            query = query.filter(
                Subscription.member_id == current_user.user_id
            )

        # ── Optional: filter by payment type ─────────────────────────────
        if type_filter in ("New", "Renewal"):
            from models import PaymentTypeEnum
            try:
                query = query.filter(
                    PaymentReceipt.payment_type == PaymentTypeEnum(type_filter)
                )
            except ValueError:
                type_filter = ""

        # ── Optional: search by member name or email ──────────────────────
        if search_query:
            like = f"%{search_query}%"
            query = query.filter(
                db.or_(
                    User.fname.ilike(like),
                    User.lname.ilike(like),
                    User.email.ilike(like),
                )
            )

        # ── Order: most recent payment first ──────────────────────────────
        results = (
            query
            .order_by(PaymentReceipt.payment_date.desc())
            .all()
        )

        # ── Aggregate total revenue for current filter ────────────────────
        total_revenue: float = sum(
            float(receipt.amount_paid) for receipt, _, __, ___ in results
        )

        return render_template(
            "receipts.html",
            receipts      = results,
            search_query  = search_query,
            type_filter   = type_filter,
            total_revenue = total_revenue,
            viewer_role   = current_user.role.value,
        )


    # =========================================================================
    #  2.  GET /certificates
    #      Global certificate list.  Replaces the version in
    #      certificate_routes.py — keep only this definition in the final app.
    #
    #      The double-alias pattern is required because Certificates has
    #      two FK columns that both reference the Users table:
    #          Certificate.member_id  → the student
    #          Certificate.issued_by  → the supervisor
    # =========================================================================

    @app.route("/certificates", methods=["GET"])
    @login_required
    def certificates():
        """
        Render the full certificate list.

        Access rules
        ────────────
        Admin      → sees all certificates.
        Supervisor → sees only certificates they personally issued.
        Member     → sees only their own certificates.

        Query parameters
        ────────────────
        q       : search substring in member name, email, or group name

        Template variables
        ──────────────────
        certificates    list of (Certificate, MemberUser, Group, IssuerUser|None)
        search_query    str  – active search term
        viewer_role     str  – current_user role value for UI decisions
        """

        search_query: str = request.args.get("q", "").strip()

        # Two aliases — one per FK relationship on Users
        MemberAlias = aliased(User, name="member")
        IssuerAlias = aliased(User, name="issuer")

        # ── Base query ────────────────────────────────────────────────────
        query = (
            db.session.query(Certificate, MemberAlias, Group, IssuerAlias)
            .join(MemberAlias, Certificate.member_id == MemberAlias.user_id)
            .join(Group,       Certificate.group_id  == Group.group_id)
            # outerjoin: certificate survives if issuer was deleted (SET NULL)
            .outerjoin(IssuerAlias, Certificate.issued_by == IssuerAlias.user_id)
        )

        # ── Role-based scoping ────────────────────────────────────────────
        if current_user.role == RoleEnum.Member:
            query = query.filter(
                Certificate.member_id == current_user.user_id
            )
        elif current_user.role == RoleEnum.Supervisor:
            query = query.filter(
                Certificate.issued_by == current_user.user_id
            )
        # Admin: no additional filter

        # ── Optional: search by member name, email, or group/course name ──
        if search_query:
            like = f"%{search_query}%"
            query = query.filter(
                db.or_(
                    MemberAlias.fname.ilike(like),
                    MemberAlias.lname.ilike(like),
                    MemberAlias.email.ilike(like),
                    Group.group_name.ilike(like),
                )
            )

        # ── Order: most recently issued first ─────────────────────────────
        results = (
            query
            .order_by(Certificate.issue_date.desc())
            .all()
        )

        return render_template(
            "certificates.html",
            certificates = results,
            search_query = search_query,
            viewer_role  = current_user.role.value,
        )