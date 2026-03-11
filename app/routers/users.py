from __future__ import annotations

import hashlib

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import User
from app.schemas import UserCreate, UserRead

router = APIRouter(prefix="/api/users", tags=["users"])


def hash_password(raw_password: str) -> str:
    return hashlib.sha256(raw_password.encode("utf-8")).hexdigest()


@router.get("/", response_model=list[UserRead])
def list_users(db: Session = Depends(get_db)) -> list[User]:
    return db.query(User).order_by(User.nome.asc()).all()


@router.post("/", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def create_user(payload: UserCreate, db: Session = Depends(get_db)) -> User:
    existing = db.query(User).filter(User.email == payload.email).first()
    if existing:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email already exists")

    user = User(
        nome=payload.nome,
        cargo=payload.cargo,
        email=payload.email,
        senha_hash=hash_password(payload.senha),
        ativo=payload.ativo,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user
