import copy
import json
import pickle
import pytest
import threading
import warnings
from uuid import UUID
from uuid import uuid4

from memoria.db import repository


def _event(**overrides):
    from memoria.core.domain_events import NewDomainEvent

    values = {
        "owner_user_id": "user-1",
        "aggregate_type": "story",
        "aggregate_id": "graytide",
        "event_type": "story.started.v1",
        "payload": {},
    }
    values.update(overrides)
    return NewDomainEvent(**values)


def _stored_event(**overrides):
    from memoria.core.domain_events import StoredDomainEvent

    values = {
        **_event().model_dump(),
        "sequence": 1,
        "aggregate_version": 1,
        "recorded_at": "2026-07-15T00:00:00+00:00",
    }
    values.update(overrides)
    return StoredDomainEvent(**values)


def _story_event(owner_user_id, event_name, *, event_id=None):
    values = {
        "owner_user_id": owner_user_id,
        "aggregate_type": "story",
        "aggregate_id": "graytide",
        "event_type": f"story.{event_name}.v1",
        "payload": {},
    }
    if event_id is not None:
        values["event_id"] = event_id
    return _event(**values)


def _fully_identified_event(owner_user_id, *, event_id):
    return _event(
        owner_user_id=owner_user_id,
        aggregate_type="story",
        aggregate_id="graytide",
        event_type="story.started.v1",
        event_id=event_id,
        payload={"chapter": 1},
        metadata={"producer": "test"},
        correlation_id="request-1",
        causation_id="command-1",
        session_id="session-1",
        group_thread_id="group-1",
        source_turn_id="turn-1",
        source_message_id=1,
        world_occurred_at="2026-07-15T08:00:00+00:00",
    )


@pytest.fixture
def test_user():
    user_id = f"domain_{uuid4().hex}"
    repository.create_user(
        user_id,
        f"domain_user_{uuid4().hex}",
        "test-hash",
    )
    return user_id


def test_new_domain_event_rejects_blank_identity():
    from pydantic import ValidationError
    from memoria.core.domain_events import NewDomainEvent

    with pytest.raises(ValidationError):
        NewDomainEvent(
            owner_user_id="user-1",
            aggregate_type="story",
            aggregate_id="",
            event_type="story.started.v1",
            payload={},
        )


def test_new_domain_event_rejects_blank_optional_identity():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        _event(correlation_id="   ")


def test_new_domain_event_rejects_non_finite_json_numbers():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        _event(payload={"confidence": float("nan")})


def test_new_domain_event_normalizes_identity_and_defaults_event_id():
    first = _event(
        owner_user_id=" user-1 ",
        aggregate_type=" story ",
        aggregate_id=" graytide ",
        event_type=" story.started.v1 ",
        correlation_id=" request-1 ",
    )
    second = _event()

    assert first.owner_user_id == "user-1"
    assert first.aggregate_type == "story"
    assert first.aggregate_id == "graytide"
    assert first.event_type == "story.started.v1"
    assert first.correlation_id == "request-1"
    assert len(first.event_id) == 32
    assert UUID(hex=first.event_id).version == 4
    assert second.event_id != first.event_id


def test_domain_event_models_are_frozen():
    from pydantic import ValidationError
    from memoria.core.domain_events import StoredDomainEvent

    new_event = _event()
    stored_event = _stored_event()

    with pytest.raises(ValidationError):
        new_event.aggregate_id = "other"
    with pytest.raises(ValidationError):
        stored_event.aggregate_version = 2


def test_domain_event_json_fields_are_deeply_frozen():
    event = _event(
        payload={"items": [{"name": "seal"}]},
        metadata={"producer": "test"},
    )

    with pytest.raises(TypeError):
        event.payload["added"] = True
    with pytest.raises(TypeError):
        event.payload["items"][0]["name"] = "changed"
    with pytest.raises(TypeError):
        event.metadata["producer"] = "changed"


def test_domain_event_json_serialization_is_warning_free():
    event = _event(payload={"items": [{"name": "seal"}]})

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        dumped = event.model_dump()
        encoded = event.model_dump_json()

    assert dumped["payload"] == {"items": [{"name": "seal"}]}
    assert '"items":[{"name":"seal"}]' in encoded
    assert caught == []


