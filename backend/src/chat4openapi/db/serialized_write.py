from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy.orm import Session


@contextmanager
def serialized_write(db: Session) -> Iterator[None]:
    """Serialize invariant-sensitive writes and discard pre-lock ORM state."""
    connection = db.connection()
    if connection.dialect.name == "sqlite":
        connection.exec_driver_sql("BEGIN IMMEDIATE")
    db.expire_all()
    try:
        yield
        db.commit()
    except BaseException:
        db.rollback()
        raise
