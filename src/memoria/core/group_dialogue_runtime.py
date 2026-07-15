"""逻辑群聊的离线自主对话扫描与租约执行。"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone

from memoria.core import character_loader, multi_character_memory, world_clock
from memoria.core.config import configs
from memoria.core.multi_character_orchestrator import MultiCharacterOrchestrator
from memoria.db import repository

logger = logging.getLogger(__name__)

REAL_COOLDOWN = timedelta(minutes=2)
WORLD_COOLDOWN = timedelta(minutes=20)
DAILY_AUTONOMOUS_MESSAGE_LIMIT = 24
MAX_PULSE_MESSAGES = 3


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed


def _active_character_ids(session: dict) -> list[str]:
    participants = repository.get_session_participants(
        session["session_id"],
        only_active=False,
    )
    return [
        participant["character_id"]
        for participant in participants
        if participant.get("character_id")
        and participant.get("is_active")
        and repository.is_character_card_active(
            session["player_id"],
            participant["character_id"],
        )
    ]


def _story_motivation(
    state: dict,
    player_id: str,
    character_ids: list[str],
) -> tuple[str | None, str | None]:
    hooks = state.get("unresolved_hooks") or []
    if hooks:
        topic = next(
            (str(hook.get("topic") or "").strip() for hook in hooks if isinstance(hook, dict)),
            "",
        )
        return "npc_follow_up", topic or "延续尚未解决的角色提问或剧情钩子"

    motivations = []
    for character_id in character_ids:
        try:
            card = character_loader.load_character_card(character_id, player_id)
        except Exception as exc:
            logger.warning("自主群聊加载角色卡失败: character=%s error=%s", character_id, exc)
            continue
        goals = getattr(card, "goals_and_motivations", None)
        current_goals = list(getattr(goals, "current_goals", []) or [])
        long_term_goals = list(getattr(goals, "long_term_goals", []) or [])
        if current_goals or long_term_goals:
            name = card.meta.display_name or card.meta.name
            motivations.append(
                f"{name}的目标：{'; '.join(str(item) for item in (current_goals or long_term_goals)[:3])}"
            )
    if motivations:
        return "goal", "；".join(motivations)[:1000]

    current_topic = str(state.get("current_topic") or "").strip()
    if current_topic and not state.get("waiting_for_player"):
        return "idle", f"群聊空闲后自然延续当前话题：{current_topic}"
    return None, None


def _ordinary_pulse_due(
    state: dict,
    snapshot: world_clock.WorldClockSnapshot,
) -> bool:
    if snapshot.paused:
        return False
    last_real = _parse_iso(state.get("last_autonomous_pulse_at"))
    if last_real and snapshot.real_now - last_real < REAL_COOLDOWN:
        return False
    last_world = _parse_iso(state.get("last_autonomous_world_at"))
    if last_world and snapshot.world_now - last_world < WORLD_COOLDOWN:
        return False
    today = snapshot.real_now.date().isoformat()
    count = int(state.get("daily_message_count") or 0)
    return state.get("daily_message_date") != today or count < DAILY_AUTONOMOUS_MESSAGE_LIMIT


def _ensure_carrier_session(
    state: dict,
    latest_session: dict,
    character_ids: list[str],
) -> dict:
    if latest_session.get("status") == "active":
        return latest_session

    session_id = str(uuid.uuid4())
    try:
        player_character = repository.get_or_create_user_character_card(
            state["player_id"]
        )
    except Exception as exc:
        logger.warning("自主群聊加载玩家角色卡失败: %s", exc)
        player_character = None
    player_name = (
        (player_character or {}).get("display_name")
        or latest_session.get("player_name")
        or "玩家"
    )
    carrier, _ = repository.get_or_create_active_multi_character_session(
        session_id=session_id,
        player_id=state["player_id"],
        player_name=player_name,
        character_ids=character_ids,
        group_name=latest_session.get("group_name"),
        group_thread_id=state["group_thread_id"],
    )
    return carrier


def run_group_dialogue_pulse(
    group_thread_id: str,
    *,
    trigger_source: str | None = None,
    trigger_text: str | None = None,
    initial_speaker_id: str | None = None,
    explicit_event: bool = False,
    now: datetime | None = None,
    lease_owner: str | None = None,
) -> list[dict]:
    """尝试领取并执行一个线程脉冲；未到期或无动机时返回空列表。"""
    state = repository.get_group_dialogue_state(group_thread_id)
    latest_session = repository.get_latest_group_thread_session(group_thread_id)
    if not state or not latest_session:
        return []

    character_ids = _active_character_ids(latest_session)
    if len(character_ids) < 2:
        return []

    real_now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    snapshot = world_clock.get_clock_snapshot(state["player_id"], real_now=real_now)
    if not explicit_event:
        if not _ordinary_pulse_due(state, snapshot):
            return []
        trigger_source, trigger_text = _story_motivation(
            state,
            state["player_id"],
            character_ids,
        )
        if not trigger_source:
            return []

    owner = lease_owner or f"group-dialogue:{uuid.uuid4().hex}"
    lease_seconds = max(300, int(configs.world_clock_scheduler_lease_seconds))
    if not repository.claim_group_dialogue_state(
        group_thread_id,
        lease_owner=owner,
        lease_expires_at=(real_now + timedelta(seconds=lease_seconds)).isoformat(),
        real_now_iso=real_now.isoformat(),
    ):
        return []

    try:
        carrier = _ensure_carrier_session(state, latest_session, character_ids)
        orchestrator = MultiCharacterOrchestrator(carrier["session_id"])
        today = real_now.date().isoformat()
        used_today = (
            int(state.get("daily_message_count") or 0)
            if state.get("daily_message_date") == today
            else 0
        )
        max_messages = (
            MAX_PULSE_MESSAGES
            if explicit_event
            else min(MAX_PULSE_MESSAGES, DAILY_AUTONOMOUS_MESSAGE_LIMIT - used_today)
        )
        if max_messages <= 0:
            repository.release_group_dialogue_state(group_thread_id, lease_owner=owner)
            return []
        responses = orchestrator.run_dialogue_pulse(
            trigger_source=trigger_source or "event",
            trigger_text=trigger_text or "推进当前剧情事件",
            initial_speaker_id=initial_speaker_id,
            max_messages=max_messages,
            clock_snapshot=snapshot,
            persist_state=False,
            persist_messages=False,
            extract_memory=False,
        )
        pulse_state = getattr(orchestrator, "last_pulse_state", {})
        responses = repository.commit_group_dialogue_pulse(
            group_thread_id,
            carrier["session_id"],
            state["player_id"],
            responses,
            lease_owner=owner,
            real_now_iso=real_now.isoformat(),
            world_now_iso=snapshot.world_now.isoformat(),
            autonomous_message_count=0 if explicit_event else len(responses),
            daily_message_date=real_now.date().isoformat(),
            current_topic=pulse_state.get("current_topic") or state.get("current_topic"),
            topic_source=pulse_state.get("topic_source") or trigger_source,
            last_reply_to_message_id=pulse_state.get("last_reply_to_message_id"),
            last_reply_to_character_id=pulse_state.get("last_reply_to_character_id"),
            last_speaker_id=pulse_state.get("last_speaker_id"),
            waiting_for_player=bool(pulse_state.get("waiting_for_player")),
            unresolved_hooks=pulse_state.get("unresolved_hooks") or [],
            group_name=carrier.get("group_name"),
        )
        if responses:
            try:
                multi_character_memory.process_dialogue_pulse_memories(
                    session_id=carrier["session_id"],
                    recent_messages=[
                        {
                            "role": "assistant",
                            "content": response.get("dialogue", ""),
                            "character_id": response.get("character_id"),
                            "character_name": response.get("character_name"),
                        }
                        for response in responses
                    ],
                    character_ids=character_ids,
                    player_id=state["player_id"],
                )
            except Exception:
                logger.error(
                    "自主群聊脉冲记忆提取失败: thread=%s",
                    group_thread_id,
                    exc_info=True,
                )
        return responses
    except Exception:
        repository.release_group_dialogue_state(group_thread_id, lease_owner=owner)
        raise


def run_autonomous_group_dialogues(
    *,
    now: datetime | None = None,
    limit: int = 100,
) -> int:
    """扫描所有逻辑群聊，并执行已到期且有剧情动机的普通自主脉冲。"""
    generated = 0
    for state in repository.list_group_dialogue_states(limit=limit):
        try:
            generated += len(
                run_group_dialogue_pulse(
                    state["group_thread_id"],
                    now=now,
                )
            )
        except Exception:
            logger.error(
                "自主群聊脉冲失败: thread=%s",
                state.get("group_thread_id"),
                exc_info=True,
            )
    return generated


def run_event_group_dialogue_pulse(
    session_id: str,
    *,
    event_text: str,
    character_id: str | None = None,
) -> list[dict]:
    """显式剧情事件触发脉冲，不受普通冷却和每日预算限制。"""
    session = repository.get_session(session_id)
    if not session or not session.get("is_multi_character"):
        return []
    return run_group_dialogue_pulse(
        session.get("group_thread_id") or session_id,
        trigger_source="event",
        trigger_text=event_text,
        initial_speaker_id=character_id,
        explicit_event=True,
    )