def test_domain_event_supports_deep_copy_and_pickle():
    event = _event(
        payload={"items": [{"name": "seal"}]},
        metadata={"producer": "test"},
    )

    copies = [
        copy.deepcopy(event),
        event.model_copy(deep=True),
        pickle.loads(pickle.dumps(event)),
    ]

    for cloned in copies:
        assert cloned == event
        with pytest.raises(TypeError):
            cloned.payload["items"][0]["name"] = "changed"


def test_domain_event_rejects_unknown_fields():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        _event(correllation_id="typo")


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    [
        ("sequence", 0),
        ("sequence", "1"),
        ("aggregate_version", -1),
        ("aggregate_version", True),
        ("source_message_id", True),
    ],
)
def test_domain_event_rejects_invalid_integer_identity(
    field_name,
    invalid_value,
):
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        _stored_event(**{field_name: invalid_value})


def test_stored_domain_event_rejects_blank_recorded_at():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        _stored_event(recorded_at=" ")


def test_append_domain_event_assigns_aggregate_versions(test_user):
    first = repository.append_domain_event(
        _story_event(test_user, "started"),
    )
    second = repository.append_domain_event(
        _story_event(test_user, "progressed"),
    )

    assert first.aggregate_version == 1
    assert second.aggregate_version == 2


def test_append_domain_event_is_idempotent_by_event_id(test_user):
    event = _story_event(
        test_user,
        "started",
        event_id="stable-event",
    )

    first = repository.append_domain_event(event)
    second = repository.append_domain_event(event)

    assert second.sequence == first.sequence
    assert repository.list_domain_events(
        test_user,
        "story",
        "graytide",
    ) == [first]


@pytest.mark.parametrize(
    ("field_name", "conflicting_value"),
    [
        ("owner_user_id", "other-owner"),
        ("aggregate_type", "chapter"),
        ("aggregate_id", "other-story"),
        ("event_type", "story.progressed.v1"),
        ("payload", {"chapter": 2}),
        ("metadata", {"producer": "other"}),
        ("correlation_id", "request-2"),
        ("causation_id", "command-2"),
        ("session_id", "session-2"),
        ("group_thread_id", "group-2"),
        ("source_turn_id", "turn-2"),
        ("source_message_id", 2),
        ("world_occurred_at", "2026-07-15T09:00:00+00:00"),
    ],
)
def test_append_domain_event_rejects_conflicting_event_id_reuse(
    test_user,
    field_name,
    conflicting_value,
):
    event_id = f"conflicting-{uuid4().hex}"
    original = _fully_identified_event(test_user, event_id=event_id)
    repository.append_domain_event(original)
    conflicting = original.model_copy(
        update={field_name: conflicting_value},
    )

    with pytest.raises(
        repository.DomainEventConcurrencyError,
        match="idempotency conflict",
    ):
        repository.append_domain_event(conflicting)


def test_append_domain_event_does_not_return_another_tenants_event(test_user):
    event_id = f"shared-{uuid4().hex}"
    stored = repository.append_domain_event(
        _story_event(test_user, "started", event_id=event_id),
    )
    other_user = f"other_{uuid4().hex}"

    with pytest.raises(repository.DomainEventConcurrencyError):
        repository.append_domain_event(
            _story_event(other_user, "started", event_id=event_id),
        )

    assert repository.get_domain_event(
        stored.event_id,
        owner_user_id=other_user,
    ) is None
    assert repository.list_domain_events(
        other_user,
        "story",
        "graytide",
    ) == []


def test_append_domain_event_rejects_stale_expected_version(test_user):
    repository.append_domain_event(
        _story_event(test_user, "started"),
        expected_version=0,
    )

    with pytest.raises(repository.DomainEventConcurrencyError):
        repository.append_domain_event(
            _story_event(test_user, "progressed"),
            expected_version=0,
        )

    events = repository.list_domain_events(
        test_user,
        "story",
        "graytide",
    )
    assert [event.aggregate_version for event in events] == [1]


def test_append_domain_events_is_atomic_across_aggregates(test_user):
    repository.append_domain_event(
        _story_event(test_user, "started"),
    )
    other_story = _event(
        owner_user_id=test_user,
        aggregate_type="story",
        aggregate_id="other-story",
        event_type="story.started.v1",
        payload={},
    )

    with pytest.raises(repository.DomainEventConcurrencyError):
        repository.append_domain_events(
            [
                other_story,
                _story_event(test_user, "progressed"),
            ],
            expected_versions={
                (test_user, "story", "graytide"): 0,
            },
        )

    assert repository.list_domain_events(
        test_user,
        "story",
        "other-story",
    ) == []


