# =============================================================================
#  certificate_routes.py  —  Route snippet to integrate into app.py
#  Project : أكاديمية شيفرة  (Shyfra Academy)
# =============================================================================

import uuid
from datetime import date

from flask import abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from models import (
    Certificate,
    Group,
    GroupMember,
    RoleEnum,
    User,
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
        """Render a single, printable certificate page."""
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

    # =========================================================================
    #  POST /certificates/issue
    #  إصدار شهادة جديدة بواسطة المدير أو المشرف
    #
    #  صلاحيات
    #  ────────
    #  Admin      : يمكنه إصدار شهادة لأي طالب في أي مسار.
    #  Supervisor : يمكنه إصدار شهادة فقط للطلاب في مساراته.
    #  Member     : ممنوع.
    #
    #  شروط الإصدار
    #  ─────────────
    #  • يجب أن يكون الطالب مسجّلاً في المسار المحدد (GroupMember).
    #  • إذا كان المُصدِر مشرفاً، يجب أن يخصّه المسار.
    # =========================================================================

    @app.route("/certificates/issue", methods=["POST"])
    @login_required
    def issue_certificate():
        """Issue a new certificate for a student enrolled in a group."""

        # ── Role guard ────────────────────────────────────────────────────
        if current_user.is_member:
            flash("إصدار الشهادات مخصص للإدارة والمشرفين فقط.", "danger")
            return redirect(url_for("certificates"))

        # ── Receive and cast form data ────────────────────────────────────
        member_id = request.form.get("member_id", type=int)
        group_id  = request.form.get("group_id",  type=int)

        if not member_id or not group_id:
            flash("يرجى اختيار الطالب والمسار.", "warning")
            return redirect(url_for("certificates"))

        # ── Validate member exists and is actually a student ──────────────
        member = db.session.get(User, member_id)
        if not member or not member.is_member:
            flash("الطالب المحدد غير صالح أو غير موجود.", "danger")
            return redirect(url_for("certificates"))

        # ── Validate group exists ─────────────────────────────────────────
        group = db.session.get(Group, group_id)
        if not group:
            flash("المسار المحدد غير موجود.", "danger")
            return redirect(url_for("certificates"))

        # ── Supervisor: ensure the group belongs to them ──────────────────
        if current_user.is_supervisor and group.supervisor_id != current_user.user_id:
            flash("لا يمكنك إصدار شهادة لمسار لا تشرف عليه.", "danger")
            return redirect(url_for("certificates"))

        # ── Ensure the student is enrolled in this group ──────────────────
        enrollment = GroupMember.query.filter_by(
            group_id=group_id, member_id=member_id
        ).first()

        if not enrollment:
            flash(
                f"الطالب {member.full_name} غير مسجّل في المسار '{group.group_name}'.",
                "danger",
            )
            return redirect(url_for("certificates"))

        # ── Generate a unique certificate code (ASCII Alphanumeric) ────────
        today = date.today()
        # Format: CERT-G<groupID>-<YEAR>-M<memberID>-<8HEX>
        cert_code = (
            f"CERT-G{group.group_id}-{today.year}-M{member.user_id}-"
            f"{uuid.uuid4().hex[:8].upper()}"
        )

        # ── Create the certificate record ─────────────────────────────────
        try:
            cert = Certificate(
                member_id        = member.user_id,
                group_id         = group.group_id,
                issued_by        = current_user.user_id,
                issue_date       = today,
                certificate_code = cert_code,
            )
            db.session.add(cert)
            db.session.commit()

            flash(
                f"✅ تم إصدار شهادة بنجاح للطالب {member.full_name} "
                f"في مسار '{group.group_name}'. "
                f"كود الشهادة: {cert_code}",
                "success",
            )

        except Exception as exc:
            db.session.rollback()
            app.logger.error(f"Certificate issuance failed: {exc}")
            flash("حدث خطأ أثناء إصدار الشهادة. يرجى المحاولة مجدداً.", "danger")

        return redirect(url_for("certificates"))

