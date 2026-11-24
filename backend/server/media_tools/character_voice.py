"""Agent entry point for background character reference-audio generation."""

import asyncio

from pydantic import BaseModel, ConfigDict, Field

from lib.backends.audio_backends.base import AudioCapability
from lib.generation.generation_result import GenerationResultBuilder, GenerationSelectionMode, record_batch_outcomes
from lib.i18n import _ as translate
from lib.infra.api_errors import ApiError, BadRequestError
from server.media_tools.context import (
    GenerationToolValue,
    generation_batch_submission_outcome,
    generation_result_outcome,
    tool_error,
    tool_problem,
)
from server.services.admission.character_voice import build_voice_sample_spec, resolve_voice_sample_backend
from server.services.tasks.generation_context import audio_backend_profile
from server.tool_runtime import CallerContext, ProjectScope, Services, ToolOutcome, ToolRequest, submit_media_generation

_OPERATION = "generate_character_reference_audio"


class GenerateCharacterReferenceAudioRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1, description="项目内角色名")
    text: str = Field(min_length=1, description="实际朗读的简短台词，建议成品在 2 至 10 秒内")
    voice: str = Field(default="", description="预设音色 ID，省略时自动匹配")
    voice_design: bool | None = Field(
        default=None, description="是否根据角色声音风格设计音色。省略时按模型能力决定。"
    )


async def generate_character_reference_audio(
    scope: ProjectScope,
    request: ToolRequest[GenerateCharacterReferenceAudioRequest],
    caller: CallerContext,
    services: Services,
) -> ToolOutcome[GenerationToolValue]:
    req = request.value
    try:
        project = await asyncio.to_thread(services.projects.load_project, scope.project_name)
        backend = await resolve_voice_sample_backend(project, services.capabilities)
        profile = await audio_backend_profile(backend.provider_id, backend.model_id)
        supports_design = AudioCapability.VOICE_DESIGN in profile.capabilities
        voice_design = supports_design and not req.voice.strip() if req.voice_design is None else req.voice_design
        if voice_design and not supports_design:
            raise BadRequestError("voice_sample_design_unsupported")
        spec = build_voice_sample_spec(
            project, req.name, req.text, voice=req.voice, voice_design=voice_design, source=caller.source,
        )
        builder = GenerationResultBuilder(_OPERATION, GenerationSelectionMode.EXPLICIT)
        submitted = await submit_media_generation(
            scope=scope,
            caller=caller,
            services=services,
            operation=_OPERATION,
            preflight=builder.build(),
            pending_ids=[spec.resource_id],
            specs=[spec],
        )
        if submitted.successes is None or submitted.failures is None:
            return generation_batch_submission_outcome(submitted.batch)
        record_batch_outcomes(builder, successes=submitted.successes, failures=submitted.failures)
        return generation_result_outcome(builder.build(), batch_id=submitted.batch.batch_id)
    except ApiError as exc:
        return tool_problem(translate(exc.key, **exc.params), code=exc.key, params=exc.params)
    except Exception as exc:
        return tool_error(_OPERATION, exc)