def test_append_domain_events_is_atomic_when_external_transaction_catches_conflict(
    test_user,
):
    repository.append_domain_event(
        _story_event(test_user, "started"),
    )
    other_story = _event(
        owner_user_id=test_user,
        aggregate_type="story",
        aggregate_id="external-other-story",
        event_type="story.started.v1",
        payload={},
    )

    with repository.get_conn() as conn:
        with pytest.raises(repository.DomainEventConcurrencyError):
            repository.append_domain_events(
                [
                    other_story,
                    _story_event(test_user, "progressed"),
                ],
                expected_versions={
                    (test_user, "story", "graytide"): 0,
                },
                conn=conn,
            )
        repository.append_domain_event(
            _event(
                owner_user_id=test_user,
                aggregate_type="story",
                aggregate_id="external-recovery-story",
                event_type="story.started.v1",
                payload={},
            ),
            conn=conn,
        )

    assert repository.list_domain_events(
        test_user,
        "story",
        "external-other-story",
    ) == []
    assert len(repository.list_domain_events(
        test_user,
        "story",
        "external-recovery-story",
    )) == 1


def _run_sqlite_domain_event_race(
    monkeypatch,
    first_append,
    second_append,
):
    original_current_version = repository._current_domain_event_version
    thread_role = threading.local()
    first_version_read = threading.Event()
    release_first = threading.Event()
    second_version_read = threading.Event()
    results = {}
    errors = {}

    def synchronized_current_version(conn, aggregate_key):
        version = original_current_version(conn, aggregate_key)
        if thread_role.value == "first":
            first_version_read.set()
            if not release_first.wait(timeout=5):
                raise RuntimeError("timed out waiting to release first writer")
        else:
            second_version_read.set()
        return version

    def run(role, append):
        thread_role.value = role
        try:
            results[role] = append()
        except Exception as exc:
            errors[role] = exc

    monkeypatch.setattr(
        repository,
        "_current_domain_event_version",
        synchronized_current_version,
    )
    first_thread = threading.Thread(
        target=run,
        args=("first", first_append),
    )
    second_thread = threading.Thread(
        target=run,
        args=("second", second_append),
    )

    first_thread.start()
    assert first_version_read.wait(timeout=5)
    second_thread.start()
    second_read_while_first_held = second_version_read.wait(timeout=1)
    release_first.set()
    first_thread.join(timeout=10)
    second_thread.join(timeout=10)

    assert not first_thread.is_alive()
    assert not second_thread.is_alive()
    return second_read_while_first_held, results, errors


def test_sqlite_concurrent_expected_version_writers_are_serialized(
    test_user,
    monkeypatch,
):
    aggregate_id = f"sqlite-race-{uuid4().hex}"

    second_read_while_first_held, results, errors = (
        _run_sqlite_domain_event_race(
            monkeypatch,
            lambda: repository.append_domain_event(
                _event(
                    owner_user_id=test_user,
                    aggregate_id=aggregate_id,
                    event_type="story.started.v1",
                ),
                expected_version=0,
            ),
            lambda: repository.append_domain_event(
                _event(
                    owner_user_id=test_user,
                    aggregate_id=aggregate_id,
                    event_type="story.progressed.v1",
                ),
                expected_version=0,
            ),
        )
    )

    assert second_read_while_first_held is False
    assert results["first"].aggregate_version == 1
    assert isinstance(
        errors.get("second"),
        repository.DomainEventConcurrencyError,
    )


def test_sqlite_concurrent_duplicate_event_id_returns_existing(
    test_user,
    monkeypatch,
):
    event = _event(
        owner_user_id=test_user,
        aggregate_id=f"sqlite-idempotency-{uuid4().hex}",
        event_id=f"concurrent-{uuid4().hex}",
    )

    second_read_while_first_held, results, errors = (
        _run_sqlite_domain_event_race(
            monkeypatch,
            lambda: repository.append_domain_event(event),
            lambda: repository.append_domain_event(event),
        )
    )

    assert second_read_while_first_held is False
    assert errors == {}
    assert results["second"].sequence == results["first"].sequence
    assert repository.list_domain_events(
        test_user,
        "story",
        event.aggregate_id,
    ) == [results["first"]]


