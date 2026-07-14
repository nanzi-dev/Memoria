"""Shared locale rules for sessions, prompts, and speech."""

from typing import Literal


Locale = Literal["zh-CN", "en-US"]
DEFAULT_LOCALE: Locale = "zh-CN"
SUPPORTED_LOCALES: tuple[Locale, ...] = ("zh-CN", "en-US")

STT_LANGUAGE_BY_LOCALE: dict[Locale, str] = {
    "zh-CN": "zh",
    "en-US": "en",
}


def language_instruction(locale: Locale) -> str:
    if locale == "en-US":
        language_rule = "All dialogue content must be written in American English."
    else:
        language_rule = "所有 dialogue 对话内容必须使用简体中文。"

    return (
        "\n\n【最高优先级会话语言约束】\n"
        f"{language_rule}\n"
        "Keep JSON keys, action values, event protocol names, mood enum values, "
        "and database enum values exactly as defined; do not translate them."
    )
