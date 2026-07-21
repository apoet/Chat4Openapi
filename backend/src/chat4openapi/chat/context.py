import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from chat4openapi.llm.client import CanonicalMessage, CanonicalToolCall
from chat4openapi.models import AgentConfig, ChatMessage, Conversation, Skill


def build_agent_context(
    session: Session,
    agent: AgentConfig,
    conversation: Conversation,
    candidate_skills: list[Skill],
) -> list[CanonicalMessage]:
    messages = [CanonicalMessage(role="system", content=agent.system_prompt)]
    messages.append(
        CanonicalMessage(
            role="system",
            content=json.dumps(
                {
                    "skills": [
                        {
                            "id": skill.id,
                            "name": skill.name,
                            "description": skill.description or "",
                        }
                        for skill in candidate_skills
                    ]
                },
                ensure_ascii=False,
                separators=(",", ":"),
            ),
        )
    )
    skills_by_id = {skill.id: skill for skill in candidate_skills}
    for skill_id in conversation.loaded_skill_ids:
        skill = skills_by_id.get(skill_id)
        if skill is not None:
            messages.append(CanonicalMessage(role="system", content=skill.system_prompt))
    stored = session.scalars(
        select(ChatMessage)
        .where(ChatMessage.conversation_id == conversation.id)
        .order_by(ChatMessage.sequence)
    ).all()
    messages.extend(message_from_record(message) for message in stored)
    return messages


def message_from_record(message: ChatMessage) -> CanonicalMessage:
    content = message.content
    calls = [
        CanonicalToolCall(
            id=str(item["id"]),
            name=str(item["name"]),
            arguments=dict(item.get("arguments") or {}),
        )
        for item in content.get("tool_calls", [])
    ]
    return CanonicalMessage(
        role=message.role,
        content=content.get("text", ""),
        tool_call_id=_optional_string(content.get("tool_call_id")),
        name=_optional_string(content.get("name")),
        tool_calls=calls,
    )


def _optional_string(value: Any) -> str | None:
    return str(value) if value is not None else None
