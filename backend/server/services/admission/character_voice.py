"""Admission shared by character reference-audio generation entry points."""

from lib.catalog.errors import ModelNotInCatalogError
from lib.config.resolver import ConfigResolver, NoAvailableProviderError, ProviderModel
from lib.generation.generation_queue_client import TaskSpec
from lib.infra.api_errors import BadRequestError, NotFoundError
from lib.project.asset_types import resolve_asset_key, validate_asset_name

VOICE_SAMPLE_TEXT_MAX_LENGTH = 200


async def resolve_voice_sample_backend(project: dict, resolver: ConfigResolver) -> ProviderModel:
    try:
        return await resolver.resolve_audio_backend(project, None)
    except ModelNotInCatalogError:
        raise
    except NoAvailableProviderError as exc:
        raise BadRequestError("audio_default_model_not_set") from exc
    except ValueError as exc:
        raise BadRequestError("audio_provider_not_configured") from exc


def build_voice_sample_spec(
    project: dict, name: str, text: str, *, voice: str, voice_design: bool, source: str,
) -> TaskSpec:
    text = text.strip()
    if not text:
        raise BadRequestError("prompt_text_empty")
    if len(text) > VOICE_SAMPLE_TEXT_MAX_LENGTH:
        raise BadRequestError("voice_sample_text_too_long", max_length=VOICE_SAMPLE_TEXT_MAX_LENGTH)
    try:
        name = validate_asset_name(name)
    except ValueError as exc:
        raise BadRequestError("asset_invalid_name", name=name) from exc
    characters = project.get("characters") or {}
    key = resolve_asset_key(characters, name)
    if key is None:
        raise NotFoundError("character_not_found", name=name)
    if voice_design and not (characters[key].get("voice_style") or "").strip():
        raise BadRequestError("voice_sample_design_style_required")
    return TaskSpec.from_request(
        task_type="voice_sample",
        media_type="audio",
        resource_id=name,
        prompt=text,
        extra_payload={"voice": "" if voice_design else voice.strip(), "voice_design": voice_design, "auto_save": True},
        source=source,
    )
