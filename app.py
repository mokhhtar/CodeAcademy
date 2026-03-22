# =============================================================================
#  app.py  —  Flask Application Factory  (Authentication update)
#  Project : أكاديمية شيفرة  (Shyfra Academy)
#
#  CHANGES IN THIS VERSION
#  ───────────────────────
#  • LoginManager fully wired (login_view, user_loader, login_message)
#  • GET  /login   → renders login.html
#  • POST /login   → validates credentials → login_user() or flash error
#  • GET  /logout  → logout_user() + redirect to login
#  • GET  /        and GET /dashboard protected with @login_required
#  • Role-aware redirect after login (Admin/Supervisor → dashboard,
#    Member → member dashboard — placeholder for now)
# =============================================================================

import os
import uuid
from datetime import date, timedelta

from flask import (
    Flask,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import (
    LoginManager,
    current_user,
    login_required,
    login_user,
    logout_user,
)
from sqlalchemy import and_, func

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
    UserStatusEnum,
    db,
)
from payment_routes import _register_payment_routes
from enrollment_routes import _register_enrollment_routes
from subscriptions_routes import _register_subscription_routes
from receipt_routes import _register_receipt_routes
from list_routes import _register_list_routes
from certificate_routes import _register_certificate_routes
from groups_routes import _register_group_routes
from plans_routes import _register_plan_routes
from users_routes import _register_user_routes
from profile_and_errors import _register_profile_routes
from role_dashboard import _register_role_dashboard_routes


# ─────────────────────────────────────────────────────────────────────────────
#  LoginManager — created once, initialised inside the factory
# ─────────────────────────────────────────────────────────────────────────────
login_manager = LoginManager()


# ─────────────────────────────────────────────────────────────────────────────
#  Application Factory
# ─────────────────────────────────────────────────────────────────────────────

def create_app(config_name: str = "development") -> Flask:
    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static",
    )

    _configure(app, config_name)
    db.init_app(app)
    _init_login_manager(app)
    _register_auth_routes(app)
    _register_role_dashboard_routes(app)
    _register_payment_routes(app)
    _register_enrollment_routes(app)
    _register_subscription_routes(app)
    _register_receipt_routes(app)
    _register_list_routes(app)
    _register_certificate_routes(app)
    _register_group_routes(app)
    _register_plan_routes(app)
    _register_user_routes(app)
    _register_profile_routes(app)
    _register_core_routes(app)

    with app.app_context():
        db.create_all()
        _seed_demo_data()

    return app


# ─────────────────────────────────────────────────────────────────────────────
#  Configuration
# ─────────────────────────────────────────────────────────────────────────────

class Config:
    SECRET_KEY                     = os.environ.get("SECRET_KEY", "dev-secret-CHANGE-in-production!")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SESSION_COOKIE_HTTPONLY        = True
    SESSION_COOKIE_SAMESITE        = "Lax"
    REMEMBER_COOKIE_DURATION       = 60 * 60 * 24 * 14   # 14 days


class DevelopmentConfig(Config):
    DEBUG                   = True
    SQLALCHEMY_DATABASE_URI = "mysql+pymysql://root:mysql2003@localhost/shyfra_academy"
    SQLALCHEMY_ECHO         = False   # set True to log SQL to console


class ProductionConfig(Config):
    DEBUG                   = False
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", "mysql+pymysql://user:password@localhost/shyfra_academy"
    )
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_recycle": 1800, "pool_pre_ping": True}
    SESSION_COOKIE_SECURE     = True


class TestingConfig(Config):
    TESTING                 = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    WTF_CSRF_ENABLED        = False


_CONFIG_MAP = {
    "development": DevelopmentConfig,
    "production":  ProductionConfig,
    "testing":     TestingConfig,
}


def _configure(app: Flask, config_name: str) -> None:
    app.config.from_object(_CONFIG_MAP.get(config_name, DevelopmentConfig))


# ─────────────────────────────────────────────────────────────────────────────
#  Flask-Login Initialisation
# ─────────────────────────────────────────────────────────────────────────────

