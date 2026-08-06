"""
SQLAlchemy 2.0 declarative ORM models for all 42 Memoria tables.

Column types map directly from the SQLite CREATE TABLE definitions in
``repository/_common.py``.  JSON blobs are stored as ``Text``; serialisation
and deserialisation live in the repository layer.

SQLAlchemy ≥ 2.0 required.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    PrimaryKeyConstraint,
    String,
    Text,
    text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------

class Base(DeclarativeBase):
    """Shared declarative base for every Memoria ORM model."""
    pass


# ===========================================================================
# User & Auth
# ===========================================================================

class User(Base):
    __tablename__ = "users"

    user_id: Mapped[str] = mapped_column(Text, primary_key=True)
    username: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    is_admin: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    gender: Mapped[Optional[str]] = mapped_column(Text, default="unknown", server_default=text("'unknown'"))
    avatar_url: Mapped[Optional[str]] = mapped_column(Text)
    tts_auto_play: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    stt_auto_send: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    created_at: Mapped[Optional[str]] = mapped_column(Text)
    updated_at: Mapped[Optional[str]] = mapped_column(Text)


class UserCharacterCard(Base):
    __tablename__ = "user_character_card"

    user_id: Mapped[str] = mapped_column(Text, ForeignKey("users.user_id"), primary_key=True)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    avatar_url: Mapped[Optional[str]] = mapped_column(Text)
    gender: Mapped[Optional[str]] = mapped_column(Text, default="unknown", server_default=text("'unknown'"))
    pronouns: Mapped[Optional[str]] = mapped_column(Text, default="", server_default=text("''"))
    age: Mapped[Optional[int]] = mapped_column(Integer)
    species: Mapped[Optional[str]] = mapped_column(Text, default="", server_default=text("''"))
    occupation: Mapped[Optional[str]] = mapped_column(Text, default="", server_default=text("''"))
    appearance: Mapped[Optional[str]] = mapped_column(Text, default="", server_default=text("''"))
    personality: Mapped[Optional[str]] = mapped_column(Text, default="", server_default=text("''"))
    background: Mapped[Optional[str]] = mapped_column(Text, default="", server_default=text("''"))
    goals: Mapped[Optional[str]] = mapped_column(Text, default="", server_default=text("''"))
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)


class AuthToken(Base):
    __tablename__ = "auth_token"

    token: Mapped[str] = mapped_column(Text, primary_key=True)
    user_id: Mapped[str] = mapped_column(Text, ForeignKey("users.user_id"), nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        Index("idx_auth_token_user", "user_id", "expires_at"),
    )


class SystemBootstrapClaim(Base):
    __tablename__ = "system_bootstrap_claim"

    claim_key: Mapped[str] = mapped_column(Text, primary_key=True)
    claimed_by_user_id: Mapped[str] = mapped_column(Text, nullable=False)
    claimed_at: Mapped[str] = mapped_column(Text, nullable=False)


# ===========================================================================
# Player World Clock
# ===========================================================================

class PlayerWorldClock(Base):
    __tablename__ = "player_world_clock"

    player_id: Mapped[str] = mapped_column(Text, ForeignKey("users.user_id"), primary_key=True)
    timezone: Mapped[str] = mapped_column(Text, nullable=False, default="UTC", server_default=text("'UTC'"))
    timezone_mode: Mapped[str] = mapped_column(Text, nullable=False, default="fixed", server_default=text("'fixed'"))
    anchor_real_utc: Mapped[str] = mapped_column(Text, nullable=False)
    anchor_world_utc: Mapped[str] = mapped_column(Text, nullable=False)
    time_scale: Mapped[float] = mapped_column(Float, nullable=False, default=1, server_default=text("1"))
    clock_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default=text("1"))
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)


# ===========================================================================
# Character Cards
# ===========================================================================

class CharacterCard(Base):
    __tablename__ = "character_card"

    owner_user_id: Mapped[str] = mapped_column(Text, ForeignKey("users.user_id"), primary_key=True)
    character_id: Mapped[str] = mapped_column(Text, primary_key=True)
    card_data: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[Optional[str]] = mapped_column(Text, default="1.0.0", server_default=text("'1.0.0'"))
    name: Mapped[Optional[str]] = mapped_column(Text)
    display_name: Mapped[Optional[str]] = mapped_column(Text)
    avatar_url: Mapped[Optional[str]] = mapped_column(Text)
    avatar_revision: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[Optional[str]] = mapped_column(Text)
    updated_at: Mapped[Optional[str]] = mapped_column(Text)
    is_active: Mapped[Optional[int]] = mapped_column(Integer, default=1, server_default=text("1"))
    source: Mapped[Optional[str]] = mapped_column(Text, default="db", server_default=text("'db'"))

    __table_args__ = (
        Index("idx_character_active", "owner_user_id", "is_active", "created_at"),
    )


# ===========================================================================
# Event System
# ===========================================================================

class EventDefinition(Base):
    __tablename__ = "event_definition"

    owner_user_id: Mapped[str] = mapped_column(Text, ForeignKey("users.user_id"), primary_key=True)
    event_id: Mapped[str] = mapped_column(Text, primary_key=True)
    event_name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    character_id: Mapped[Optional[str]] = mapped_column(Text)
    story_id: Mapped[Optional[str]] = mapped_column(Text)
    trigger_config: Mapped[str] = mapped_column(Text, nullable=False)
    effects_config: Mapped[str] = mapped_column(Text, nullable=False)
    schedule: Mapped[Optional[str]] = mapped_column(Text)
    template_id: Mapped[Optional[str]] = mapped_column(Text)
    priority: Mapped[Optional[int]] = mapped_column(Integer, default=0, server_default=text("0"))
    exclusive_group: Mapped[Optional[str]] = mapped_column(Text)
    exclusive_scope: Mapped[str] = mapped_column(Text, nullable=False, default="turn", server_default=text("'turn'"))
    max_triggers_per_turn: Mapped[Optional[int]] = mapped_column(Integer, default=3, server_default=text("3"))
    stop_processing: Mapped[Optional[int]] = mapped_column(Integer, default=0, server_default=text("0"))
    is_active: Mapped[Optional[int]] = mapped_column(Integer, default=1, server_default=text("1"))
    created_at: Mapped[Optional[str]] = mapped_column(Text)
    updated_at: Mapped[Optional[str]] = mapped_column(Text)
    trigger_count: Mapped[Optional[int]] = mapped_column(Integer, default=0, server_default=text("0"))
    last_triggered_at: Mapped[Optional[str]] = mapped_column(Text)

    __table_args__ = (
        Index("idx_event_character", "owner_user_id", "character_id", "is_active"),
    )


class EventTriggerLog(Base):
    __tablename__ = "event_trigger_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(Text, nullable=False)
    character_id: Mapped[str] = mapped_column(Text, nullable=False)
    player_id: Mapped[str] = mapped_column(Text, nullable=False)
    session_id: Mapped[str] = mapped_column(Text, nullable=False)
    triggered_at: Mapped[Optional[str]] = mapped_column(Text)
    context_snapshot: Mapped[Optional[str]] = mapped_column(Text)
    effects_applied: Mapped[Optional[str]] = mapped_column(Text)
    execution_id: Mapped[Optional[str]] = mapped_column(Text)
    status: Mapped[Optional[str]] = mapped_column(Text, default="succeeded", server_default=text("'succeeded'"))

    __table_args__ = (
        ForeignKeyConstraint(
            ["player_id", "event_id"],
            ["event_definition.owner_user_id", "event_definition.event_id"],
        ),
        Index("idx_event_trigger_log", "event_id", "character_id", "player_id", "triggered_at"),
    )


class EventTriggerGuard(Base):
    __tablename__ = "event_trigger_guard"

    player_id: Mapped[str] = mapped_column(Text, primary_key=True)
    event_id: Mapped[str] = mapped_column(Text, primary_key=True)
    character_scope: Mapped[str] = mapped_column(Text, primary_key=True)
    last_triggered_at: Mapped[Optional[str]] = mapped_column(Text)
    claim_token: Mapped[Optional[str]] = mapped_column(Text)
    claim_expires_at: Mapped[Optional[str]] = mapped_column(Text)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)


class EventExclusiveGroupGuard(Base):
    __tablename__ = "event_exclusive_group_guard"

    player_id: Mapped[str] = mapped_column(Text, primary_key=True)
    exclusive_group: Mapped[str] = mapped_column(Text, primary_key=True)
    selected_event_id: Mapped[Optional[str]] = mapped_column(Text)
    claim_token: Mapped[Optional[str]] = mapped_column(Text)
    claim_expires_at: Mapped[Optional[str]] = mapped_column(Text)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)


class EventExecutionBatch(Base):
    __tablename__ = "event_execution_batch"

    player_id: Mapped[str] = mapped_column(Text, primary_key=True)
    execution_key: Mapped[str] = mapped_column(Text, primary_key=True)
    trigger_source: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    results_data: Mapped[str] = mapped_column(Text, nullable=False)
    deduplicated_count: Mapped[Optional[int]] = mapped_column(Integer, default=0, server_default=text("0"))
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    completed_at: Mapped[Optional[str]] = mapped_column(Text)


class EventExecution(Base):
    __tablename__ = "event_execution"

    execution_id: Mapped[str] = mapped_column(Text, primary_key=True)
    execution_key: Mapped[str] = mapped_column(Text, nullable=False)
    owner_user_id: Mapped[str] = mapped_column(Text, nullable=False)
    event_id: Mapped[str] = mapped_column(Text, nullable=False)
    character_id: Mapped[str] = mapped_column(Text, nullable=False)
    session_id: Mapped[str] = mapped_column(Text, nullable=False)
    trigger_source: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    effects_data: Mapped[str] = mapped_column(Text, nullable=False)
    result_data: Mapped[str] = mapped_column(Text, nullable=False)
    error: Mapped[Optional[str]] = mapped_column(Text)
    duration_ms: Mapped[Optional[float]] = mapped_column(Float, default=0.0, server_default=text("0.0"))
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    completed_at: Mapped[Optional[str]] = mapped_column(Text)

    __table_args__ = (
        UniqueConstraint("owner_user_id", "event_id", "execution_key"),
        Index("idx_event_execution_metrics", "owner_user_id", "event_id", "status", "completed_at"),
    )


class EventUnlock(Base):
    __tablename__ = "event_unlock"

    player_id: Mapped[str] = mapped_column(Text, primary_key=True)
    character_id: Mapped[str] = mapped_column(Text, primary_key=True)
    unlock_key: Mapped[str] = mapped_column(Text, primary_key=True)
    event_id: Mapped[str] = mapped_column(Text, nullable=False)
    unlocked_at: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        Index("idx_event_unlock_lookup", "player_id", "character_id", "unlocked_at"),
    )


class EventContextState(Base):
    __tablename__ = "event_context_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(Text, nullable=False)
    character_id: Mapped[str] = mapped_column(Text, nullable=False)
    player_id: Mapped[str] = mapped_column(Text, nullable=False)
    context_data: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[Optional[str]] = mapped_column(Text, default="active", server_default=text("'active'"))
    progress: Mapped[Optional[float]] = mapped_column(Float, default=0.0, server_default=text("0.0"))
    last_session_id: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[Optional[str]] = mapped_column(Text)
    updated_at: Mapped[Optional[str]] = mapped_column(Text)

    __table_args__ = (
        UniqueConstraint("event_id", "character_id", "player_id"),
        Index("idx_event_context_lookup", "character_id", "player_id", "status", "updated_at"),
    )


class EventScheduleState(Base):
    __tablename__ = "event_schedule_state"

    event_id: Mapped[str] = mapped_column(Text, primary_key=True)
    character_id: Mapped[str] = mapped_column(Text, primary_key=True)
    player_id: Mapped[str] = mapped_column(Text, primary_key=True)
    schedule: Mapped[str] = mapped_column(Text, nullable=False)
    last_checked_at: Mapped[Optional[str]] = mapped_column(Text)
    last_run_at: Mapped[Optional[str]] = mapped_column(Text)
    next_run_at: Mapped[Optional[str]] = mapped_column(Text)
    next_due_real_at: Mapped[Optional[str]] = mapped_column(Text)
    missed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    status: Mapped[Optional[str]] = mapped_column(Text, default="active", server_default=text("'active'"))
    lease_owner: Mapped[Optional[str]] = mapped_column(Text)
    lease_expires_at: Mapped[Optional[str]] = mapped_column(Text)
    last_error: Mapped[Optional[str]] = mapped_column(Text)
    last_failed_at: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[Optional[str]] = mapped_column(Text)
    updated_at: Mapped[Optional[str]] = mapped_column(Text)

    __table_args__ = (
        Index("idx_event_schedule_due", "status", "next_run_at"),
        Index("idx_event_schedule_due_real", "status", "next_due_real_at"),
        Index("idx_event_schedule_lease", "status", "lease_expires_at"),
    )


class EventTemplate(Base):
    __tablename__ = "event_template"

    template_id: Mapped[str] = mapped_column(Text, primary_key=True)
    template_name: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[Optional[str]] = mapped_column(Text)
    description: Mapped[Optional[str]] = mapped_column(Text)
    trigger_config: Mapped[str] = mapped_column(Text, nullable=False)
    effects_config: Mapped[str] = mapped_column(Text, nullable=False)
    template_metadata: Mapped[Optional[str]] = mapped_column("metadata", Text)
    created_at: Mapped[Optional[str]] = mapped_column(Text)
    updated_at: Mapped[Optional[str]] = mapped_column(Text)


# ===========================================================================
# Character Relationships
# ===========================================================================

class CharacterRelationship(Base):
    __tablename__ = "character_relationship"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_user_id: Mapped[str] = mapped_column(Text, ForeignKey("users.user_id"), nullable=False)
    character_id_a: Mapped[str] = mapped_column(Text, nullable=False)
    character_id_b: Mapped[str] = mapped_column(Text, nullable=False)
    relationship_type: Mapped[Optional[str]] = mapped_column(Text)
    affinity: Mapped[Optional[float]] = mapped_column(Float, default=0.0, server_default=text("0.0"))
    description: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[Optional[str]] = mapped_column(Text)
    updated_at: Mapped[Optional[str]] = mapped_column(Text)

    __table_args__ = (
        UniqueConstraint("owner_user_id", "character_id_a", "character_id_b"),
        Index("idx_relationship_lookup", "owner_user_id", "character_id_a", "character_id_b"),
    )


class CharacterRelationshipRevision(Base):
    __tablename__ = "character_relationship_revision"

    owner_user_id: Mapped[str] = mapped_column(Text, ForeignKey("users.user_id"), primary_key=True)
    character_id_a: Mapped[str] = mapped_column(Text, primary_key=True)
    character_id_b: Mapped[str] = mapped_column(Text, primary_key=True)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        Index("idx_relationship_revision_lookup", "owner_user_id", "character_id_a", "character_id_b"),
    )


class RelationshipState(Base):
    __tablename__ = "relationship_state"

    character_id: Mapped[str] = mapped_column(Text, primary_key=True)
    player_id: Mapped[str] = mapped_column(Text, primary_key=True)
    affection_level: Mapped[Optional[float]] = mapped_column(Float, default=0.0, server_default=text("0.0"))
    trust_level: Mapped[Optional[float]] = mapped_column(Float, default=0.0, server_default=text("0.0"))
    current_mood: Mapped[Optional[str]] = mapped_column(Text, default="neutral", server_default=text("'neutral'"))
    updated_at: Mapped[Optional[str]] = mapped_column(Text)


# ===========================================================================
# Long-Term Facts
# ===========================================================================

class LongTermFact(Base):
    __tablename__ = "long_term_fact"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    character_id: Mapped[str] = mapped_column(Text, nullable=False)
    player_id: Mapped[str] = mapped_column(Text, nullable=False)
    fact_text: Mapped[str] = mapped_column(Text, nullable=False)
    importance: Mapped[Optional[int]] = mapped_column(Integer, default=5, server_default=text("5"))
    created_at: Mapped[Optional[str]] = mapped_column(Text)
    last_referenced: Mapped[Optional[str]] = mapped_column(Text)

    __table_args__ = (
        Index("idx_fact_lookup", "character_id", "player_id", "importance", "last_referenced"),
    )


# ===========================================================================
# Sessions & Dialogue
# ===========================================================================

class DialogueSession(Base):
    """Maps to the ``session`` table (renamed to avoid SQLAlchemy Session clash)."""

    __tablename__ = "session"

    session_id: Mapped[str] = mapped_column(Text, primary_key=True)
    character_id: Mapped[str] = mapped_column(Text, nullable=False)
    player_id: Mapped[str] = mapped_column(Text, nullable=False)
    player_name: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[Optional[str]] = mapped_column(Text)
    ended_at: Mapped[Optional[str]] = mapped_column(Text)
    status: Mapped[Optional[str]] = mapped_column(Text, default="active", server_default=text("'active'"))
    group_name: Mapped[Optional[str]] = mapped_column(Text)
    group_thread_id: Mapped[Optional[str]] = mapped_column(Text)
    story_id: Mapped[Optional[str]] = mapped_column(Text)
    locale: Mapped[str] = mapped_column(Text, nullable=False, default="zh-CN", server_default=text("'zh-CN'"))
    is_multi_character: Mapped[Optional[int]] = mapped_column(Integer, default=0, server_default=text("0"))

    __table_args__ = (
        Index("idx_session_lookup", "character_id", "player_id", "created_at"),
        Index("idx_session_multi", "is_multi_character", "player_id", "created_at"),
        Index("idx_session_group_thread", "group_thread_id", "created_at"),
    )


class MultiSessionParticipant(Base):
    __tablename__ = "multi_session_participant"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(Text, ForeignKey("session.session_id"), nullable=False)
    character_id: Mapped[str] = mapped_column(Text, nullable=False)
    join_order: Mapped[Optional[int]] = mapped_column(Integer, default=0, server_default=text("0"))
    speak_frequency: Mapped[Optional[float]] = mapped_column(Float, default=1.0, server_default=text("1.0"))
    is_active: Mapped[Optional[int]] = mapped_column(Integer, default=1, server_default=text("1"))
    message_count: Mapped[Optional[int]] = mapped_column(Integer, default=0, server_default=text("0"))
    created_at: Mapped[Optional[str]] = mapped_column(Text)
    last_spoke_at: Mapped[Optional[str]] = mapped_column(Text)

    __table_args__ = (
        UniqueConstraint("session_id", "character_id"),
        Index("idx_multi_participant", "session_id", "is_active"),
    )


class ShortTermMessage(Base):
    __tablename__ = "short_term_message"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    character_id: Mapped[Optional[str]] = mapped_column(Text)
    character_name: Mapped[Optional[str]] = mapped_column(Text)
    action: Mapped[Optional[str]] = mapped_column(Text)
    affinity_delta: Mapped[Optional[float]] = mapped_column(Float)
    trust_delta: Mapped[Optional[float]] = mapped_column(Float)
    current_affinity: Mapped[Optional[float]] = mapped_column(Float)
    current_trust: Mapped[Optional[float]] = mapped_column(Float)
    current_mood: Mapped[Optional[str]] = mapped_column(Text)
    event_notification: Mapped[Optional[str]] = mapped_column(Text)
    knowledge_sources: Mapped[Optional[str]] = mapped_column(Text)
    reply_to_message_id: Mapped[Optional[int]] = mapped_column(Integer)
    reply_to_character_id: Mapped[Optional[str]] = mapped_column(Text)
    intent: Mapped[Optional[str]] = mapped_column(Text)
    topic: Mapped[Optional[str]] = mapped_column(Text)
    trigger_source: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[Optional[str]] = mapped_column(Text)
    world_created_at: Mapped[Optional[str]] = mapped_column(Text)

    __table_args__ = (
        Index("idx_message_session", "session_id", "id"),
        Index("idx_message_character", "session_id", "character_id", "created_at"),
    )


class DialogueTurn(Base):
    __tablename__ = "dialogue_turn"

    session_id: Mapped[str] = mapped_column(Text, ForeignKey("session.session_id"), primary_key=True)
    request_id: Mapped[str] = mapped_column(Text, primary_key=True)
    player_id: Mapped[str] = mapped_column(Text, ForeignKey("users.user_id"), nullable=False)
    turn_kind: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    lease_owner: Mapped[Optional[str]] = mapped_column(Text)
    lease_expires_at: Mapped[Optional[str]] = mapped_column(Text)
    response_data: Mapped[Optional[str]] = mapped_column(Text)
    error: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)
    completed_at: Mapped[Optional[str]] = mapped_column(Text)

    __table_args__ = (
        Index("idx_dialogue_turn_session_lease", "session_id", "status", "lease_expires_at"),
    )


# ===========================================================================
# Background Jobs
# ===========================================================================

class BackgroundJob(Base):
    __tablename__ = "background_job"

    job_id: Mapped[str] = mapped_column(Text, primary_key=True)
    job_type: Mapped[str] = mapped_column(Text, nullable=False)
    dedupe_key: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    payload: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending", server_default=text("'pending'"))
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    available_at: Mapped[str] = mapped_column(Text, nullable=False)
    lease_owner: Mapped[Optional[str]] = mapped_column(Text)
    lease_expires_at: Mapped[Optional[str]] = mapped_column(Text)
    last_error: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)
    completed_at: Mapped[Optional[str]] = mapped_column(Text)

    __table_args__ = (
        Index("idx_background_job_claim", "status", "available_at", "lease_expires_at", "created_at"),
    )


# ===========================================================================
# Knowledge Base
# ===========================================================================

class KnowledgeBase(Base):
    __tablename__ = "knowledge_base"

    knowledge_base_id: Mapped[str] = mapped_column(Text, primary_key=True)
    owner_user_id: Mapped[str] = mapped_column(Text, ForeignKey("users.user_id"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    is_enabled: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default=text("1"))
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        Index("idx_knowledge_base_owner", "owner_user_id", "is_enabled", "updated_at"),
    )


class KnowledgeBinding(Base):
    __tablename__ = "knowledge_binding"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_user_id: Mapped[str] = mapped_column(Text, ForeignKey("users.user_id"), nullable=False)
    knowledge_base_id: Mapped[str] = mapped_column(Text, ForeignKey("knowledge_base.knowledge_base_id"), nullable=False)
    target_type: Mapped[str] = mapped_column(Text, nullable=False)
    target_id: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default=text("''"))
    created_at: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        UniqueConstraint("owner_user_id", "knowledge_base_id", "target_type", "target_id"),
        Index("idx_knowledge_binding_target", "owner_user_id", "target_type", "target_id", "knowledge_base_id"),
    )


class KnowledgeDocument(Base):
    __tablename__ = "knowledge_document"

    document_id: Mapped[str] = mapped_column(Text, primary_key=True)
    owner_user_id: Mapped[str] = mapped_column(Text, ForeignKey("users.user_id"), nullable=False)
    knowledge_base_id: Mapped[str] = mapped_column(Text, ForeignKey("knowledge_base.knowledge_base_id"), nullable=False)
    original_name: Mapped[str] = mapped_column(Text, nullable=False)
    media_type: Mapped[str] = mapped_column(Text, nullable=False)
    source_type: Mapped[str] = mapped_column(Text, nullable=False)
    storage_path: Mapped[Optional[str]] = mapped_column(Text)
    checksum: Mapped[str] = mapped_column(Text, nullable=False)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    status: Mapped[str] = mapped_column(Text, nullable=False, default="queued", server_default=text("'queued'"))
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    extracted_chars: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    page_count: Mapped[Optional[int]] = mapped_column(Integer)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        Index("idx_knowledge_document_base", "owner_user_id", "knowledge_base_id", "status", "created_at"),
    )


class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunk"

    chunk_id: Mapped[str] = mapped_column(Text, primary_key=True)
    owner_user_id: Mapped[str] = mapped_column(Text, ForeignKey("users.user_id"), nullable=False)
    knowledge_base_id: Mapped[str] = mapped_column(Text, ForeignKey("knowledge_base.knowledge_base_id"), nullable=False)
    document_id: Mapped[str] = mapped_column(Text, ForeignKey("knowledge_document.document_id"), nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    char_count: Mapped[int] = mapped_column(Integer, nullable=False)
    source_metadata: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        UniqueConstraint("document_id", "chunk_index"),
        Index("idx_knowledge_chunk_document", "owner_user_id", "document_id", "chunk_index"),
    )


class KnowledgeVectorCleanup(Base):
    __tablename__ = "knowledge_vector_cleanup"

    cleanup_id: Mapped[str] = mapped_column(Text, primary_key=True)
    owner_user_id: Mapped[str] = mapped_column(Text, nullable=False)
    scope_type: Mapped[str] = mapped_column(Text, nullable=False)
    scope_id: Mapped[str] = mapped_column(Text, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    last_error: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        UniqueConstraint("owner_user_id", "scope_type", "scope_id"),
        Index("idx_knowledge_vector_cleanup_pending", "updated_at", "attempts"),
    )


# ===========================================================================
# Player Event Inbox
# ===========================================================================

class PlayerEventInbox(Base):
    __tablename__ = "player_event_inbox"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    player_id: Mapped[str] = mapped_column(Text, ForeignKey("users.user_id"), nullable=False)
    event_id: Mapped[Optional[str]] = mapped_column(Text)
    character_id: Mapped[Optional[str]] = mapped_column(Text)
    session_id: Mapped[Optional[str]] = mapped_column(Text)
    event_type: Mapped[str] = mapped_column(Text, nullable=False, default="event", server_default=text("'event'"))
    group_thread_id: Mapped[Optional[str]] = mapped_column(Text)
    unread_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    title: Mapped[Optional[str]] = mapped_column(Text)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[Optional[str]] = mapped_column(Text)
    world_created_at: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    read_at: Mapped[Optional[str]] = mapped_column(Text)

    __table_args__ = (
        Index("idx_player_event_inbox_unread", "player_id", "read_at", "id"),
        Index("idx_player_group_inbox_unread", "player_id", "group_thread_id", "read_at", "id"),
        # 运行时部分唯一索引（迁移/init_db 亦创建）：群聊未读聚合按行去重
        Index(
            "idx_inbox_group_unread",
            "player_id",
            "group_thread_id",
            unique=True,
            sqlite_where=text("event_type = 'group_message' AND read_at IS NULL"),
            postgresql_where=text("event_type = 'group_message' AND read_at IS NULL"),
        ),
    )


# ===========================================================================
# Group Dialogue State
# ===========================================================================

class GroupDialogueState(Base):
    __tablename__ = "group_dialogue_state"

    group_thread_id: Mapped[str] = mapped_column(Text, primary_key=True)
    player_id: Mapped[str] = mapped_column(Text, ForeignKey("users.user_id"), nullable=False)
    current_topic: Mapped[Optional[str]] = mapped_column(Text)
    topic_source: Mapped[Optional[str]] = mapped_column(Text)
    last_reply_to_message_id: Mapped[Optional[int]] = mapped_column(Integer)
    last_reply_to_character_id: Mapped[Optional[str]] = mapped_column(Text)
    last_speaker_id: Mapped[Optional[str]] = mapped_column(Text)
    waiting_for_player: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    unresolved_hooks: Mapped[str] = mapped_column(Text, nullable=False, default="[]", server_default=text("'[]'"))
    last_autonomous_pulse_at: Mapped[Optional[str]] = mapped_column(Text)
    last_autonomous_world_at: Mapped[Optional[str]] = mapped_column(Text)
    daily_message_date: Mapped[Optional[str]] = mapped_column(Text)
    daily_message_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    lease_owner: Mapped[Optional[str]] = mapped_column(Text)
    lease_expires_at: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        Index("idx_group_dialogue_state_scan", "player_id", "lease_expires_at", "last_autonomous_pulse_at"),
    )


# ===========================================================================
# Session Summary (Mid-Term Memory)
# ===========================================================================

class SessionSummary(Base):
    __tablename__ = "session_summary"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(Text, ForeignKey("session.session_id"), nullable=False)
    character_id: Mapped[str] = mapped_column(Text, nullable=False)
    player_id: Mapped[str] = mapped_column(Text, nullable=False)
    summary_text: Mapped[str] = mapped_column(Text, nullable=False)
    message_count: Mapped[Optional[int]] = mapped_column(Integer)
    summary_status: Mapped[Optional[str]] = mapped_column(Text, default="completed", server_default=text("'completed'"))
    created_at: Mapped[Optional[str]] = mapped_column(Text)

    __table_args__ = (
        Index("idx_summary_lookup", "session_id", "created_at"),
        Index("idx_summary_player", "character_id", "player_id", "created_at"),
        # 唯一索引（迁移/init_db 亦创建）：ON CONFLICT(session_id, character_id, player_id) 依赖
        Index(
            "idx_summary_unique",
            "session_id",
            "character_id",
            "player_id",
            unique=True,
        ),
    )


# ===========================================================================
# Domain Events (Event Sourcing)
# ===========================================================================

class DomainEvent(Base):
    __tablename__ = "domain_event"

    sequence: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    event_id: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    owner_user_id: Mapped[str] = mapped_column(Text, nullable=False)
    aggregate_type: Mapped[str] = mapped_column(Text, nullable=False)
    aggregate_id: Mapped[str] = mapped_column(Text, nullable=False)
    aggregate_version: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[str] = mapped_column(Text, nullable=False)
    meta_data: Mapped[str] = mapped_column("metadata", Text, nullable=False)
    correlation_id: Mapped[Optional[str]] = mapped_column(Text)
    causation_id: Mapped[Optional[str]] = mapped_column(Text)
    session_id: Mapped[Optional[str]] = mapped_column(Text)
    group_thread_id: Mapped[Optional[str]] = mapped_column(Text)
    source_turn_id: Mapped[Optional[str]] = mapped_column(Text)
    source_message_id: Mapped[Optional[int]] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite")
    )
    world_occurred_at: Mapped[Optional[str]] = mapped_column(Text)
    recorded_at: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        UniqueConstraint("owner_user_id", "aggregate_type", "aggregate_id", "aggregate_version"),
        Index("idx_domain_event_aggregate", "owner_user_id", "aggregate_type", "aggregate_id", "aggregate_version"),
        Index("idx_domain_event_correlation", "owner_user_id", "correlation_id", "sequence"),
        Index("idx_domain_event_source_turn", "owner_user_id", "source_turn_id", "sequence"),
        Index("idx_domain_event_group_thread", "owner_user_id", "group_thread_id", "sequence"),
    )


class ProjectionCheckpoint(Base):
    __tablename__ = "projection_checkpoint"

    projector_name: Mapped[str] = mapped_column(Text, primary_key=True)
    owner_user_id: Mapped[str] = mapped_column(Text, primary_key=True)
    last_sequence: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)


class DataMigration(Base):
    __tablename__ = "data_migration"

    migration_key: Mapped[str] = mapped_column(Text, primary_key=True)
    meta_data: Mapped[str] = mapped_column("metadata", Text, nullable=False, default="{}", server_default=text("'{}'"))
    applied_at: Mapped[str] = mapped_column(Text, nullable=False)


# ===========================================================================
# Fact Claims & Story State
# ===========================================================================

class FactClaim(Base):
    __tablename__ = "fact_claim"

    claim_id: Mapped[str] = mapped_column(Text, primary_key=True)
    owner_user_id: Mapped[str] = mapped_column(Text, nullable=False)
    scope_type: Mapped[str] = mapped_column(Text, nullable=False)
    scope_id: Mapped[str] = mapped_column(Text, nullable=False)
    fact_text: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_fact_text: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_content_hash: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    source_kind: Mapped[str] = mapped_column(Text, nullable=False)
    provenance: Mapped[str] = mapped_column(Text, nullable=False, default="{}", server_default=text("'{}'"))
    source_ids: Mapped[str] = mapped_column(Text, nullable=False, default="[]", server_default=text("'[]'"))
    supersedes_claim_id: Mapped[Optional[str]] = mapped_column(Text, ForeignKey("fact_claim.claim_id"))
    superseded_by_claim_id: Mapped[Optional[str]] = mapped_column(Text, ForeignKey("fact_claim.claim_id"))
    ledger_version: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), nullable=False
    )
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)
    verified_at: Mapped[Optional[str]] = mapped_column(Text)
    retracted_at: Mapped[Optional[str]] = mapped_column(Text)

    __table_args__ = (
        CheckConstraint("scope_type IN ('character', 'group_thread', 'story')"),
        CheckConstraint("status IN ('candidate', 'verified', 'retracted', 'superseded')"),
        CheckConstraint(
            "source_kind IN ('player_message', 'knowledge_chunk', 'authored_event', 'model_inference', 'legacy')"
        ),
        UniqueConstraint("owner_user_id", "scope_type", "scope_id", "normalized_content_hash"),
        Index("idx_fact_claim_scope", "owner_user_id", "scope_type", "scope_id", "created_at", "claim_id"),
        Index("idx_fact_claim_verified", "owner_user_id", "scope_type", "scope_id", "status", "created_at", "claim_id"),
    )


class StoryState(Base):
    __tablename__ = "story_state"

    owner_user_id: Mapped[str] = mapped_column(Text, primary_key=True)
    story_id: Mapped[str] = mapped_column(Text, primary_key=True)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    progress: Mapped[float] = mapped_column(Float, nullable=False, default=0, server_default=text("0"))
    terminal_reason: Mapped[Optional[str]] = mapped_column(Text)
    ledger_version: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), nullable=False
    )
    started_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)
    completed_at: Mapped[Optional[str]] = mapped_column(Text)
    failed_at: Mapped[Optional[str]] = mapped_column(Text)

    __table_args__ = (
        CheckConstraint("status IN ('active', 'completed', 'failed')"),
        Index("idx_story_state_status", "owner_user_id", "status", "updated_at", "story_id"),
    )


# ===========================================================================
# Shared & Group Memory
# ===========================================================================

class SharedMemory(Base):
    __tablename__ = "shared_memory"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    owner_user_id: Mapped[str] = mapped_column(Text, nullable=False)
    character_a_id: Mapped[str] = mapped_column(Text, nullable=False)
    character_b_id: Mapped[str] = mapped_column(Text, nullable=False)
    observer_character_id: Mapped[Optional[str]] = mapped_column(Text)
    target_character_id: Mapped[Optional[str]] = mapped_column(Text)
    memory_kind: Mapped[str] = mapped_column(Text, nullable=False, default="legacy_archived", server_default=text("'legacy_archived'"))
    memory_text: Mapped[str] = mapped_column(Text, nullable=False)
    context: Mapped[Optional[str]] = mapped_column(Text)
    importance: Mapped[Optional[float]] = mapped_column(Float, default=0.5, server_default=text("0.5"))
    created_at: Mapped[Optional[str]] = mapped_column(Text)
    last_referenced: Mapped[Optional[str]] = mapped_column(Text)
    reference_count: Mapped[Optional[int]] = mapped_column(Integer, default=0, server_default=text("0"))

    __table_args__ = (
        Index("idx_shared_memory_owner_pair", "owner_user_id", "character_a_id", "character_b_id", "importance"),
        Index(
            "idx_shared_memory_directional",
            "owner_user_id",
            "observer_character_id",
            "target_character_id",
            "importance",
        ),
    )


class GroupMemory(Base):
    __tablename__ = "group_memory"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    session_id: Mapped[str] = mapped_column(Text, nullable=False)
    memory_text: Mapped[str] = mapped_column(Text, nullable=False)
    participants: Mapped[Optional[str]] = mapped_column(Text)
    context: Mapped[Optional[str]] = mapped_column(Text)
    importance: Mapped[Optional[float]] = mapped_column(Float, default=0.5, server_default=text("0.5"))
    created_at: Mapped[Optional[str]] = mapped_column(Text)
    last_referenced: Mapped[Optional[str]] = mapped_column(Text)
    reference_count: Mapped[Optional[int]] = mapped_column(Integer, default=0, server_default=text("0"))


# ===========================================================================
# Memory Curve (World-Time Decay Projection)
# ===========================================================================

class MemoryCurveState(Base):
    __tablename__ = "memory_curve_state"

    owner_user_id: Mapped[str] = mapped_column(Text, primary_key=True)
    character_id: Mapped[str] = mapped_column(Text, primary_key=True)
    memory_type: Mapped[str] = mapped_column(Text, primary_key=True)
    memory_id: Mapped[str] = mapped_column(Text, primary_key=True)
    anchor_strength: Mapped[float] = mapped_column(Float, nullable=False, default=1.0, server_default=text("1.0"))
    stability_days: Mapped[float] = mapped_column(Float, nullable=False)
    anchor_elapsed_seconds: Mapped[float] = mapped_column(Float, nullable=False, default=0.0, server_default=text("0.0"))
    elapsed_decay_seconds: Mapped[float] = mapped_column(Float, nullable=False, default=0.0, server_default=text("0.0"))
    world_time_watermark: Mapped[str] = mapped_column(Text, nullable=False)
    reinforcement_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    source_kind: Mapped[str] = mapped_column(Text, nullable=False, default="legacy", server_default=text("'legacy'"))
    importance: Mapped[float] = mapped_column(Float, nullable=False, default=0.5, server_default=text("0.5"))
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        Index("idx_memory_curve_character", "owner_user_id", "character_id", "memory_type"),
    )


class MemoryCurveReinforcement(Base):
    __tablename__ = "memory_curve_reinforcement"

    owner_user_id: Mapped[str] = mapped_column(Text, primary_key=True)
    character_id: Mapped[str] = mapped_column(Text, primary_key=True)
    memory_type: Mapped[str] = mapped_column(Text, primary_key=True)
    memory_id: Mapped[str] = mapped_column(Text, primary_key=True)
    evidence_id: Mapped[str] = mapped_column(Text, primary_key=True)
    world_occurred_at: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["owner_user_id", "character_id", "memory_type", "memory_id"],
            [
                "memory_curve_state.owner_user_id",
                "memory_curve_state.character_id",
                "memory_curve_state.memory_type",
                "memory_curve_state.memory_id",
            ],
        ),
    )
