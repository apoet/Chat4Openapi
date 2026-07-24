import hashlib
import json
import logging
from time import perf_counter
from typing import Any, Sequence

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from chat4openapi.api.errors import ApiError
from chat4openapi.auto_agentify.catalog import (
    build_operation_catalog,
    find_body_schema_issues,
    is_high_impact,
)
from chat4openapi.auto_agentify.planner import (
    AutoAgentifyPlanner,
    PlanGenerationError,
)
from chat4openapi.auto_agentify.progress import ProgressEvent
from chat4openapi.db.serialized_write import serialized_write
from chat4openapi.llm.client import LlmProviderError
from chat4openapi.models import (
    Agent,
    AgentSkill,
    ApiSource,
    LlmProvider,
    Skill,
    SkillTool,
    Tool,
)
from chat4openapi.schemas.auto_agentify import (
    AutoAgentifyResponse,
    GeneratedAgentResponse,
    GeneratedSkillResponse,
    GenerationPlan,
)
from chat4openapi.schemas.tools import ApiSourceSummary
from chat4openapi.security.encryption import SecretCipher
from chat4openapi.tools.candidates import ToolCandidate, build_candidates
from chat4openapi.tools.openapi_loader import (
    OpenAPIImportError,
    load_openapi,
    normalize_openapi,
)

logger = logging.getLogger(__name__)


