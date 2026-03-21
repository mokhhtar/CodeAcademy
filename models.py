# =============================================================================
#  models.py  —  SQLAlchemy ORM Models  (Authentication update)
#  Project   : أكاديمية شيفرة  (Shyfra Academy)
#
#  CHANGES IN THIS VERSION
#  ───────────────────────
#  • User now inherits from flask_login.UserMixin
#    Provides: is_authenticated, is_active, is_anonymous, get_id()
#  • is_active is OVERRIDDEN to respect our status column (Inactive = blocked)
#  • get_id() explicitly returns str(user_id) — Flask-Login contract
#  • All other models are unchanged.
# =============================================================================
 
import enum
from datetime import date, datetime
 
from flask_login import UserMixin                          # ← NEW
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import check_password_hash, generate_password_hash
 
db = SQLAlchemy()
 
 
# ══════════════════════════════════════════════════════════════════════════════
#  Python Enums  (mirror MySQL ENUM columns exactly)
# ══════════════════════════════════════════════════════════════════════════════
 
class RoleEnum(enum.Enum):
    Admin      = "Admin"
    Supervisor = "Supervisor"
    Member     = "Member"
 
 
class UserStatusEnum(enum.Enum):
    Active   = "Active"
    Inactive = "Inactive"
 
 
class SubscriptionStatusEnum(enum.Enum):
    Active    = "Active"
    Expired   = "Expired"
    Suspended = "Suspended"
    Canceled  = "Canceled"
 
 
class PaymentTypeEnum(enum.Enum):
    New     = "New"
    Renewal = "Renewal"
 
 
# ══════════════════════════════════════════════════════════════════════════════
#  1.  User  ← NOW inherits UserMixin for Flask-Login compatibility
# ══════════════════════════════════════════════════════════════════════════════
 