def _init_login_manager(app: Flask) -> None:
    """
    Attach LoginManager to the app and configure its behaviour.

    login_view     → the endpoint name Flask redirects to when
                     @login_required fails. Must match the GET /login route.
    login_message  → flashed message shown on that redirect.
    user_loader    → callback that reconstructs the User object from the
                     user_id stored in the encrypted session cookie.
    """
    login_manager.init_app(app)

    # Redirect unauthenticated requests here
    login_manager.login_view         = "login"
    login_manager.login_message      = "يرجى تسجيل الدخول للوصول إلى هذه الصفحة."
    login_manager.login_message_category = "warning"

    # "Remember me" cookie name (cosmetic — avoids fingerprinting defaults)
    login_manager.remember_cookie_name = "shyfra_remember"

    @login_manager.user_loader
    def load_user(user_id: str) -> User | None:
        """
        Called on EVERY request that has a session cookie.
        Must return the User object or None (never raise an exception).
        db.session.get() is preferred over .query.get() in SQLAlchemy 2.x.
        """
        try:
            return db.session.get(User, int(user_id))
        except (ValueError, TypeError):
            return None

    @login_manager.unauthorized_handler
    def unauthorized():
        """Custom handler so we can flash a specific message."""
        flash("يجب تسجيل الدخول أولاً للوصول إلى هذه الصفحة.", "warning")
        return redirect(url_for("login"))


# ─────────────────────────────────────────────────────────────────────────────
#  Authentication Routes
# ─────────────────────────────────────────────────────────────────────────────

def _register_auth_routes(app: Flask) -> None:

    # ── GET /login  ──────────────────────────────────────────────────────────
    @app.route("/login", methods=["GET"])
    def login():
        """
        Render the login page.
        If the user is already authenticated, skip the form and go to dashboard.
        """
        if current_user.is_authenticated:
            return redirect(url_for("dashboard"))
        return render_template("login.html")

    # ── POST /login  ─────────────────────────────────────────────────────────
    @app.route("/login", methods=["POST"])
    def login_post():
        """
        Process the submitted login form.

        Security notes
        ──────────────
        • We use a GENERIC error message ("بيانات الدخول غير صحيحة") regardless
          of whether the email doesn't exist or the password is wrong. This
          prevents user-enumeration attacks.
        • check_password() uses constant-time comparison internally (Werkzeug).
        • login_user() rejects users whose is_active == False (Inactive status).
        • The `remember` checkbox creates a persistent cookie.
        """
        email    = request.form.get("email",    "").strip().lower()
        password = request.form.get("password", "").strip()
        remember = bool(request.form.get("remember"))

        # ── Basic presence check ──────────────────────────────────────────
        if not email or not password:
            flash("يرجى إدخال البريد الإلكتروني وكلمة المرور.", "danger")
            return redirect(url_for("login"))

        # ── Lookup user (filter by lowercased email) ──────────────────────
        user: User | None = User.query.filter_by(email=email).first()

        # ── Validate (single generic error to prevent enumeration) ────────
        if user is None or not user.check_password(password):
            flash("بيانات الدخول غير صحيحة. يرجى المحاولة مجدداً.", "danger")
            return redirect(url_for("login"))

        # ── Inactive account check ─────────────────────────────────────────
        # login_user() will silently fail if is_active == False, so we add
        # an explicit check to give the user a meaningful message.
        if not user.is_active:
            flash("حسابك معطّل. يرجى التواصل مع المسؤول.", "warning")
            return redirect(url_for("login"))

        # ── Authenticate ───────────────────────────────────────────────────
        login_user(user, remember=remember)

        # ── Role-aware redirect ────────────────────────────────────────────
        # Honour the "next" parameter Flask-Login appends when redirecting
        # to the login page (e.g. /login?next=%2Fdashboard).
        # We validate it to prevent open-redirect attacks.
        next_page = request.args.get("next")
        if next_page and next_page.startswith("/"):
            return redirect(next_page)

        # Admins & Supervisors → main dashboard
        # Members → member panel (placeholder: dashboard for now)
        if user.is_member:
            flash(f"مرحباً {user.fname}! تسجيل الدخول ناجح.", "success")
            return redirect(url_for("dashboard"))   # swap for member_dashboard later

        flash(f"مرحباً {user.full_name}! تسجيل الدخول ناجح.", "success")
        return redirect(url_for("dashboard"))

    # ── GET /logout  ─────────────────────────────────────────────────────────
    @app.route("/logout")
    @login_required
    def logout():
        """
        Terminate the user session.
        logout_user() clears the session and removes the remember-me cookie.
        """
        user_name = current_user.fname   # capture before logout clears the proxy
        logout_user()
        flash(f"تم تسجيل خروج {user_name} بنجاح. إلى اللقاء!", "info")
        return redirect(url_for("login"))





# ─────────────────────────────────────────────────────────────────────────────
#  Core / Utility Routes
# ─────────────────────────────────────────────────────────────────────────────

