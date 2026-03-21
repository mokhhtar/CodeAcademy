# =============================================================================
#  certificate_routes.py  —  Route snippet to integrate into app.py
#  Project : أكاديمية شيفرة  (Shyfra Academy)
# =============================================================================

from flask import abort, flash, redirect, render_template, url_for
from flask_login import current_user, login_required

from models import (
    Certificate,
    RoleEnum,
    db,
)


def _register_certificate_routes(app) -> None:
    """Register certificate routes onto the Flask app instance."""

    # =========================================================================
    #  GET /certificate/<cert_id>/print
    # =========================================================================

    @app.route("/certificate/<int:cert_id>/print", methods=["GET"])
    @login_required
    def print_certificate(cert_id: int):
        """
        Render a single, printable certificate page.
        """
        # Fetch certificate
        certificate = db.session.get(Certificate, cert_id)
        if certificate is None:
            abort(404)

        # Access control
        if current_user.role == RoleEnum.Member and current_user.user_id != certificate.member_id:
            flash("ليس لديك صلاحية لطباعة هذه الشهادة.", "danger")
            return redirect(url_for("certificates"))
            
        return render_template(
            "print_certificate.html",
            certificate = certificate,
            member      = certificate.member,
            group       = certificate.group,
            issuer      = certificate.issuer,
        )
