"""Replace saved ComfyUI image graphs with the 4K H3 CFG 1 workflow."""

from copy import deepcopy
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision = "b42ad6e7c311"
down_revision = "d04e9a317b62"
branch_labels = None
depends_on = None

# Frozen API graph from the workflow supplied for this migration.
_WORKFLOW = {
    "1": {
        "inputs": {
            "unet_name": "minimax_h3_image_pruned_int8_convrot.safetensors",
            "weight_dtype": "default",
        },
        "class_type": "UNETLoader",
        "_meta": {"title": "主模型 · MiniMax H3-Image INT8"},
    },
    "2": {
        "inputs": {
            "clip_name": "qwen3vl_32b_minimax_h3_int8_convrot.safetensors",
            "type": "minimax",
            "device": "default",
        },
        "class_type": "CLIPLoader",
        "_meta": {"title": "文本编码器 · Qwen3-VL INT8"},
    },
    "3": {
        "inputs": {"vae_name": "minimax_h3_image_vae_fp16.safetensors"},
        "class_type": "VAELoader",
        "_meta": {"title": "VAE · MiniMax H3-Image FP16"},
    },
    "5": {
        "inputs": {
            "prompt": "Ultraman Taro uses Codex to write code.",
            "width": 4096,
            "height": 4096,
            "clip": ["2", 0],
            "vae": ["3", 0],
            "references": ["11", 0],
        },
        "class_type": "H3MultiRefConditioning",
        "_meta": {"title": "MiniMax H3-Image · 0 图文生图 / 多图参考"},
    },
    "7": {
        "inputs": {
            "seed": 42,
            "steps": 6,
            "cfg": 1,
            "sampler_name": "euler",
            "scheduler": "simple",
            "denoise": 1,
            "model": ["1", 0],
            "positive": ["5", 0],
            "negative": ["12", 0],
            "latent_image": ["5", 1],
        },
        "class_type": "KSampler",
        "_meta": {"title": "KSampler · CFG 1.0"},
    },
    "8": {
        "inputs": {"samples": ["7", 0], "vae": ["3", 0]},
        "class_type": "VAEDecode",
        "_meta": {"title": "VAE 解码"},
    },
    "9": {
        "inputs": {
            "filename_prefix": "MiniMax-H3-Image/multi_ref_0_15_4k_cfg1",
            "images": ["8", 0],
        },
        "class_type": "SaveImage",
        "_meta": {"title": "保存图片"},
    },
    "11": {
        "inputs": {"refs_json": "[]"},
        "class_type": "H3MultiRefPanel",
        "_meta": {"title": "H3 Multi REF · 0–15 张图片"},
    },
    "12": {
        "inputs": {"conditioning": ["5", 0]},
        "class_type": "ConditioningZeroOut",
        "_meta": {"title": "负向条件置零（不编码负面提示词）"},
    },
}

_ENDPOINT = sa.table(
    "custom_endpoint",
    sa.column("id", sa.Integer),
    sa.column("kind", sa.String),
    sa.column("media_type", sa.String),
    sa.column("definition", sa.JSON),
    sa.column("updated_at", sa.DateTime(timezone=True)),
)
_BACKUP = sa.table(
    "comfyui_image_workflow_backup",
    sa.column("endpoint_id", sa.Integer),
    sa.column("workflow", sa.JSON),
    sa.column("bindings", sa.JSON),
)


def _target(node: str, field: str | None = None) -> dict:
    target = {"node": node, "class_type": _WORKFLOW[node]["class_type"]}
    return target if field is None else {**target, "input": field}


def _replacement(old_workflow: dict, old_bindings: dict) -> tuple[dict, dict]:
    workflow = deepcopy(_WORKFLOW)
    bindings = {
        "prompt": [_target("5", "prompt")],
        "width": [_target("5", "width")],
        "height": [_target("5", "height")],
        "seed": [{**_target("7", "seed"), "policy": "random"}],
        "output": [_target("9")],
    }
    if old_bindings.get("reference_images"):
        bindings["reference_images"] = [_target("11", "refs_json")]

    targets = {
        (str(t["node"]), t["input"]) for t in old_bindings.get("negative_prompt", [])
    }
    for node in old_workflow.values():
        link = node.get("inputs", {}).get("negative")
        if isinstance(link, list) and len(link) == 2:
            source = str(link[0])
            inputs = old_workflow.get(source, {}).get("inputs", {})
            targets.update(
                (source, key)
                for key in ("text", "prompt", "negative_prompt")
                if key in inputs
            )
    excluded = []
    for node_id, key in sorted(targets):
        value = old_workflow.get(node_id, {}).get("inputs", {}).get(key)
        if isinstance(value, str) and value.strip() and value.strip() not in excluded:
            excluded.append(value.strip())
    if excluded:
        workflow["5"]["_meta"]["juling_prompt_requirements"] = (
            "Keep the image free of " + "; ".join(excluded) + "."
        )
    return workflow, bindings


def _update(
    connection, endpoint_id: int, definition: dict, workflow: dict, bindings: dict
) -> None:
    connection.execute(
        sa.update(_ENDPOINT)
        .where(_ENDPOINT.c.id == endpoint_id)
        .values(
            definition={**definition, "workflow": workflow, "bindings": bindings},
            updated_at=datetime.now(UTC),
        )
    )


def upgrade() -> None:
    op.create_table(
        _BACKUP.name,
        sa.Column("endpoint_id", sa.Integer, primary_key=True),
        sa.Column("workflow", sa.JSON, nullable=False),
        sa.Column("bindings", sa.JSON, nullable=False),
    )
    connection = op.get_bind()
    rows = connection.execute(
        sa.select(_ENDPOINT.c.id, _ENDPOINT.c.definition).where(
            _ENDPOINT.c.kind == "comfyui", _ENDPOINT.c.media_type == "image"
        )
    ).all()
    for endpoint_id, definition in rows:
        workflow, bindings = definition["workflow"], definition["bindings"]
        replacement = _replacement(workflow, bindings)
        connection.execute(
            _BACKUP.insert().values(
                endpoint_id=endpoint_id, workflow=workflow, bindings=bindings
            )
        )
        _update(connection, endpoint_id, definition, *replacement)


def downgrade() -> None:
    connection = op.get_bind()
    rows = connection.execute(
        sa.select(
            _BACKUP.c.endpoint_id,
            _BACKUP.c.workflow,
            _BACKUP.c.bindings,
            _ENDPOINT.c.definition,
        ).join(_ENDPOINT, _ENDPOINT.c.id == _BACKUP.c.endpoint_id)
    ).all()
    for endpoint_id, workflow, bindings, definition in rows:
        if (definition.get("workflow"), definition.get("bindings")) == _replacement(
            workflow, bindings
        ):
            _update(connection, endpoint_id, definition, workflow, bindings)
    op.drop_table(_BACKUP.name)
