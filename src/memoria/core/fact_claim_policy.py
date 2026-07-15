import hashlib
import json
import re
import unicodedata
from typing import Any


CLAIM_SOURCE_KINDS = frozenset({
    "player_message",
    "knowledge_chunk",
    "authored_event",
    "model_inference",
    "legacy",
})
ADMIN_VERIFICATION_SOURCE_KIND = "admin_verification"
EVIDENCE_SOURCE_KINDS = CLAIM_SOURCE_KINDS | {
    ADMIN_VERIFICATION_SOURCE_KIND,
}

HIGH_RISK_MARKERS = (
    "身份",
    "本人",
    "真实姓名",
    "签名",
    "签署",
    "罪责",
    "有罪",
    "凶手",
    "罪犯",
    "主谋",
    "指使",
    "授权",
    "批准",
    "代理",
    "代表",
    "安装者",
    "操作者",
    "执行者",
    "杀害",
    "谋杀",
    "作案",
    "identity",
    "signed",
    "signature",
    "guilty",
    "culprit",
    "murderer",
    "killed",
    "murdered",
    "responsible for",
    "authorized",
    "approved",
    "agent",
    "acting on behalf",
)


def normalize_fact_text(fact_text: str) -> str:
    original = str(fact_text or "").strip()
    if not original:
        raise ValueError("fact_text must not be blank")
    normalized = unicodedata.normalize("NFKC", original).casefold()
    stable_chars = []
    for char in normalized:
        category = unicodedata.category(char)
        stable_chars.append(
            char if category[0] in {"L", "M", "N"} else " "
        )
    return re.sub(r"\s+", " ", "".join(stable_chars)).strip()


def hash_fact_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def deterministic_fact_claim_id(
    owner_user_id: str,
    scope_type: str,
    scope_id: str,
    normalized_content_hash: str,
) -> str:
    identity = json.dumps(
        [
            owner_user_id,
            scope_type,
            scope_id,
            normalized_content_hash,
        ],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return f"fact_{hash_fact_text(identity)}"


def derive_fact_claim_identity(
    owner_user_id: str,
    scope_type: str,
    scope_id: str,
    fact_text: str,
) -> dict[str, str]:
    normalized_fact_text = normalize_fact_text(fact_text)
    content_hash = hash_fact_text(fact_text)
    normalized_content_hash = hash_fact_text(normalized_fact_text)
    return {
        "normalized_fact_text": normalized_fact_text,
        "content_hash": content_hash,
        "normalized_content_hash": normalized_content_hash,
        "claim_id": deterministic_fact_claim_id(
            owner_user_id,
            scope_type,
            scope_id,
            normalized_content_hash,
        ),
    }


def clean_source_ids(source_ids: list[str]) -> list[str]:
    if type(source_ids) is not list or not source_ids:
        raise ValueError("source_ids must be a non-empty list of strings")
    if any(
        type(source_id) is not str or not source_id.strip()
        for source_id in source_ids
    ):
        raise ValueError("source_ids must contain only non-empty strings")
    return sorted({source_id.strip() for source_id in source_ids})


def normalize_evidence_entry(evidence: dict[str, Any]) -> dict[str, Any]:
    if type(evidence) is not dict:
        raise ValueError("fact claim evidence must be an object")
    source_kind = evidence.get("source_kind")
    if source_kind not in EVIDENCE_SOURCE_KINDS:
        raise ValueError(f"unsupported fact claim source_kind: {source_kind}")
    direct_support = evidence.get("direct_support")
    if not isinstance(direct_support, bool):
        raise ValueError("direct_support must be a boolean")
    details = evidence.get("details", {})
    if type(details) is not dict:
        raise ValueError("fact claim evidence details must be an object")
    return {
        "source_kind": source_kind,
        "source_ids": clean_source_ids(evidence.get("source_ids")),
        "direct_support": direct_support,
        "details": dict(details),
    }


def evaluate_verification(
    normalized_fact_text: str,
    evidence: list[dict[str, Any]],
) -> dict[str, Any]:
    if type(evidence) is not list:
        raise ValueError("fact claim evidence must be a list")
    normalized_evidence = [
        normalize_evidence_entry(item)
        for item in evidence
    ]
    high_risk = any(
        marker in normalized_fact_text
        for marker in HIGH_RISK_MARKERS
    )
    qualifying_source_ids = set()
    all_source_ids = set()
    for item in normalized_evidence:
        source_kind = item["source_kind"]
        source_ids = item["source_ids"]
        all_source_ids.update(source_ids)
        qualifies = (
            source_kind
            in {"authored_event", ADMIN_VERIFICATION_SOURCE_KIND}
            or (
                source_kind in {"player_message", "knowledge_chunk"}
                and item["direct_support"] is True
            )
        )
        if qualifies:
            qualifying_source_ids.update(source_ids)
    required_sources = 2 if high_risk else 1
    return {
        "verified": len(qualifying_source_ids) >= required_sources,
        "high_risk": high_risk,
        "required_sources": required_sources,
        "qualifying_source_ids": sorted(qualifying_source_ids),
        "source_ids": sorted(all_source_ids),
    }
