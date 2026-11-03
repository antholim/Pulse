# AI contribution: 50% or more AI-generated
"""Tenant isolation in the query layer: every session works for one tenant or says it is system.

A TenantSession bound to a tenant adds `tenant_id = <tenant>` to every ORM read, update and
delete, and checks that inserts, raw SQL and flushed objects belong to that tenant. Without a
tenant or explicit system access, any statement raises TenantContextError.
"""

import uuid
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from functools import cache
from typing import Any

from sqlalchemy import event, inspect
from sqlalchemy.exc import NoResultFound
from sqlalchemy.orm import ORMExecuteState, Session, with_loader_criteria

from app.models import Base, Tenant

TENANT_KEY = "tenant_id"
SYSTEM_KEY = "system_access"


class TenantContextError(RuntimeError):
    """A statement ran without a tenant, or touched another tenant's rows."""


class TenantSession(Session):
    """The session class of the app; see the module docstring."""

    def get(self, entity: Any, ident: Any, **kwargs: Any) -> Any:
        # get() can answer from the identity map without SQL, which skips the criteria.
        found = super().get(entity, ident, **kwargs)
        tenant_id = current_tenant(self)
        if found is None or tenant_id is None or _tenant_of(found) in (None, tenant_id):
            return found
        return None

    def get_one(self, entity: Any, ident: Any, **kwargs: Any) -> Any:
        found = self.get(entity, ident, **kwargs)
        if found is None:
            raise NoResultFound("No row was found when one was required")
        return found


@cache
def tenant_owned() -> tuple[type, ...]:
    """Mapped classes whose table has a tenant_id column."""
    return tuple(
        mapper.class_
        for mapper in Base.registry.mappers
        if "tenant_id" in mapper.local_table.c  # type: ignore[union-attr]
    )


def _tenant_of(obj: Any) -> uuid.UUID | None:
    if isinstance(obj, Tenant):
        return obj.id
    return getattr(obj, "tenant_id", None)


def current_tenant(session: Session) -> uuid.UUID | None:
    return session.info.get(TENANT_KEY)


def has_system_access(session: Session) -> bool:
    return bool(session.info.get(SYSTEM_KEY))


@contextmanager
def bound_to_tenant(session: Session, tenant_id: uuid.UUID) -> Iterator[Session]:
    """Scope `session` to one tenant until the block ends, then restore its previous scope."""
    current = current_tenant(session)
    if current is not None and current != tenant_id:
        raise TenantContextError("The session is already bound to another tenant")
    previous = (current, session.info.get(SYSTEM_KEY))
    session.info[TENANT_KEY] = tenant_id
    session.info.pop(SYSTEM_KEY, None)
    try:
        yield session
    finally:
        _restore(session, *previous)


@contextmanager
def system_access(session: Session) -> Iterator[Session]:
    """Let `session` work across tenants, for jobs that are not about one tenant."""
    if current_tenant(session) is not None:
        raise TenantContextError("A session bound to a tenant cannot get system access")
    previous = session.info.get(SYSTEM_KEY)
    session.info[SYSTEM_KEY] = True
    try:
        yield session
    finally:
        _restore(session, None, previous)


def _restore(session: Session, tenant_id: uuid.UUID | None, system: bool | None) -> None:
    for key, value in ((TENANT_KEY, tenant_id), (SYSTEM_KEY, system)):
        if value is None:
            session.info.pop(key, None)
        else:
            session.info[key] = value


def check_parameters(parameters: Any, tenant_id: uuid.UUID) -> None:
    """Every parameter set must carry tenant_id equal to the session's tenant."""
    rows = parameters if isinstance(parameters, list | tuple) else [parameters]
    if not rows or not all(isinstance(row, Mapping) and TENANT_KEY in row for row in rows):
        raise TenantContextError("Raw SQL and inserts must pass tenant_id as a parameter")
    if any(_as_uuid(row[TENANT_KEY]) != tenant_id for row in rows):
        raise TenantContextError("A statement passed another tenant's id")


def _as_uuid(value: Any) -> uuid.UUID:
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


def _tenant_criteria(tenant_id: uuid.UUID) -> list:
    options = [
        with_loader_criteria(cls, lambda cls: cls.tenant_id == tenant_id, include_aliases=True)
        for cls in tenant_owned()
    ]
    options.append(
        with_loader_criteria(Tenant, lambda cls: cls.id == tenant_id, include_aliases=True)
    )
    return options


@event.listens_for(TenantSession, "do_orm_execute")
def _scope_statement(state: ORMExecuteState) -> None:
    tenant_id = current_tenant(state.session)
    if tenant_id is None:
        if has_system_access(state.session):
            return
        raise TenantContextError("No tenant: bind the session with bound_to_tenant()")

    if not state.all_mappers or state.is_insert:
        # Raw SQL, Core table statements and inserts cannot be filtered, only checked.
        check_parameters(state.parameters, tenant_id)
        return
    # Column and relationship loads inherit the criteria of the query that loaded the object.
    if state.is_column_load or state.is_relationship_load:
        return
    state.statement = state.statement.options(*_tenant_criteria(tenant_id))


@event.listens_for(TenantSession, "before_flush")
def _check_flushed_objects(session: Session, _context: Any, _instances: Any) -> None:
    tenant_id = current_tenant(session)
    if tenant_id is None:
        if has_system_access(session) or not (session.new or session.dirty or session.deleted):
            return
        raise TenantContextError("No tenant: bind the session with bound_to_tenant()")

    for obj in session.new:
        if isinstance(obj, Tenant):
            raise TenantContextError("Tenants are created with system access")
        if isinstance(obj, tenant_owned()):
            if obj.tenant_id is None:
                obj.tenant_id = tenant_id
            elif obj.tenant_id != tenant_id:
                raise TenantContextError("Cannot add a row of another tenant")
    for obj in session.dirty:
        if isinstance(obj, tenant_owned()) and inspect(obj).attrs.tenant_id.history.has_changes():
            raise TenantContextError("A row cannot move to another tenant")
    for obj in session.deleted:
        if isinstance(obj, tenant_owned()) and obj.tenant_id != tenant_id:
            raise TenantContextError("Cannot delete a row of another tenant")