def test_get_domain_event_round_trips_and_enforces_owner_boundary(test_user):
    stored = repository.append_domain_event(
        _story_event(test_user, "started"),
    )

    with pytest.raises(TypeError):
        repository.get_domain_event(stored.event_id)
    assert repository.get_domain_event(
        stored.event_id,
        owner_user_id=test_user,
    ) == stored
    assert repository.get_domain_event(
        stored.event_id,
        owner_user_id="other-user",
    ) is None


@pytest.mark.parametrize("invalid_limit", [-1, True])
def test_list_domain_events_rejects_invalid_limit(
    test_user,
    invalid_limit,
):
    repository.append_domain_event(
        _story_event(test_user, "started"),
    )

    with pytest.raises(ValueError):
        repository.list_domain_events(
            test_user,
            "story",
            "graytide",
            limit=invalid_limit,
        )


def test_domain_event_schema_and_indexes_are_additive():
    with repository.get_conn() as conn:
        tables = {
            row["name"]
            for row in conn.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table'
                """
            ).fetchall()
        }
        indexes = {
            row["name"]
            for row in conn.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'index'
                """
            ).fetchall()
        }

    assert {
        "domain_event",
        "projection_checkpoint",
        "data_migration",
    } <= tables
    assert {
        "idx_domain_event_aggregate",
        "idx_domain_event_correlation",
        "idx_domain_event_source_turn",
        "idx_domain_event_group_thread",
    } <= indexes


def test_replay_rebuilds_fact_and_story_projections(test_user):
    from memoria.core import fact_claims

    story_id = f"graytide-replay-{uuid4().hex}"
    fact_claims.record_claim(
        test_user,
        "story",
        story_id,
        "旧港灯塔编号为 GT-7。",
        source_kind="authored_event",
        source_ids=["event:graytide-replay"],
        provenance={"chapter": 3},
    )
    repository.append_story_event(
        test_user,
        story_id,
        "story.started.v1",
        {"progress": 0.1},
    )
    repository.append_story_event(
        test_user,
        story_id,
        "story.progressed.v1",
        {"progress": 0.75},
    )
    repository.append_story_event(
        test_user,
        story_id,
        "story.completed.v1",
        {"reason": "replay-test"},
    )

    original_claims = repository.list_fact_claims(
        test_user,
        "story",
        story_id,
    )
    original_story = repository.get_story_state(test_user, story_id)
    events = repository.list_domain_events(test_user)
    expected_sequences = {
        repository.FACT_CLAIM_PROJECTOR: max(
            event.sequence
            for event in events
            if event.aggregate_type == "fact_claim"
        ),
        repository.STORY_STATE_PROJECTOR: max(
            event.sequence
            for event in events
            if event.aggregate_type == "story"
        ),
    }

    with repository.get_conn() as conn:
        conn.execute(
            "DELETE FROM fact_claim WHERE owner_user_id = ?",
            (test_user,),
        )
        conn.execute(
            "DELETE FROM story_state WHERE owner_user_id = ?",
            (test_user,),
        )
        conn.execute(
            "DELETE FROM projection_checkpoint WHERE owner_user_id = ?",
            (test_user,),
        )

    repository.rebuild_domain_projections(test_user)

    assert repository.list_fact_claims(
        test_user,
        "story",
        story_id,
    ) == original_claims
    assert repository.get_story_state(test_user, story_id) == original_story
    assert {
        projector_name: repository.get_projection_checkpoint(
            projector_name,
            test_user,
        )["last_sequence"]
        for projector_name in expected_sequences
    } == expected_sequences


def test_replay_rejects_unknown_major_version_without_losing_projections(
    test_user,
):
    story_id = f"graytide-stable-{uuid4().hex}"
    original_story = repository.append_story_event(
        test_user,
        story_id,
        "story.started.v1",
        {"progress": 0.25},
    )
    repository.append_domain_event(
        _event(
            owner_user_id=test_user,
            aggregate_type="story",
            aggregate_id=f"graytide-future-{uuid4().hex}",
            event_type="story.started.v2",
        ),
    )

    with pytest.raises(
        repository.UnsupportedDomainEventVersionError,
        match=r"story\.started\.v2.*major version 2",
    ):
        repository.rebuild_domain_projections(test_user)

    assert repository.get_story_state(test_user, story_id) == original_story