class User(UserMixin, db.Model):           # UserMixin MUST come before db.Model
    """
    Unified user table for Admin / Supervisor / Member.
 
    Flask-Login integration (via UserMixin)
    ───────────────────────────────────────
    UserMixin supplies four default properties Flask-Login requires:
 
        is_authenticated  → True  (only loaded for logged-in sessions)
        is_active         → OVERRIDDEN — respects our status column
        is_anonymous      → False
        get_id()          → OVERRIDDEN — returns str(user_id)
 
    Inactive accounts will fail the is_active check inside login_user()
    and will be rejected even if they supply the correct password.
    """
 
    __tablename__ = "Users"
 
    # ── Columns ────────────────────────────────────────────────────────────
    user_id       = db.Column(db.Integer,     primary_key=True, autoincrement=True)
    fname         = db.Column(db.String(60),  nullable=False,   comment="الاسم الأول")
    lname         = db.Column(db.String(60),  nullable=False,   comment="اسم العائلة")
    email         = db.Column(db.String(150), nullable=False,   unique=True, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role          = db.Column(db.Enum(RoleEnum),       nullable=False,
                              default=RoleEnum.Member, index=True)
    status        = db.Column(db.Enum(UserStatusEnum), nullable=False,
                              default=UserStatusEnum.Active, index=True)
    created_at    = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
 
    # ── Relationships ───────────────────────────────────────────────────────
    supervised_groups = db.relationship(
        "Group", back_populates="supervisor",
        foreign_keys="Group.supervisor_id", lazy="dynamic",
    )
    group_memberships = db.relationship(
        "GroupMember", back_populates="member",
        cascade="all, delete-orphan", lazy="dynamic",
    )
    subscriptions = db.relationship(
        "Subscription", back_populates="member",
        cascade="all, delete-orphan", lazy="dynamic",
    )
    certificates = db.relationship(
        "Certificate", back_populates="member",
        foreign_keys="Certificate.member_id",
        cascade="all, delete-orphan", lazy="dynamic",
    )
    issued_certificates = db.relationship(
        "Certificate", back_populates="issuer",
        foreign_keys="Certificate.issued_by", lazy="dynamic",
    )
 
    # ── Flask-Login overrides ───────────────────────────────────────────────
 
    @property
    def is_active(self) -> bool:
        """
        Flask-Login calls this before completing login_user().
        We map our status column: Active → True, Inactive → False.
        Inactive users are blocked at the login layer, not just the UI.
        """
        return self.status == UserStatusEnum.Active
 
    def get_id(self) -> str:
        """
        Flask-Login stores this value in the session cookie and passes it
        back to @login_manager.user_loader on every request.
        Must return a unicode string, not an integer.
        """
        return str(self.user_id)
 
    # ── Password helpers ────────────────────────────────────────────────────
 
    def set_password(self, plain_password: str) -> None:
        """Hash and store password using Werkzeug (pbkdf2:sha256)."""
        self.password_hash = generate_password_hash(plain_password)
 
    def check_password(self, plain_password: str) -> bool:
        """Return True if plain_password matches the stored hash."""
        return check_password_hash(self.password_hash, plain_password)
 
    # ── Convenience properties ──────────────────────────────────────────────
 
    @property
    def full_name(self) -> str:
        return f"{self.fname} {self.lname}"
 
    @property
    def is_admin(self) -> bool:
        return self.role == RoleEnum.Admin
 
    @property
    def is_supervisor(self) -> bool:
        return self.role == RoleEnum.Supervisor
 
    @property
    def is_member(self) -> bool:
        return self.role == RoleEnum.Member
 
    def __repr__(self) -> str:
        return f"<User id={self.user_id} email={self.email} role={self.role.value}>"
 
 
# ══════════════════════════════════════════════════════════════════════════════
#  2.  Group
# ══════════════════════════════════════════════════════════════════════════════
 
class Group(db.Model):
    __tablename__ = "Groups"
 
    group_id      = db.Column(db.Integer,     primary_key=True, autoincrement=True)
    group_name    = db.Column(db.String(150), nullable=False)
    description   = db.Column(db.Text,        nullable=True)
    supervisor_id = db.Column(
        db.Integer,
        db.ForeignKey("Users.user_id", onupdate="CASCADE", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
 
    supervisor   = db.relationship("User", back_populates="supervised_groups",
                                   foreign_keys=[supervisor_id])
    member_links = db.relationship("GroupMember", back_populates="group",
                                   cascade="all, delete-orphan", lazy="dynamic")
    certificates = db.relationship("Certificate", back_populates="group",
                                   cascade="all, delete-orphan", lazy="dynamic")
 
    @property
    def member_count(self) -> int:
        return self.member_links.count()
 
    def __repr__(self) -> str:
        return f"<Group id={self.group_id} name={self.group_name}>"
 
 
# ══════════════════════════════════════════════════════════════════════════════
#  3.  GroupMember  (junction table)
# ══════════════════════════════════════════════════════════════════════════════
 
class GroupMember(db.Model):
    __tablename__ = "Group_Members"
    __table_args__ = (
        db.UniqueConstraint("group_id", "member_id", name="uq_group_member"),
    )
 
    id          = db.Column(db.Integer, primary_key=True, autoincrement=True)
    group_id    = db.Column(db.Integer,
                            db.ForeignKey("Groups.group_id",
                                          onupdate="CASCADE", ondelete="CASCADE"),
                            nullable=False)
    member_id   = db.Column(db.Integer,
                            db.ForeignKey("Users.user_id",
                                          onupdate="CASCADE", ondelete="CASCADE"),
                            nullable=False, index=True)
    joined_date = db.Column(db.Date, nullable=False, default=date.today)
 
    group  = db.relationship("Group", back_populates="member_links")
    member = db.relationship("User",  back_populates="group_memberships")
 
    def __repr__(self) -> str:
        return f"<GroupMember group={self.group_id} member={self.member_id}>"
 
 
# ══════════════════════════════════════════════════════════════════════════════
#  4.  SubscriptionPlan
# ══════════════════════════════════════════════════════════════════════════════
 
class SubscriptionPlan(db.Model):
    __tablename__ = "Subscription_Plans"
 
    plan_id         = db.Column(db.Integer,        primary_key=True, autoincrement=True)
    plan_name       = db.Column(db.String(80),     nullable=False, unique=True)
    duration_months = db.Column(db.Integer,        nullable=False)
    price           = db.Column(db.Numeric(10, 2), nullable=False)
    is_active       = db.Column(db.Boolean,        nullable=False, default=True)
 
    subscriptions = db.relationship("Subscription", back_populates="plan", lazy="dynamic")
 
    def __repr__(self) -> str:
        return f"<SubscriptionPlan id={self.plan_id} name={self.plan_name}>"
 
 
# ══════════════════════════════════════════════════════════════════════════════
#  5.  Subscription
# ══════════════════════════════════════════════════════════════════════════════
 
class Subscription(db.Model):
    __tablename__ = "Subscriptions"
 
    subscription_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    member_id       = db.Column(db.Integer,
                                db.ForeignKey("Users.user_id",
                                              onupdate="CASCADE", ondelete="CASCADE"),
                                nullable=False, index=True)
    plan_id         = db.Column(db.Integer,
                                db.ForeignKey("Subscription_Plans.plan_id",
                                              onupdate="CASCADE", ondelete="RESTRICT"),
                                nullable=False)
    start_date = db.Column(db.Date, nullable=False)
    end_date   = db.Column(db.Date, nullable=False, index=True)
    status     = db.Column(db.Enum(SubscriptionStatusEnum), nullable=False,
                           default=SubscriptionStatusEnum.Active, index=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
 
    member   = db.relationship("User",             back_populates="subscriptions")
    plan     = db.relationship("SubscriptionPlan", back_populates="subscriptions")
    receipts = db.relationship("PaymentReceipt", back_populates="subscription",
                               cascade="all, delete-orphan", lazy="dynamic",
                               order_by="PaymentReceipt.payment_date")
 
    @property
    def days_remaining(self) -> int:
        return (self.end_date - date.today()).days
 
    @property
    def is_expiring_soon(self) -> bool:
        return self.status == SubscriptionStatusEnum.Active and 0 <= self.days_remaining <= 5
 
    @property
    def alert_level(self) -> str:
        if self.days_remaining <= 5:
            return "danger"
        if self.days_remaining <= 15:
            return "warning"
        return "success"
 
    def __repr__(self) -> str:
        return f"<Subscription id={self.subscription_id} status={self.status.value}>"
 
 
# ══════════════════════════════════════════════════════════════════════════════
#  6.  PaymentReceipt
# ══════════════════════════════════════════════════════════════════════════════
 
class PaymentReceipt(db.Model):
    __tablename__ = "Payments_Receipts"
 
    receipt_id      = db.Column(db.Integer,        primary_key=True, autoincrement=True)
    subscription_id = db.Column(db.Integer,
                                db.ForeignKey("Subscriptions.subscription_id",
                                              onupdate="CASCADE", ondelete="CASCADE"),
                                nullable=False, index=True)
    amount_paid  = db.Column(db.Numeric(10, 2), nullable=False)
    payment_date = db.Column(db.Date,           nullable=False, default=date.today, index=True)
    payment_type = db.Column(db.Enum(PaymentTypeEnum), nullable=False,
                             default=PaymentTypeEnum.New)
    notes        = db.Column(db.String(255), nullable=True)
    created_at   = db.Column(db.DateTime,    nullable=False, default=datetime.utcnow)
 
    subscription = db.relationship("Subscription", back_populates="receipts")
 
    @property
    def receipt_number(self) -> str:
        return f"REC-{self.receipt_id:05d}"
 
    def __repr__(self) -> str:
        return f"<PaymentReceipt id={self.receipt_id} type={self.payment_type.value}>"
 
 
# ══════════════════════════════════════════════════════════════════════════════
#  7.  Certificate
# ══════════════════════════════════════════════════════════════════════════════
 
class Certificate(db.Model):
    __tablename__ = "Certificates"
 
    certificate_id   = db.Column(db.Integer,    primary_key=True, autoincrement=True)
    member_id        = db.Column(db.Integer,
                                 db.ForeignKey("Users.user_id",
                                               onupdate="CASCADE", ondelete="CASCADE"),
                                 nullable=False, index=True)
    group_id         = db.Column(db.Integer,
                                 db.ForeignKey("Groups.group_id",
                                               onupdate="CASCADE", ondelete="CASCADE"),
                                 nullable=False, index=True)
    issued_by        = db.Column(db.Integer,
                                 db.ForeignKey("Users.user_id",
                                               onupdate="CASCADE", ondelete="SET NULL"),
                                 nullable=True)
    issue_date       = db.Column(db.Date,       nullable=False, default=date.today)
    certificate_code = db.Column(db.String(64), nullable=False, unique=True)
 
    member = db.relationship("User",  back_populates="certificates",
                             foreign_keys=[member_id])
    issuer = db.relationship("User",  back_populates="issued_certificates",
                             foreign_keys=[issued_by])
    group  = db.relationship("Group", back_populates="certificates")
 
    def __repr__(self) -> str:
        return f"<Certificate id={self.certificate_id} code={self.certificate_code}>"