class AutoAgentifyService:
    def __init__(
        self,
        *,
        planner: AutoAgentifyPlanner,
        cipher: SecretCipher,
    ) -> None:
        self._planner = planner
        self._cipher = cipher

    async def generate(
        self,
        *,
        db: Session,
        provider_id: int,
        name: str,
        raw_document: bytes,
        source_url: str | None,
        base_url: str | None,
        allow_private_networks: bool,
        reporter: Any | None = None,
        allowed_system_capabilities: list[str] | tuple[str, ...] = (),
        custom_capability_labels: list[str] | tuple[str, ...] = (),
        result_language: str = "en-US",
    ) -> AutoAgentifyResponse:
        started_at = perf_counter()
        await _emit(
            reporter,
            ProgressEvent(
                kind="document_loaded",
                phase="loading_document",
                progress=5,
                message_key="autoAgentify.events.documentLoaded",
                params={"bytes": len(raw_document)},
            ),
        )
        provider = db.get(LlmProvider, provider_id)
        if (
            provider is None
            or provider.deleted_at is not None
            or not provider.enabled
        ):
            raise ApiError(409, "auto_agentify.provider_unavailable")
        try:
            spec = load_openapi(raw_document)
            normalized = normalize_openapi(spec, source_url=source_url)
        except OpenAPIImportError as exc:
            raise ApiError(
                422, "auto_agentify.openapi_invalid", reason=str(exc)
            ) from exc
        await _emit(
            reporter,
            ProgressEvent(
                kind="openapi_validated",
                phase="parsing_openapi",
                progress=15,
                message_key="autoAgentify.events.openapiValidated",
                params={},
            ),
        )
        effective_base_url = base_url
        if effective_base_url is None:
            servers = normalized.get("servers", [])
            effective_base_url = servers[0].get("url") if servers else None
        if not effective_base_url:
            raise ApiError(422, "tools.base_url_required")
        try:
            candidates = await build_candidates(normalized, effective_base_url)
        except (KeyError, ValueError) as exc:
            raise ApiError(
                422, "auto_agentify.openapi_unsupported", reason=str(exc)
            ) from exc
        catalog = build_operation_catalog(normalized, candidates)
        body_schema_issues = find_body_schema_issues(normalized)
        await _emit(
            reporter,
            ProgressEvent(
                kind="operations_discovered",
                phase="cataloging_operations",
                progress=22,
                message_key="autoAgentify.events.operationsDiscovered",
                params={"count": len(catalog)},
                metrics={"operation_count": len(catalog)},
            ),
        )
        if body_schema_issues:
            visible_issues = [
                issue.as_dict() for issue in body_schema_issues[:20]
            ]
            await _emit(
                reporter,
                ProgressEvent(
                    kind="body_schema_warning",
                    phase="cataloging_operations",
                    progress=22,
                    message_key="autoAgentify.events.bodySchemaWarning",
                    params={
                        "count": len(body_schema_issues),
                        "issues": visible_issues,
                        "truncated": len(body_schema_issues) > len(visible_issues),
                    },
                    metrics={
                        "body_schema_issue_count": len(body_schema_issues),
                        "body_schema_issues": visible_issues,
                    },
                ),
            )
        secret = self._cipher.decrypt_json(provider.encrypted_api_key)
        try:
            plan = await self._planner.plan(
                provider_type=provider.provider_type,
                base_url=provider.base_url,
                api_key=str(secret["api_key"]),
                model=provider.default_model,
                catalog=catalog,
                reporter=reporter,
                source_name=name,
                allowed_system_capabilities=allowed_system_capabilities,
                custom_capability_labels=custom_capability_labels,
                result_language=result_language,
            )
        except PlanGenerationError as exc:
            raise ApiError(422, "auto_agentify.plan_invalid") from exc
        except LlmProviderError as exc:
            raise ApiError(
                502, "auto_agentify.provider_failed", status=exc.status_code
            ) from exc
        await _emit(
            reporter,
            ProgressEvent(
                kind="plan_validated",
                phase="validating_plan",
                progress=78,
                message_key="autoAgentify.events.planValidated",
                params={
                    "skill_count": len(plan.skills),
                    "agent_count": len(plan.agents),
                },
                metrics={
                    "skill_count": len(plan.skills),
                    "agent_count": len(plan.agents),
                },
            ),
        )
        await _emit(
            reporter,
            ProgressEvent(
                kind="persistence_started",
                phase="persisting_configuration",
                progress=85,
                message_key="autoAgentify.events.persistenceStarted",
                params={},
            ),
        )

        try:
            with serialized_write(db):
                result = self._persist(
                    db=db,
                    provider_id=provider_id,
                    name=name,
                    raw_document=raw_document,
                    spec=spec,
                    candidates=candidates,
                    plan=plan,
                    source_url=source_url,
                    base_url=effective_base_url,
                    allow_private_networks=allow_private_networks,
                    catalog=catalog,
                    result_language=result_language,
                )
        except IntegrityError as exc:
            raise ApiError(409, "auto_agentify.conflict") from exc
        await _emit(
            reporter,
            ProgressEvent(
                kind="configuration_created",
                phase="persisting_configuration",
                progress=98,
                message_key="autoAgentify.events.configurationCreated",
                params={
                    "tool_count": result.enabled_tool_count,
                    "skill_count": len(result.skills),
                    "agent_count": len(result.agents),
                },
            ),
        )
        await _emit(
            reporter,
            ProgressEvent(
                kind="completed",
                phase="completed",
                progress=100,
                message_key="autoAgentify.events.completed",
                params={},
            ),
        )
        logger.info(
            "auto_agentify.completed provider_id=%s document_hash=%s "
            "operations=%s skills=%s agents=%s elapsed_ms=%s",
            provider_id,
            hashlib.sha256(raw_document).hexdigest(),
            len(candidates),
            len(result.skills),
            len(result.agents),
            round((perf_counter() - started_at) * 1_000),
        )
        return result

    def _persist(
        self,
        *,
        db: Session,
        provider_id: int,
        name: str,
        raw_document: bytes,
        spec: dict[str, Any],
        candidates: Sequence[ToolCandidate],
        plan: GenerationPlan,
        source_url: str | None,
        base_url: str,
        allow_private_networks: bool,
        catalog,
        result_language: str,
    ) -> AutoAgentifyResponse:
        source = ApiSource(
            name=name,
            source_type="openapi",
            base_url=base_url,
            document_url=source_url,
            spec_snapshot=json.dumps(
                spec, ensure_ascii=False, separators=(",", ":")
            ),
            spec_hash=hashlib.sha256(raw_document).hexdigest(),
            allow_private_networks=allow_private_networks,
        )
        db.add(source)
        db.flush()

        tools = [
            Tool(
                api_source_id=source.id,
                operation_key=candidate.operation_key,
                name=candidate.name,
                description=candidate.description,
                input_schema=candidate.input_schema,
                execution_schema=candidate.execution_schema,
                enabled=False,
            )
            for candidate in candidates
        ]
        db.add_all(tools)
        db.flush()
        tools_by_key = {tool.operation_key: tool for tool in tools}

        existing_skill_names = set(
            db.scalars(select(Skill.name))
        )
        existing_agent_names = set(
            db.scalars(select(Agent.name))
        )
        skill_rows: dict[str, Skill] = {}
        generated_skills: list[GeneratedSkillResponse] = []
        provenance = _auto_generated_provenance(name, result_language)
        for skill_plan in plan.skills:
            allocated_name = _allocate_name(
                skill_plan.name, name, existing_skill_names
            )
            skill = Skill(
                name=allocated_name,
                description=_append_provenance(
                    skill_plan.description, provenance
                ),
                system_prompt=skill_plan.system_prompt,
                running=True,
            )
            db.add(skill)
            db.flush()
            bound_tools = [
                tools_by_key[operation_key]
                for operation_key in skill_plan.operation_keys
            ]
            for tool in bound_tools:
                tool.enabled = True
            db.add_all(
                SkillTool(
                    skill_id=skill.id,
                    tool_id=tool.id,
                    position=position,
                )
                for position, tool in enumerate(bound_tools)
            )
            skill_rows[skill_plan.name] = skill
            generated_skills.append(
                GeneratedSkillResponse(
                    id=skill.id,
                    name=skill.name,
                    description=skill.description,
                    tool_ids=[tool.id for tool in bound_tools],
                    value=skill_plan.value,
                )
            )

        high_impact_keys = {
            item.operation_key for item in catalog if is_high_impact(item)
        }
        skill_plan_by_name = {item.name: item for item in plan.skills}
        generated_agents: list[GeneratedAgentResponse] = []
        for agent_plan in plan.agents:
            allocated_name = _allocate_name(
                agent_plan.name, name, existing_agent_names
            )
            bound_skills = [
                skill_rows[skill_name] for skill_name in agent_plan.skill_names
            ]
            referenced_operations = {
                operation_key
                for skill_name in agent_plan.skill_names
                for operation_key in skill_plan_by_name[skill_name].operation_keys
            }
            mode = (
                "human_in_loop"
                if referenced_operations & high_impact_keys
                else agent_plan.mode
            )
            agent = Agent(
                name=allocated_name,
                description=_append_provenance(
                    agent_plan.responsibility, provenance
                ),
                enabled=True,
                is_default=False,
                system_prompt=agent_plan.system_prompt,
                provider_id=provider_id,
                model=None,
                mode=mode,
                max_iterations=agent_plan.max_iterations,
            )
            db.add(agent)
            db.flush()
            db.add_all(
                AgentSkill(
                    agent_id=agent.id,
                    skill_id=skill.id,
                    position=position,
                )
                for position, skill in enumerate(bound_skills)
            )
            generated_agents.append(
                GeneratedAgentResponse(
                    id=agent.id,
                    name=agent.name,
                    description=agent.description,
                    skill_ids=[skill.id for skill in bound_skills],
                    mode=mode,
                    provider_id=provider_id,
                    value=agent_plan.value,
                    use_cases=agent_plan.use_cases,
                )
            )

        db.flush()
        return AutoAgentifyResponse(
            source=ApiSourceSummary.model_validate(source),
            imported_tool_count=len(tools),
            enabled_tool_count=sum(tool.enabled for tool in tools),
            skills=generated_skills,
            agents=generated_agents,
        )