def test_legacy_fact_backfill_is_idempotent_and_non_destructive(test_user):
    migration_key = repository.LONG_TERM_FACT_BACKFILL_MIGRATION
    character_ids = [
        f"legacy-character-{uuid4().hex}",
        f"legacy-character-{uuid4().hex}",
    ]
    fact_texts = [
        "玩家曾在旧码头见过灰色封条。",
        "调查组知道东侧闸门的旧编号。",
    ]

    with repository.get_conn() as conn:
        conn.execute(
            "DELETE FROM data_migration WHERE migration_key = ?",
            (migration_key,),
        )
        legacy_fact_ids = []
        for character_id, fact_text in zip(character_ids, fact_texts):
            cursor = conn.execute(
                """
                INSERT INTO long_term_fact (
                    character_id,
                    player_id,
                    fact_text,
                    importance,
                    created_at,
                    last_referenced
                )
                VALUES (?, ?, ?, 5, ?, ?)
                """,
                (
                    character_id,
                    test_user,
                    fact_text,
                    "2026-07-15T00:00:00+00:00",
                    "2026-07-15T00:00:00+00:00",
                ),
            )
            legacy_fact_ids.append(cursor.lastrowid)

    try:
        repository.backfill_legacy_long_term_fact_events()
        first_events = [
            event
            for event in repository.list_domain_events(test_user)
            if event.event_type == "fact.claimed.v1"
            and event.metadata.get("legacy_backfill") is True
        ]

        repository.backfill_legacy_long_term_fact_events()
        second_events = [
            event
            for event in repository.list_domain_events(test_user)
            if event.event_type == "fact.claimed.v1"
            and event.metadata.get("legacy_backfill") is True
        ]

        assert [event.event_id for event in first_events] == [
            f"legacy-long-term-fact-{fact_id}"
            for fact_id in legacy_fact_ids
        ]
        assert second_events == first_events
        assert all(
            event.metadata["legacy_fact_id"] == fact_id
            for event, fact_id in zip(first_events, legacy_fact_ids)
        )
        assert all(
            repository.get_fact_claim(
                test_user,
                event.payload["claim_id"],
            )["status"] == "candidate"
            for event in first_events
        )
        with repository.get_conn() as conn:
            source_count = conn.execute(
                """
                SELECT COUNT(*) AS count
                FROM long_term_fact
                WHERE id IN (?, ?)
                """,
                tuple(legacy_fact_ids),
            ).fetchone()["count"]
        assert source_count == 2
        assert repository.has_data_migration(migration_key)
    finally:
        with repository.get_conn() as conn:
            conn.execute(
                "DELETE FROM data_migration WHERE migration_key = ?",
                (migration_key,),
            )


class _FakePostgresUniqueViolation(Exception):
    sqlstate = "23505"


class _FakePostgresInFailedTransaction(Exception):
    pass


class _FakeCursor:
    def __init__(self, row=None):
        self._row = row

    def fetchone(self):
        return self._row


class _AbortingPostgresConnection:
    def __init__(self, existing_after_rollback=None):
        self.aborted = False
        self.rolled_back_to_savepoint = False
        self.existing_after_rollback = existing_after_rollback

    def execute(self, sql, params=None):
        normalized = " ".join(sql.split())
        if normalized.startswith("ROLLBACK TO SAVEPOINT"):
            self.aborted = False
            self.rolled_back_to_savepoint = True
            return _FakeCursor()
        if self.aborted:
            raise _FakePostgresInFailedTransaction(normalized)
        if normalized.startswith("SAVEPOINT"):
            return _FakeCursor()
        if normalized.startswith("RELEASE SAVEPOINT"):
            return _FakeCursor()
        if normalized.startswith(
            "SELECT * FROM domain_event WHERE event_id = ?"
        ):
            row = (
                self.existing_after_rollback
                if self.rolled_back_to_savepoint
                else None
            )
            return _FakeCursor(row)
        if "SELECT COALESCE(MAX(aggregate_version), 0)" in normalized:
            return _FakeCursor({"aggregate_version": 0})
        if normalized.startswith("INSERT INTO domain_event"):
            self.aborted = True
            raise _FakePostgresUniqueViolation()
        raise AssertionError(f"unexpected SQL: {normalized}")


