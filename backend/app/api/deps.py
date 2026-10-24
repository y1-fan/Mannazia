from __future__ import annotations

from collections.abc import Iterator

from fastapi import Request
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import Book


def get_db(request: Request) -> Iterator[Session]:
    with request.app.state.db.session() as session:
        yield session


def get_book_or_404(session: Session, book_id: str) -> Book:
    book = session.get(Book, book_id)
    if book is None:
        raise AppError("Book not found.", status_code=404, code="book_not_found")
    return book
