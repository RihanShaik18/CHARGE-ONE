"""Payment: one wallet that pays at every network."""
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import services
from ..database import get_db
from ..models import Transaction, User
from ..schemas import TopUpIn, TransactionOut, WalletOut
from ..security import get_current_user

router = APIRouter(prefix="/api/wallet", tags=["payment"])


def _wallet(db: Session, user: User) -> WalletOut:
    rows = db.scalars(
        select(Transaction).where(Transaction.user_id == user.id)
        .order_by(Transaction.id.desc()).limit(20)
    ).all()
    return WalletOut(
        balance=user.wallet_balance,
        transactions=[
            TransactionOut(
                id=t.id, kind=t.kind, amount=t.amount, balance_after=t.balance_after,
                description=t.description, created_at=services.iso(t.created_at),
            )
            for t in rows
        ],
    )


@router.get("", response_model=WalletOut)
def get_wallet(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _wallet(db, user)


@router.post("/topup", response_model=WalletOut)
def top_up(body: TopUpIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    # DEMO PAYMENT: money is simply added. In production, credit the wallet only after a
    # payment gateway (Razorpay / UPI / Stripe) confirms the payment.
    amount = round(body.amount, 2)
    user.wallet_balance = round(user.wallet_balance + amount, 2)
    db.add(Transaction(
        user_id=user.id, kind="topup", amount=amount,
        balance_after=user.wallet_balance, description="Wallet top-up",
    ))
    db.commit()
    return _wallet(db, user)