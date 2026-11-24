"""Host-neutral read-only tool that hands asset sheets and storyboard images to an Agent so it can look at them.

Images are read from the chosen version snapshot, or the metadata-owned current image when no history
is registered, downscaled to JPEG in memory and returned as image content blocks after the JSON.
Nothing is written and no model is called.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

from lib.project.asset_types import ASSET_SPECS, resolve_asset_key
from lib.artifacts.version_manager import VersionManager
from lib.final_cut.basis import version_snapshot
from lib.infra.image_utils import compress_image_bytes
from lib.infra.path_safety import try_safe_join
from lib.material.work_files import local_work_files
from lib.script.script_editor import ScriptEditError
from lib.script.script_models import get_generated_assets
from lib.script.storyboard_sequence import get_storyboard_items
from server.agent_toolset.declaration import ToolImage
from server.media_tools.context import tool_error, tool_problem
from server.media_tools.image_edits import EditableResourceType
from server.services.tasks.image_edit_tasks import edit_version_resource_type, resolve_current_image_pointer
from server.tool_runtime import CallerContext, ProjectScope, Services, ToolOutcome, ToolRequest

logger = logging.getLogger(__name__)

_OPERATION = "inspect_images"

MAX_IMAGES_PER_CALL = 20
MAX_IMAGE_EDGE = 2000
_JPEG_QUALITY = 85

LABEL_ZH: dict[str, str] = {
    "character": "角色资产图",
    "scene": "场景资产图",
    "prop": "道具资产图",
    "product": "商品资产图",
    "storyboard": "参考图",
    "character_derivative": "角色衍生资产图",
}

type ImageStatus = Literal["ok", "image_missing", "image_unreadable"]


class InspectImagesRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    resource_type: EditableResourceType = Field(description="要看的图片类型；一次调用只看同一类型")
    ids: list[str] = Field(
        min_length=1,
        description=(
            "要看的 ID 列表：资产为资产名称；storyboard 为分镜 ID（segment_id / scene_id，如 E1S05）；"
            "character_derivative 为「本体名/衍生名」"
        ),
    )
    version: StrictInt | None = Field(
        default=None,
        ge=1,
        description="版本号，对列表中每一项都取这个版本；省略时取各项的 current 版本",
    )
    image_source: Literal["asset_sheet", "product_reference"] = Field(
        default="asset_sheet",
        description="asset_sheet 看生成资产图；product_reference 看商品登记的全部原图，仅适用于 product 且不传 version",
    )

    @model_validator(mode="after")
    def _validate_image_source(self) -> InspectImagesRequest:
        if self.image_source == "product_reference" and self.resource_type != "product":
            raise ValueError("product_reference 仅适用于 resource_type=product")
        if self.image_source == "product_reference" and self.version is not None:
            raise ValueError("查看商品原图时不能指定 version")
        return self


@dataclass(frozen=True, slots=True)
class InspectedImage:
    id: str
    version: int | None
    status: ImageStatus
    #: 该项现有的全部版本号，用来发现还没看过的历史版本。
    available_versions: tuple[int, ...] = ()
    #: 生成该版本时登记的提示词；手动上传等没有登记提示词的版本为 None。
    prompt: str | None = None
    detail: str | None = None
    jpeg: bytes | None = None
    reference_index: int | None = None


@dataclass(frozen=True, slots=True)
class InspectImagesResult:
    resource_type: str
    images: tuple[InspectedImage, ...]
    image_source: str = "asset_sheet"


def _storyboard_images(services: Services, project_name: str) -> dict[str, str | None]:
    """项目全部剧本里的分镜 ID 与登记的当前图；参考生视频的剧本没有分镜。"""
    found: dict[str, str | None] = {}
    for script_name in sorted(services.projects.list_scripts(project_name)):
        try:
            script = services.projects.load_script_readonly(project_name, script_name)
            items, id_field, *_ = get_storyboard_items(script)
        except (ScriptEditError, ValueError, OSError):
            # 读不出的剧本无法证明分镜存在，跳过；其余剧本照常判定
            logger.warning("查找分镜时跳过无法读取的剧本: %s", script_name, exc_info=True)
            continue
        for item in items:
            if isinstance(item, dict) and item.get(id_field):
                pointer = get_generated_assets(item).get("storyboard_image")
                found[str(item[id_field])] = pointer if isinstance(pointer, str) and pointer else None
    return found


def _resolve_ids(
    services: Services, project_name: str, resource_type: str, ids: list[str]
) -> tuple[list[tuple[str, str | None]], list[str]]:
    """返回归一后的 ID 与登记的当前图，以及不存在的请求 ID。"""
    if resource_type == "storyboard":
        known = _storyboard_images(services, project_name)
        return [(item_id, known[item_id]) for item_id in ids if item_id in known], [
            item_id for item_id in ids if item_id not in known
        ]
    project = services.projects.load_project(project_name)
    resolved: list[tuple[str, str | None]] = []
    missing: list[str] = []
    for item_id in ids:
        try:
            resolved.append(resolve_current_image_pointer(project, resource_type, item_id, None))
        except KeyError:
            # 包括不合「本体名/衍生名」格式的衍生 ID
            missing.append(item_id)
    return resolved, missing


def _available_versions(versions: VersionManager, resource_type: str, resource_id: str) -> list[int]:
    return [
        record["version"]
        for record in versions.get_versions(resource_type, resource_id).get("versions", [])
        if isinstance(record, Mapping) and isinstance(record.get("version"), int)
    ]


def _read_image(path: Path) -> tuple[bytes | None, str | None]:
    """读快照并缩成 JPEG；读不出或解不开时返回原因。"""
    try:
        return compress_image_bytes(path.read_bytes(), max_long_edge=MAX_IMAGE_EDGE, quality=_JPEG_QUALITY), None
    except OSError as exc:
        return None, f"读取失败：{exc}"
    except ValueError:
        return None, "图片无法解码"


def _inspect_product_reference_images(
    services: Services, project_name: str, ids: list[str]
) -> ToolOutcome[InspectImagesResult]:
    project = services.projects.load_project(project_name)
    product_bucket = project.get(ASSET_SPECS["product"].bucket_key)
    project_path = services.projects.get_project_path(project_name)
    products: list[tuple[str, list[Any]]] = []
    missing: list[str] = []
    for product_id in ids:
        key = resolve_asset_key(product_bucket, product_id)
        product = product_bucket.get(key) if isinstance(product_bucket, dict) and key is not None else None
        if not isinstance(product, dict):
            missing.append(product_id)
            continue
        references = product.get("reference_images")
        products.append((product_id, references if isinstance(references, list) else []))
    if missing:
        return tool_problem(
            f"商品资产不存在：{', '.join(missing)}",
            code="resource_not_found",
            params={"resource_type": "product", "ids": missing},
        )

    targets = [
        (product_id, index, reference)
        for product_id, references in products
        for index, reference in (enumerate(references, 1) if references else [(1, None)])
    ]
    if len(targets) > MAX_IMAGES_PER_CALL:
        return tool_problem(
            f"商品原图共 {len(targets)} 张，超过每次 {MAX_IMAGES_PER_CALL} 张的上限",
            code="image_limit_exceeded",
            params={"max_images_per_call": MAX_IMAGES_PER_CALL},
        )

    images: list[InspectedImage] = []
    for product_id, index, reference in targets:
        path = try_safe_join(project_path, reference, require_file=True) if isinstance(reference, str) else None
        if path is None:
            images.append(
                InspectedImage(
                    id=product_id,
                    version=None,
                    status="image_missing",
                    detail="未登记商品原图或原图文件缺失",
                    reference_index=index,
                )
            )
            continue
        jpeg, detail = _read_image(path)
        images.append(
            InspectedImage(
                id=product_id,
                version=None,
                status="ok" if jpeg is not None else "image_unreadable",
                detail=detail,
                jpeg=jpeg,
                reference_index=index,
            )
        )
    return ToolOutcome(
        value=InspectImagesResult(resource_type="product", images=tuple(images), image_source="product_reference")
    )


async def inspect_images(
    request: ToolRequest[InspectImagesRequest],
    scope: ProjectScope,
    _caller: CallerContext,
    services: Services,
) -> ToolOutcome[InspectImagesResult]:
    resource_type = request.value.resource_type
    ids = list(dict.fromkeys(request.value.ids))
    if len(ids) > MAX_IMAGES_PER_CALL:
        return tool_problem(
            f"一次最多看 {MAX_IMAGES_PER_CALL} 张图，本次请求了 {len(ids)} 张，请分批调用",
            code="image_limit_exceeded",
            params={"max_images_per_call": MAX_IMAGES_PER_CALL},
        )
    label = LABEL_ZH[resource_type]
    try:
        if request.value.image_source == "product_reference":
            return await asyncio.to_thread(_inspect_product_reference_images, services, scope.project_name, ids)
        resolved, missing = await asyncio.to_thread(_resolve_ids, services, scope.project_name, resource_type, ids)
        if missing:
            return tool_problem(
                f"{label}的对象不存在：{', '.join(missing)}",
                code="resource_not_found",
                params={"resource_type": resource_type, "ids": missing},
            )

        version_type = edit_version_resource_type(resource_type)

        def inspect_all() -> list[InspectedImage] | ToolOutcome[Any]:
            versions = VersionManager(services.projects.get_project_path(scope.project_name))
            project_path = services.projects.get_project_path(scope.project_name)
            targets: list[tuple[str, int | None, list[int], str | None]] = []
            for item_id, pointer in resolved:
                available = _available_versions(versions, version_type, item_id)
                version = request.value.version
                if version is None:
                    current = versions.get_current_version(version_type, item_id)
                    version = current if current > 0 else None
                elif version not in available:
                    return tool_problem(
                        f"{label}「{item_id}」没有版本 v{version}；现有版本：{', '.join(map(str, available)) or '无'}",
                        code="version_not_found",
                        params={"id": item_id, "available_versions": available},
                    )
                targets.append((item_id, version, available, pointer))
            images: list[InspectedImage] = []
            for item_id, version, available, pointer in targets:
                found = (
                    version_snapshot(project_path, versions, version_type, item_id, version)
                    if version is not None
                    else None
                )
                # 仅当前产物归档可省略历史；无版本时只读登记的当前图，不补写版本记录。
                if version is None and pointer:
                    current_path = try_safe_join(project_path, pointer, require_file=True)
                    found = (current_path, {}) if current_path is not None else None
                if found is None:
                    images.append(
                        InspectedImage(
                            id=item_id, version=version, status="image_missing", available_versions=tuple(available)
                        )
                    )
                    continue
                path, record = found
                prompt = record.get("prompt")
                jpeg, detail = _read_image(path)
                images.append(
                    InspectedImage(
                        id=item_id,
                        version=version,
                        status="ok" if jpeg is not None else "image_unreadable",
                        available_versions=tuple(available),
                        prompt=prompt if isinstance(prompt, str) and prompt else None,
                        detail=detail,
                        jpeg=jpeg,
                    )
                )
            return images

        def snapshot_files() -> tuple[Path, list[str]]:
            project_path = services.projects.get_project_path(scope.project_name)
            versions = VersionManager(project_path)
            files: list[str] = []
            for item_id, _pointer in resolved:
                version = request.value.version
                if version is None:
                    version = versions.get_current_version(version_type, item_id)
                for record in versions.get_versions(version_type, item_id).get("versions", []):
                    if isinstance(record, Mapping) and record.get("version") == version:
                        file = record.get("file")
                        if isinstance(file, str):
                            files.append(file)
            return project_path, files

        # 要看的版本快照是缓存已清理的远端内容版本时先取回，读图期间登记使用
        project_path, files = await asyncio.to_thread(snapshot_files)
        async with local_work_files(project_path, files):
            inspected = await asyncio.to_thread(inspect_all)
        if isinstance(inspected, ToolOutcome):
            return inspected
        return ToolOutcome(
            value=InspectImagesResult(
                resource_type=resource_type, images=tuple(inspected), image_source=request.value.image_source
            )
        )
    except Exception as exc:
        return tool_error(_OPERATION, exc)


def inspect_images_projection(value: InspectImagesResult) -> dict[str, Any]:
    image_number = 0
    images: list[dict[str, Any]] = []
    for image in value.images:
        entry: dict[str, Any] = {
            "id": image.id,
            "version": image.version,
            "available_versions": list(image.available_versions),
            "status": image.status,
        }
        if image.jpeg is not None:
            image_number += 1
            entry["image"] = image_number
        if image.reference_index is not None:
            entry["reference_index"] = image.reference_index
        if image.prompt is not None:
            entry["prompt"] = image.prompt
        if image.detail is not None:
            entry["detail"] = image.detail
        images.append(entry)
    return {
        "inspect_images": {
            "resource_type": value.resource_type,
            "image_source": value.image_source,
            "images": images,
        }
    }


def inspect_images_images(value: InspectImagesResult) -> list[ToolImage]:
    return [ToolImage(data=image.jpeg, mime_type="image/jpeg") for image in value.images if image.jpeg is not None]


def inspect_images_summary(value: InspectImagesResult) -> str:
    unseen = [
        f"{image.id} 原图{image.reference_index}"
        if image.reference_index is not None
        else image.id
        for image in value.images
        if image.jpeg is None
    ]
    label = "商品原图" if value.image_source == "product_reference" else LABEL_ZH[value.resource_type]
    text = f"已取出 {len(value.images) - len(unseen)} 张{label}，图片按 image 序号附在后面"
    return f"{text}；没有可看的图：{', '.join(unseen)}" if unseen else text


__all__ = [
    "MAX_IMAGES_PER_CALL",
    "MAX_IMAGE_EDGE",
    "InspectImagesRequest",
    "InspectImagesResult",
    "inspect_images",
    "inspect_images_images",
    "inspect_images_projection",
    "inspect_images_summary",
]