def _register_core_routes(app: Flask) -> None:

    @app.route("/health")
    def health_check():
        return jsonify(status="ok", app="أكاديمية شيفرة", version="1.0.0"), 200

    @app.route("/db-stats")
    @login_required
    def db_stats():
        """Developer stats endpoint — remove or gate behind admin check in prod."""
        return jsonify({
            "users":               User.query.count(),
            "groups":              Group.query.count(),
            "subscriptions":       Subscription.query.count(),
            "active_subscriptions": Subscription.query.filter_by(
                                       status=SubscriptionStatusEnum.Active).count(),
            "payment_receipts":    PaymentReceipt.query.count(),
            "certificates":        Certificate.query.count(),
        }), 200

    @app.errorhandler(404)
    def not_found(e):
        return render_template("errors/404.html"), 404   # create if needed

    @app.errorhandler(403)
    def forbidden(e):
        flash("ليس لديك صلاحية للوصول إلى هذه الصفحة.", "danger")
        return redirect(url_for("dashboard"))

    @app.errorhandler(500)
    def server_error(e):
        app.logger.error(f"500 error: {e}")
        return jsonify(error="خطأ داخلي في الخادم — 500"), 500


# ─────────────────────────────────────────────────────────────────────────────
#  Demo Data Seeder
# ─────────────────────────────────────────────────────────────────────────────