def _auto_generated_provenance(
    source_name: str, result_language: str
) -> str:
    normalized_source = " ".join(source_name.split())
    if result_language == "zh-CN":
        return f"根据「{normalized_source}」来源自动生成。"
    return f'Automatically generated from the "{normalized_source}" source.'


def _append_provenance(description: str, provenance: str) -> str:
    punctuation = ("。", ".", "！", "!", "？", "?")
    separator = (
        ""
        if description.rstrip().endswith(punctuation)
        else ("。" if provenance.startswith("根据") else ".")
    )
    suffix = f"{separator} {provenance}"
    return f"{description.rstrip()[: 4_000 - len(suffix)]}{suffix}"


def _allocate_name(base: str, source_name: str, used: set[str]) -> str:
    normalized_base = " ".join(base.split())
    if normalized_base not in used:
        used.add(normalized_base)
        return normalized_base
    suffix = f" ({' '.join(source_name.split())})"
    candidate = f"{normalized_base[:160 - len(suffix)]}{suffix}"
    sequence = 2
    while candidate in used:
        numbered_suffix = f" ({' '.join(source_name.split())} {sequence})"
        candidate = f"{normalized_base[:160 - len(numbered_suffix)]}{numbered_suffix}"
        sequence += 1
    used.add(candidate)
    return candidate


async def _emit(reporter: Any | None, event: ProgressEvent) -> None:
    if reporter is not None:
        await reporter.emit(event)
