"""
历史会话回放。
"""

from __future__ import annotations


def build_replay(session: dict, messages: list[dict], step: int | None = None) -> dict:
    total_steps = len(messages)
    if step is None:
        replay_messages = messages
        current_step = total_steps
    else:
        current_step = max(0, min(step, total_steps))
        replay_messages = messages[:current_step]

    state_timeline = []
    last_state = None
    for index, message in enumerate(messages, start=1):
        state = {
            "affinity": message.get("current_affinity"),
            "trust": message.get("current_trust"),
            "mood": message.get("current_mood"),
        }
        if any(value is not None for value in state.values()):
            state_timeline.append({
                "step": index,
                "message_id": message.get("message_id"),
                "state": state,
                "delta": {
                    "affinity": message.get("affinity_delta"),
                    "trust": message.get("trust_delta"),
                },
                "action": message.get("action"),
                "event_notification": message.get("event_notification"),
            })
            last_state = state

    return {
        "session": session,
        "current_step": current_step,
        "total_steps": total_steps,
        "messages": replay_messages,
        "state_timeline": state_timeline,
        "current_state": last_state,
        "state_tracking_available": bool(state_timeline),
    }