def _seed_demo_data() -> None:
    """Insert realistic Arabic demo data on first run. Idempotent."""
    if User.query.first() is not None:
        return

    print("📦  Seeding demo data …")
    try:
        admin = User(fname="أحمد", lname="الزهراني", email="admin@shyfra.dz", role=RoleEnum.Admin)
        admin.set_password("Password@123")

        sup1 = User(fname="سارة",  lname="بن عيسى", email="sara.supervisor@shyfra.dz",   role=RoleEnum.Supervisor)
        sup2 = User(fname="يوسف", lname="حمزاوي",   email="youssef.supervisor@shyfra.dz", role=RoleEnum.Supervisor)
        sup1.set_password("Password@123")
        sup2.set_password("Password@123")

        members_data = [
            ("ليلى",  "مسعود",   "leila@gmail.com",  UserStatusEnum.Active),
            ("كريم",  "بوعلام",  "karim@gmail.com",  UserStatusEnum.Active),
            ("إيمان", "قادري",   "iman@gmail.com",   UserStatusEnum.Active),
            ("رضا",   "عمروش",   "redha@gmail.com",  UserStatusEnum.Inactive),
            ("نور",   "براهيمي", "nour@gmail.com",   UserStatusEnum.Active),
        ]
        members = []
        for fname, lname, email, status in members_data:
            u = User(fname=fname, lname=lname, email=email,
                     role=RoleEnum.Member, status=status)
            u.set_password("Password@123")
            members.append(u)

        leila, karim, iman, redha, nour = members
        db.session.add_all([admin, sup1, sup2, *members])
        db.session.flush()

        g_python = Group(group_name="بايثون التأسيسي — الدفعة الأولى",
                         description="مسار بايثون من الصفر.",     supervisor_id=sup1.user_id)
        g_web    = Group(group_name="تطوير الويب الكامل — الدفعة الأولى",
                         description="HTML · CSS · JS · Flask.",  supervisor_id=sup2.user_id)
        db.session.add_all([g_python, g_web])
        db.session.flush()

        db.session.add_all([
            GroupMember(group_id=g_python.group_id, member_id=leila.user_id,  joined_date=date(2024, 9, 5)),
            GroupMember(group_id=g_python.group_id, member_id=karim.user_id,  joined_date=date(2024, 9, 5)),
            GroupMember(group_id=g_python.group_id, member_id=iman.user_id,   joined_date=date(2024, 9, 10)),
            GroupMember(group_id=g_web.group_id,    member_id=iman.user_id,   joined_date=date(2024, 10, 3)),
            GroupMember(group_id=g_web.group_id,    member_id=redha.user_id,  joined_date=date(2024, 10, 3)),
            GroupMember(group_id=g_web.group_id,    member_id=nour.user_id,   joined_date=date(2024, 10, 5)),
        ])

        plan_m = SubscriptionPlan(plan_name="شهري",  duration_months=1,  price=1500.00)
        plan_y = SubscriptionPlan(plan_name="سنوي",  duration_months=12, price=15000.00)
        db.session.add_all([plan_m, plan_y])
        db.session.flush()

        subs = [
            Subscription(member_id=leila.user_id,  plan_id=plan_m.plan_id,
                         start_date=date(2025, 3, 1),  end_date=date(2026, 3, 13),
                         status=SubscriptionStatusEnum.Active),
            Subscription(member_id=karim.user_id,  plan_id=plan_y.plan_id,
                         start_date=date(2025, 1, 15), end_date=date(2026, 1, 15),
                         status=SubscriptionStatusEnum.Active),
            Subscription(member_id=iman.user_id,   plan_id=plan_m.plan_id,
                         start_date=date(2025, 1, 1),  end_date=date(2026, 3, 1),
                         status=SubscriptionStatusEnum.Active),
            Subscription(member_id=iman.user_id,   plan_id=plan_y.plan_id,
                         start_date=date(2024, 10, 3), end_date=date(2025, 10, 3),
                         status=SubscriptionStatusEnum.Expired),
            Subscription(member_id=redha.user_id,  plan_id=plan_m.plan_id,
                         start_date=date(2024, 10, 3), end_date=date(2024, 11, 3),
                         status=SubscriptionStatusEnum.Canceled),
            Subscription(member_id=nour.user_id,   plan_id=plan_m.plan_id,
                         start_date=date(2025, 2, 1),  end_date=date(2026, 3, 1),
                         status=SubscriptionStatusEnum.Suspended),
            Subscription(member_id=leila.user_id,  plan_id=plan_y.plan_id,
                         start_date=date(2023, 9, 1),  end_date=date(2024, 9, 1),
                         status=SubscriptionStatusEnum.Expired),
        ]
        db.session.add_all(subs)
        db.session.flush()

        s0, s1, s2, s3, s4, s5, s6 = subs
        db.session.add_all([
            PaymentReceipt(subscription_id=s0.subscription_id, amount_paid=1500.00,
                           payment_date=date(2025, 3, 1),  payment_type=PaymentTypeEnum.New,     notes="نقداً"),
            PaymentReceipt(subscription_id=s1.subscription_id, amount_paid=15000.00,
                           payment_date=date(2025, 1, 15), payment_type=PaymentTypeEnum.New,     notes="CCP"),
            PaymentReceipt(subscription_id=s2.subscription_id, amount_paid=1500.00,
                           payment_date=date(2025, 1, 1),  payment_type=PaymentTypeEnum.New,     notes="نقداً"),
            PaymentReceipt(subscription_id=s2.subscription_id, amount_paid=1500.00,
                           payment_date=date(2025, 2, 3),  payment_type=PaymentTypeEnum.Renewal, notes="تجديد فبراير"),
            PaymentReceipt(subscription_id=s2.subscription_id, amount_paid=1500.00,
                           payment_date=date(2025, 3, 4),  payment_type=PaymentTypeEnum.Renewal, notes="تجديد مارس"),
            PaymentReceipt(subscription_id=s3.subscription_id, amount_paid=15000.00,
                           payment_date=date(2024, 10, 3), payment_type=PaymentTypeEnum.New,     notes="Baridimob"),
            PaymentReceipt(subscription_id=s4.subscription_id, amount_paid=1500.00,
                           payment_date=date(2024, 10, 3), payment_type=PaymentTypeEnum.New,     notes="ملغى"),
            PaymentReceipt(subscription_id=s5.subscription_id, amount_paid=1500.00,
                           payment_date=date(2025, 2, 1),  payment_type=PaymentTypeEnum.New,     notes="معلّق"),
            PaymentReceipt(subscription_id=s6.subscription_id, amount_paid=15000.00,
                           payment_date=date(2023, 9, 1),  payment_type=PaymentTypeEnum.New,     notes="سنوي قديم"),
        ])

        db.session.add_all([
            Certificate(member_id=karim.user_id, group_id=g_python.group_id,
                        issued_by=sup1.user_id, issue_date=date(2025, 2, 28),
                        certificate_code=f"CERT-PY-2025-001-KRM-{uuid.uuid4().hex[:8].upper()}"),
            Certificate(member_id=iman.user_id,  group_id=g_web.group_id,
                        issued_by=sup2.user_id, issue_date=date(2025, 3, 1),
                        certificate_code=f"CERT-WB-2025-001-IMN-{uuid.uuid4().hex[:8].upper()}"),
        ])

        db.session.commit()
        print("✅  Demo data seeded — login: admin@shyfra.dz / Password@123")

    except Exception as exc:
        db.session.rollback()
        print(f"❌  Seeding failed: {exc}")
        raise


# ─────────────────────────────────────────────────────────────────────────────
#  Entry Point
# ─────────────────────────────────────────────────────────────────────────────
_env = os.environ.get("APP_ENV", "development")
app  = create_app(_env)

if __name__ == "__main__":
    app.run(
        host  = "0.0.0.0",
        port  = int(os.environ.get("PORT", 5000)),
        debug = app.config.get("DEBUG", False),
    )