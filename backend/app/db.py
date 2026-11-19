import os
from datetime import date, datetime, timezone

from sqlalchemy import BigInteger, Date, DateTime, Integer, String, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./homestead.db")

# Hosts such as Neon hand out "postgresql://" URLs; psycopg 3 needs the explicit driver name.
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg://", 1)
elif DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
    pool_pre_ping=True,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False)


class Base(DeclarativeBase):
    pass


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Budget(Base):
    """The current figures. Only one row exists, with id = 1."""

    __tablename__ = "budget"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    budget_paise: Mapped[int] = mapped_column(BigInteger)
    paid_paise: Mapped[int] = mapped_column(BigInteger)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class BudgetHistory(Base):
    """Every saved change, so past values can be reviewed."""

    __tablename__ = "budget_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    budget_paise: Mapped[int] = mapped_column(BigInteger)
    paid_paise: Mapped[int] = mapped_column(BigInteger)
    saved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)


class Expense(Base):
    """A single payment. Its amount is added to the budget's amount paid."""

    __tablename__ = "expense"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    expense_date: Mapped[date] = mapped_column(Date, index=True)
    category: Mapped[str] = mapped_column(String(100))
    vendor: Mapped[str] = mapped_column(String(200), default="")
    amount_paise: Mapped[int] = mapped_column(BigInteger)
    notes: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ScheduledPayment(Base):
    __tablename__ = "scheduled_payment"
    __table_args__ = {"sqlite_autoincrement": True}

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    milestone: Mapped[str] = mapped_column(String(200))
    percentage_bps: Mapped[int]
    amount_paise: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(7))


def init_db() -> None:
    Base.metadata.create_all(engine)
