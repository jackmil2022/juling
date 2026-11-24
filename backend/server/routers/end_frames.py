"""分镜尾帧设置/清除路由。

设置有两条通道、同一落点：``/end-frame/upload`` 收 multipart 上传，``/end-frame/select``
按项目内相对路径选已有图片；两者都归一为 PNG 快照写到 ``end_frames/scene_{id}.png``。
``DELETE /end-frame`` 清除（删快照 + 字段置空）。

字段 ``end_frame_image`` 只由这里写入：通用剧本 PATCH 白名单刻意不含它，避免原样写值
绕过快照复制、重新引入悬空引用与越界路径。
"""

from __future__ import annotations

import logging
from collections.abc import Generator
from contextlib import contextmanager

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

from lib.infra.api_errors import ApiError, NotFoundError
from lib.generation.generation_admission import generation_admission_lock
from lib.generation.generation_queue import get_generation_queue
from lib.infra.async_thread import run_sync_transaction
from lib.project.project_change_hints import project_change_source
from lib.project.project_manager import get_project_manager
from lib.script.storyboard_sequence import find_storyboard_item, get_storyboard_items
from lib.script.script_editor import ScriptEditError
from server.error_handlers import script_edit_detail
from server.i18n import Translator
from server.auth import CurrentUser
from server.services.currency.upload_finalize import (
    UploadTooLargeError,
    UploadValidationError,
    validate_upload,
)
from server.services.project.end_frame import (
    EndFrameError,
    clear_end_frame,
    set_end_frame_from_bytes,
    set_end_frame_from_project_image,
)

logger = logging.getLogger(__name__)

router = APIRouter()


class SelectEndFrameRequest(BaseModel):
    script_file: str
    source_path: str


@contextmanager
def _translated_errors(script_file: str, _t: Translator) -> Generator[None]:
    """三个端点共用的领域错误 → HTTP 映射。"""
    try:
        yield
    except (EndFrameError, UploadValidationError) as e:
        raise HTTPException(status_code=e.status_code, detail=_t(e.key, **e.params)) from e
    except FileNotFoundError as exc:
        # 不回传 str(exc)：load_script 的异常信息含服务器绝对路径
        raise NotFoundError("script_not_found", name=script_file) from exc
    except ScriptEditError as e:
        raise HTTPException(status_code=400, detail=script_edit_detail(e, _t)) from e
    except (HTTPException, ApiError):
        raise
    except Exception as e:
        # 不回传 str(e)：未预期异常的消息可能含服务器路径等内部细节，堆栈进日志即可
        logger.exception("请求处理失败")
        raise HTTPException(status_code=500, detail=_t("internal_server_error")) from e


@router.post("/projects/{project_name}/shots/{shot_id}/end-frame/upload")
async def upload_end_frame(
    project_name: str,
    shot_id: str,
    script_file: str,
    _t: Translator,
    file: UploadFile = File(...),
):
    """上传任意图片作为该分镜的尾帧。"""
    with _translated_errors(script_file, _t):
        max_bytes = validate_upload(file.filename, file.size, kind="image")
        # 限定读入内存的字节数：Content-Length 缺失/被绕过时不至于 OOM
        content = await file.read(max_bytes + 1)
        if len(content) > max_bytes:
            raise UploadTooLargeError(max_bytes)

        relative = await set_end_frame_from_bytes(
            project_name=project_name,
            script_file=script_file,
            shot_id=shot_id,
            content=content,
        )
        return {"success": True, "end_frame_image": relative}


@router.post("/projects/{project_name}/shots/{shot_id}/end-frame/select")
async def select_end_frame(
    project_name: str,
    shot_id: str,
    req: SelectEndFrameRequest,
    _t: Translator,
):
    """指定项目内已有图片的相对路径作为该分镜的尾帧（快照复制，不建立引用）。"""
    with _translated_errors(req.script_file, _t):
        relative = await set_end_frame_from_project_image(
            project_name=project_name,
            script_file=req.script_file,
            shot_id=shot_id,
            source_path=req.source_path,
        )
        return {"success": True, "end_frame_image": relative}


@router.delete("/projects/{project_name}/shots/{shot_id}/end-frame")
async def delete_end_frame(
    project_name: str,
    shot_id: str,
    script_file: str,
    _t: Translator,
):
    """清除该分镜的尾帧：删快照文件并把字段置空。"""
    with _translated_errors(script_file, _t):
        await clear_end_frame(project_name=project_name, script_file=script_file, shot_id=shot_id)
        return {"success": True}


@router.delete("/projects/{project_name}/shots/{shot_id}/storyboard-image")
async def delete_storyboard_image(
    project_name: str, shot_id: str, script_file: str, _t: Translator, user: CurrentUser,
    shot_range: str | None = None,
):
    def clear() -> None:
        manager = get_project_manager()
        with project_change_source("webui"), manager.locked_script(project_name, script_file) as script:
            items, id_field, _, _, _ = get_storyboard_items(script)
            matched = find_storyboard_item(items, id_field, shot_id)
            if matched is None:
                raise EndFrameError("segment_not_found", status_code=404, id=shot_id)
            item = matched[0]
            assets = item.setdefault("generated_assets", {})
            images = assets.get("storyboard_images") or {}
            if shot_range:
                removed = images.pop(shot_range, None)
                if removed and assets.get("storyboard_image") == removed:
                    assets["storyboard_image"] = None
                label = shot_range
            else:
                assets["storyboard_image"] = None
                images = {}
                label = "*"
            assets["storyboard_images"] = images
            deleted = assets.setdefault("deleted_storyboard_shots", [])
            if label not in deleted:
                deleted.append(label)
            manager.update_scene_status(item)

    with _translated_errors(script_file, _t):
        async with generation_admission_lock(project_name=project_name, script_file=script_file, resource_id=shot_id):
            active = await get_generation_queue().get_active_tasks_for_resources(
                project_name=project_name, task_type="storyboard", resource_ids=[shot_id],
                script_file=script_file, user_id=user.id,
            )
            if active:
                raise ApiError("generation_active_task_conflict", status_code=409)
            await run_sync_transaction(clear)
        return {"success": True}
