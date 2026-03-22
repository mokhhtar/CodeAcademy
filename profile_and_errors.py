# =============================================================================
#  profile_and_errors.py  —  Route snippet to integrate into app.py
#  Project : أكاديمية شيفرة  (Shyfra Academy)
#
#  Add _register_profile_routes(app) inside create_app():
#
#      ...
#      _register_plan_routes(app)
#      _register_profile_routes(app)         ← add this line
#      _register_core_routes(app)            ← keep this last
#
#  Error handlers are registered inside _register_profile_routes as well
#  (or move them to _register_core_routes — either location works).
# =============================================================================

from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from models import db


def _register_profile_routes(app) -> None:
    """Register the profile routes and global error handlers."""

    # =========================================================================
    #  1a.  GET /profile
    #       Render the user's profile page — shows account info and the
    #       change-password form.
    # =========================================================================

    @app.route("/profile", methods=["GET"])
    @login_required
    def profile():
        """
        Render the personal profile page for the currently logged-in user.

        Template variables
        ──────────────────
        user    current_user  (User ORM object — already available via
                               Flask-Login's proxy, but passed explicitly
                               so the template doesn't need to import it)
        """
        return render_template("profile.html", user=current_user)


    # =========================================================================
    #  1b.  POST /profile/change_password
    #       Verify the current password then hash and save the new one.
    #
    #       Security notes
    #       ──────────────
    #       • current_password is verified with check_password() which uses
    #         Werkzeug's constant-time comparison — safe against timing attacks.
    #       • new_password is never stored in plain text; set_password() calls
    #         generate_password_hash() before assignment.
    #       • We do NOT re-login the user after the change (the session cookie
    #         remains valid) — acceptable for this project scope.
    # =========================================================================

    @app.route("/profile/change_password", methods=["POST"])
    @login_required
    def change_password():
        """
        Handle the change-password form submission.

        Form fields
        ───────────
        current_password  : str  (must match the stored hash)
        new_password      : str  (will be hashed before saving)
        confirm_password  : str  (must equal new_password)
        """

        current_pw = request.form.get("current_password", "").strip()
        new_pw     = request.form.get("new_password",     "").strip()
        confirm_pw = request.form.get("confirm_password", "").strip()

        # ── Presence check ────────────────────────────────────────────────
        if not current_pw or not new_pw or not confirm_pw:
            flash("جميع حقول كلمة المرور مطلوبة.", "danger")
            return redirect(url_for("profile"))

        # ── Verify current password ────────────────────────────────────────
        if not current_user.check_password(current_pw):
            flash("كلمة المرور الحالية غير صحيحة.", "danger")
            return redirect(url_for("profile"))

        # ── New password must differ from current ──────────────────────────
        if new_pw == current_pw:
            flash("كلمة المرور الجديدة يجب أن تختلف عن الحالية.", "warning")
            return redirect(url_for("profile"))

        # ── Confirmation match ─────────────────────────────────────────────
        if new_pw != confirm_pw:
            flash("كلمة المرور الجديدة وتأكيدها غير متطابقتين.", "danger")
            return redirect(url_for("profile"))

        # ── Minimum length ────────────────────────────────────────────────
        if len(new_pw) < 8:
            flash("كلمة المرور الجديدة يجب أن تكون 8 أحرف على الأقل.", "danger")
            return redirect(url_for("profile"))

        # ── Hash and persist ──────────────────────────────────────────────
        try:
            current_user.set_password(new_pw)
            db.session.commit()
            flash("تم تغيير كلمة المرور بنجاح. ✅", "success")
        except Exception as exc:
            db.session.rollback()
            app.logger.error(f"change_password error for user "
                             f"{current_user.user_id}: {exc}")
            flash("حدث خطأ أثناء حفظ كلمة المرور. يرجى المحاولة مجدداً.", "danger")

        return redirect(url_for("profile"))


    # =========================================================================
    #  2.  Custom Error Handlers
    #      Render dedicated error pages instead of Flask's plain-text defaults.
    #      Templates live in templates/errors/.
    # =========================================================================

    @app.errorhandler(404)
    def not_found(error):
        """
        Handle 404 Not Found.
        Triggered when no route matches the requested URL.
        """
        app.logger.info(f"404 — {request.url}")
        return render_template("errors/404.html"), 404

    @app.errorhandler(500)
    def internal_error(error):
        """
        Handle 500 Internal Server Error.
        Roll back any open DB transaction to leave the session in a clean state
        before rendering the error page.
        """
        db.session.rollback()   # prevent "transaction already aborted" cascades
        app.logger.error(f"500 — {request.url} — {error}")
        return render_template("errors/500.html"), 500

    @app.errorhandler(403)
    def forbidden(error):
        """
        Handle 403 Forbidden.
        Triggered by @admin_required / role guards that call abort(403).
        """
        app.logger.warning(f"403 — {request.url} — user {current_user.get_id()}")
        return render_template("errors/403.html"), 403