"""ORM row -> plain dict, derived from SQLAlchemy's own column mapping so
every field is included under its model-declared name with no hand-written,
easily-stale field list per endpoint. See schemas.py for why responses are
plain dicts rather than a second Pydantic-typed copy of the same shape."""
from sqlalchemy import inspect as sa_inspect


def to_dict(obj):
    if obj is None:
        return None
    return {c.key: getattr(obj, c.key) for c in sa_inspect(obj).mapper.column_attrs}


def to_dicts(objs):
    return [to_dict(o) for o in objs]