class _MixedRecoveryPostgresConnection:
    def __init__(self, recovered_event):
        self.aborted = False
        self.recovered_event = recovered_event
        self.recovered_event_visible = False
        self.insert_attempts = []

    def execute(self, sql, params=None):
        normalized = " ".join(sql.split())
        if normalized.startswith("ROLLBACK TO SAVEPOINT"):
            self.aborted = False
            self.recovered_event_visible = True
            return _FakeCursor()
        if self.aborted:
            raise _FakePostgresInFailedTransaction(normalized)
        if normalized.startswith("SAVEPOINT"):
            return _FakeCursor()
        if normalized.startswith("RELEASE SAVEPOINT"):
            return _FakeCursor()
        if normalized.startswith(
            "SELECT * FROM domain_event WHERE event_id = ?"
        ):
            event_id = params[0]
            row = None
            if (
                self.recovered_event_visible
                and event_id == self.recovered_event["event_id"]
            ):
                row = self.recovered_event
            return _FakeCursor(row)
        if "SELECT COALESCE(MAX(aggregate_version), 0)" in normalized:
            return _FakeCursor({"aggregate_version": 0})
        if normalized.startswith("INSERT INTO domain_event"):
            event_id = params[0]
            aggregate_version = params[4]
            self.insert_attempts.append((event_id, aggregate_version))
            if event_id == self.recovered_event["event_id"]:
                self.aborted = True
                raise _FakePostgresUniqueViolation()
            if aggregate_version != 2:
                self.aborted = True
                raise _FakePostgresUniqueViolation()
            return _FakeCursor({"sequence": 8})
        raise AssertionError(f"unexpected SQL: {normalized}")


def _stored_database_row(event, *, sequence=7, aggregate_version=1):
    values = event.model_dump()
    values.update({
        "sequence": sequence,
        "aggregate_version": aggregate_version,
        "recorded_at": "2026-07-15T00:00:00+00:00",
        "payload": json.dumps(values["payload"]),
        "metadata": json.dumps(values["metadata"]),
    })
    return values


def test_postgres_aggregate_conflict_recovers_before_translating(monkeypatch):
    monkeypatch.setattr(repository, "_is_postgres_enabled", lambda: True)
    conn = _AbortingPostgresConnection()

    with pytest.raises(repository.DomainEventConcurrencyError):
        repository.append_domain_event(
            _story_event("user-1", "started"),
            conn=conn,
        )

    assert conn.rolled_back_to_savepoint is True


def test_postgres_concurrent_duplicate_event_id_returns_existing(monkeypatch):
    monkeypatch.setattr(repository, "_is_postgres_enabled", lambda: True)
    event = _story_event(
        "user-1",
        "started",
        event_id="same-event",
    )
    conn = _AbortingPostgresConnection(
        existing_after_rollback=_stored_database_row(event),
    )

    stored = repository.append_domain_event(event, conn=conn)

    assert stored.event_id == event.event_id
    assert stored.sequence == 7
    assert conn.rolled_back_to_savepoint is True


def test_postgres_batch_advances_version_after_recovered_duplicate(monkeypatch):
    monkeypatch.setattr(repository, "_is_postgres_enabled", lambda: True)
    first = _story_event(
        "user-1",
        "started",
        event_id="same-event",
    )
    second = _story_event(
        "user-1",
        "progressed",
        event_id="next-event",
    )
    conn = _MixedRecoveryPostgresConnection(
        _stored_database_row(first),
    )
    aggregate_key = ("user-1", "story", "graytide")

    stored = repository.append_domain_events(
        [first, second],
        expected_versions={aggregate_key: 0},
        conn=conn,
    )

    assert [event.event_id for event in stored] == [
        "same-event",
        "next-event",
    ]
    assert [event.aggregate_version for event in stored] == [1, 2]
    assert conn.insert_attempts == [
        ("same-event", 1),
        ("next-event", 2),
    ]


def test_postgres_concurrent_event_id_recovery_rejects_mismatch(monkeypatch):
    monkeypatch.setattr(repository, "_is_postgres_enabled", lambda: True)
    event = _fully_identified_event("user-1", event_id="same-event")
    conflicting = event.model_copy(
        update={"payload": {"chapter": 2}},
    )
    conn = _AbortingPostgresConnection(
        existing_after_rollback=_stored_database_row(conflicting),
    )

    with pytest.raises(
        repository.DomainEventConcurrencyError,
        match="idempotency conflict",
    ):
        repository.append_domain_event(event, conn=conn)

    assert conn.rolled_back_to_savepoint is True
