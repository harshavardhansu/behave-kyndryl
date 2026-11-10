from copy import deepcopy
from pathlib import Path
from threading import RLock
from typing import Callable, TypeVar

from sqlalchemy import JSON, String, create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column
from sqlalchemy.pool import StaticPool


class Base(DeclarativeBase):
    pass


class Entity(Base):
    __tablename__ = "entities"
    collection: Mapped[str] = mapped_column(String(40), primary_key=True)
    identifier: Mapped[str] = mapped_column(String(120), primary_key=True)
    body: Mapped[dict] = mapped_column(JSON)


class Workspace(Base):
    __tablename__ = "workspace"
    identifier: Mapped[str] = mapped_column(String(40), primary_key=True)
    body: Mapped[dict] = mapped_column(JSON)


class AuditRecord(Base):
    __tablename__ = "audit_events"
    identifier: Mapped[str] = mapped_column(String(120), primary_key=True)
    body: Mapped[dict] = mapped_column(JSON)


class AuthSession(Base):
    __tablename__ = "auth_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    body: Mapped[dict] = mapped_column(JSON)


COLLECTIONS = ("incidents", "services", "dependencies", "evidence", "hypotheses", "agents", "tests", "security", "changes", "approvals", "logs", "knowledge", "deployments", "integrations")
Result = TypeVar("Result")


class Store:
    def __init__(self, database_url: str):
        if database_url.startswith("sqlite:///./"):
            Path(database_url.removeprefix("sqlite:///./")).parent.mkdir(parents=True, exist_ok=True)
        options = {"connect_args": {"check_same_thread": False, "timeout": 5}} if database_url.startswith("sqlite") else {"pool_pre_ping": True, "pool_timeout": 5}
        if make_url(database_url).get_backend_name() == "postgresql":
            options["connect_args"] = {"connect_timeout": 5}
        if ":memory:" in database_url:
            options["poolclass"] = StaticPool
        self.engine = create_engine(database_url, **options)
        self.lock = RLock()
        Base.metadata.create_all(self.engine)

    def initialize(self, state: dict) -> None:
        with self.lock, Session(self.engine) as session, session.begin():
            if session.get(Workspace, "main"):
                return
            self._write(session, state)

    def _read(self, session: Session) -> dict:
        workspace = session.get(Workspace, "main")
        if workspace is None:
            raise RuntimeError("Workspace not initialized")
        state = deepcopy(workspace.body)
        for collection in COLLECTIONS:
            state[collection] = []
        for entity in session.scalars(select(Entity)):
            state[entity.collection].append(deepcopy(entity.body))
        state["audit"] = [deepcopy(record.body) for record in session.scalars(select(AuditRecord))]
        return state

    def _write(self, session: Session, state: dict) -> None:
        meta = {key: value for key, value in state.items() if key not in COLLECTIONS and key != "audit"}
        session.merge(Workspace(identifier="main", body=deepcopy(meta)))
        for collection in COLLECTIONS:
            for body in state[collection]:
                existing = session.get(Entity, (collection, body["id"]))
                if existing is None:
                    session.add(Entity(collection=collection, identifier=body["id"], body=deepcopy(body)))
                elif existing.body != body:
                    existing.body = deepcopy(body)
        for event in state["audit"]:
            if session.get(AuditRecord, event["id"]) is None:
                session.add(AuditRecord(identifier=event["id"], body=deepcopy(event)))

    def read(self) -> dict:
        with self.lock, Session(self.engine) as session:
            return self._read(session)

    def check_health(self) -> None:
        with self.engine.connect() as connection:
            connection.execute(select(Workspace.identifier).where(Workspace.identifier == "main")).scalar_one()

    def mutate(self, operation: Callable[[dict], Result]) -> Result:
        with self.lock, Session(self.engine) as session, session.begin():
            session.execute(select(Workspace).where(Workspace.identifier == "main").with_for_update()).scalar_one()
            state = self._read(session)
            result = operation(state)
            self._write(session, state)
            return deepcopy(result)

    def save_session(self, token_hash: str, data: dict) -> None:
        with self.lock, Session(self.engine) as session, session.begin():
            session.merge(AuthSession(token_hash=token_hash, body=data))

    def get_session(self, token_hash: str) -> dict | None:
        with self.lock, Session(self.engine) as session:
            record = session.get(AuthSession, token_hash)
            return deepcopy(record.body) if record else None

    def delete_session(self, token_hash: str) -> None:
        with self.lock, Session(self.engine) as session, session.begin():
            record = session.get(AuthSession, token_hash)
            if record:
                session.delete(record)