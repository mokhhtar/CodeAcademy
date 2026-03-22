# =============================================================================
#  plans_routes.py  —  Route snippet to integrate into app.py
#  Project : أكاديمية شيفرة  (Shyfra Academy)
#
#  Add _register_plan_routes(app) inside create_app():
#
#      ...
#      _register_group_routes(app)
#      _register_plan_routes(app)            ← add this line
#      _register_core_routes(app)
#
#  Requires: admin_required decorator (defined in groups_routes.py).
#  Import or redefine it here if plans_routes is loaded independently.
# =============================================================================

from flask import flash, redirect, render_template, request, url_for
from flask_login import login_required

from models import SubscriptionPlan, db


# ─────────────────────────────────────────────────────────────────────────────
#  If admin_required is not already imported from groups_routes, redefine it:
#
#  from functools import wraps
#  from flask_login import current_user
#  from flask import flash, redirect, url_for
#
#  def admin_required(f):
#      @wraps(f)
#      def decorated(*args, **kwargs):
#          if not current_user.is_admin:
#              flash("هذه الصفحة مخصصة للمسؤول فقط.", "danger")
#              return redirect(url_for("dashboard"))
#          return f(*args, **kwargs)
#      return decorated
#
#  In the final app.py, define admin_required once at module level and
#  reuse it across all route-registration functions.
# ─────────────────────────────────────────────────────────────────────────────


def _register_plan_routes(app) -> None:
    """Register all /plans routes onto the Flask app instance."""

    from groups_routes import admin_required


    # =========================================================================
    #  1.  GET /plans
    #      List all subscription plans (active and inactive).
    # =========================================================================

    @app.route("/plans", methods=["GET"])
    @login_required
    def plans():
        """
        Render the subscription plans management page.

        Template variables
        ──────────────────
        plans   list[SubscriptionPlan]  — all plans, active first
        """
        all_plans = (
            SubscriptionPlan.query
            .order_by(
                SubscriptionPlan.is_active.desc(),   # active plans first
                SubscriptionPlan.duration_months.asc(),
            )
            .all()
        )

        return render_template("plans.html", plans=all_plans)


    # =========================================================================
    #  2.  POST /plans/add
    #      Create a new subscription plan.
    # =========================================================================

    @app.route("/plans/add", methods=["POST"])
    @login_required
    @admin_required
    def add_plan():
        """
        Handle the Add Plan form submission.

        Form fields
        ───────────
        plan_name        : str   (required, must be unique)
        duration_months  : int   (required, must be ≥ 1)
        price            : float (required, must be > 0)
        """

        plan_name       = request.form.get("plan_name",       "").strip()
        duration_months = request.form.get("duration_months", "").strip()
        price           = request.form.get("price",           "").strip()

        # ── Presence validation ───────────────────────────────────────────
        if not plan_name or not duration_months or not price:
            flash("جميع الحقول مطلوبة (الاسم، المدة، السعر).", "danger")
            return redirect(url_for("plans"))

        # ── Type / range validation ────────────────────────────────────────
        try:
            duration_months = int(duration_months)
            if duration_months < 1:
                raise ValueError
        except ValueError:
            flash("مدة الخطة يجب أن تكون رقماً صحيحاً موجباً (شهر واحد على الأقل).", "danger")
            return redirect(url_for("plans"))

        try:
            price = float(price)
            if price <= 0:
                raise ValueError
        except ValueError:
            flash("السعر يجب أن يكون رقماً موجباً أكبر من صفر.", "danger")
            return redirect(url_for("plans"))

        # ── Duplicate name check (case-insensitive) ────────────────────────
        existing = SubscriptionPlan.query.filter(
            SubscriptionPlan.plan_name.ilike(plan_name)
        ).first()
        if existing:
            flash(f"توجد خطة باسم '{plan_name}' مسبقاً.", "warning")
            return redirect(url_for("plans"))

        # ── Create and persist ────────────────────────────────────────────
        new_plan = SubscriptionPlan(
            plan_name       = plan_name,
            duration_months = duration_months,
            price           = price,
            is_active       = True,    # always active by default
        )

        try:
            db.session.add(new_plan)
            db.session.commit()
            flash(
                f"تم إنشاء خطة '{plan_name}' "
                f"({duration_months} شهر — {price:,.2f} دج) بنجاح. ✅",
                "success",
            )
        except Exception as exc:
            db.session.rollback()
            app.logger.error(f"add_plan error: {exc}")
            flash("حدث خطأ أثناء إنشاء الخطة. يرجى المحاولة مجدداً.", "danger")

        return redirect(url_for("plans"))


    # =========================================================================
    #  3.  POST /plans/toggle/<plan_id>
    #      Toggle the is_active flag of a plan (True ↔ False).
    #
    #      Design note: POST (not GET) prevents CSRF via link-following.
    #      A plan that has active subscriptions can still be toggled to
    #      is_active=False (hidden from new sales) — existing subscriptions
    #      are not affected because Subscriptions.plan_id uses RESTRICT,
    #      not CASCADE.
    # =========================================================================

    @app.route("/plans/toggle/<int:plan_id>", methods=["POST"])
    @login_required
    @admin_required
    def toggle_plan(plan_id: int):
        """
        Toggle a plan's is_active status.

        is_active = True  → False  (plan hidden from new subscriptions)
        is_active = False → True   (plan available again)
        """
        plan = db.get_or_404(
            SubscriptionPlan, plan_id,
            description=f"الخطة رقم {plan_id} غير موجودة."
        )

        plan.is_active = not plan.is_active
        new_state_ar   = "مفعَّلة ✅" if plan.is_active else "مُعطَّلة ⏸"

        try:
            db.session.commit()
            flash(
                f"خطة '{plan.plan_name}' أصبحت الآن {new_state_ar}.",
                "success" if plan.is_active else "warning",
            )
        except Exception as exc:
            db.session.rollback()
            app.logger.error(f"toggle_plan error for plan {plan_id}: {exc}")
            flash("حدث خطأ أثناء تعديل حالة الخطة.", "danger")

        return redirect(url_for("plans"))