from typing import Annotated, Any
from uuid import uuid4

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    field_serializer,
    field_validator,
    model_validator,
)


class _FrozenDict(dict):
    def _immutable(self, *args: Any, **kwargs: Any) -> None:
        raise TypeError("domain event JSON fields are immutable")

    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        memo[id(self)] = self
        return self

    def __reduce__(self):
        return self.__class__, (dict(self),)

    __delitem__ = _immutable
    __ior__ = _immutable
    __setitem__ = _immutable
    clear = _immutable
    pop = _immutable
    popitem = _immutable
    setdefault = _immutable
    update = _immutable


def _freeze_json(value: JsonValue) -> Any:
    if isinstance(value, dict):
        return _FrozenDict({
            key: _freeze_json(item)
            for key, item in value.items()
        })
    if isinstance(value, list):
        return tuple(_freeze_json(item) for item in value)
    return value


def _thaw_json(value: Any) -> JsonValue:
    if isinstance(value, dict):
        return {
            key: _thaw_json(item)
            for key, item in value.items()
        }
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value


PositiveStrictInt = Annotated[int, Field(strict=True, gt=0)]


class NewDomainEvent(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        allow_inf_nan=False,
        extra="forbid",
    )

    owner_user_id: str
    aggregate_type: str
    aggregate_id: str
    event_type: str
    payload: dict[str, JsonValue] = Field(default_factory=dict)
    metadata: dict[str, JsonValue] = Field(default_factory=dict)
    correlation_id: str | None = None
    causation_id: str | None = None
    session_id: str | None = None
    group_thread_id: str | None = None
    source_turn_id: str | None = None
    source_message_id: PositiveStrictInt | None = None
    world_occurred_at: str | None = None
    event_id: str = Field(default_factory=lambda: uuid4().hex)

    @field_validator(
        "owner_user_id",
        "aggregate_type",
        "aggregate_id",
        "event_type",
        "event_id",
    )
    @classmethod
    def validate_identity(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("domain event identity fields must not be blank")
        return normalized

    @field_validator(
        "correlation_id",
        "causation_id",
        "session_id",
        "group_thread_id",
        "source_turn_id",
        "world_occurred_at",
    )
    @classmethod
    def normalize_optional_identity(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("domain event identity fields must not be blank")
        return normalized

    @model_validator(mode="after")
    def freeze_json_fields(self):
        object.__setattr__(self, "payload", _freeze_json(self.payload))
        object.__setattr__(self, "metadata", _freeze_json(self.metadata))
        return self

    @field_serializer("payload", "metadata")
    def serialize_json_fields(self, value: JsonValue) -> JsonValue:
        return _thaw_json(value)


class StoredDomainEvent(NewDomainEvent):
    sequence: PositiveStrictInt
    aggregate_version: PositiveStrictInt
    recorded_at: str

    @field_validator("recorded_at")
    @classmethod
    def validate_recorded_at(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("recorded_at must not be blank")
        return normalized
