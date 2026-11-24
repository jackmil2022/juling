"""Submit an ad story draft to the desktop form without writing project files."""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from server.agent_toolset.declaration import BLOCKED, ToolDeclaration
from server.tool_runtime import CallerContext, ProjectScope, Services, ToolOutcome, ToolRequest

type DraftText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class AdStorySetting(BaseModel):
    model_config = ConfigDict(extra="forbid")

    synopsis: DraftText = Field(description="一句话梗概，突出核心冲突和行动或转折")
    genre: DraftText = Field(description="题材与风格")
    theme: DraftText = Field(description="核心主题")
    world_setting: DraftText = Field(description="时代、场景和必要规则")


async def submit_ad_story_setting(
    request: ToolRequest[AdStorySetting], _scope: ProjectScope, _caller: CallerContext, _services: Services
) -> ToolOutcome[AdStorySetting]:
    return ToolOutcome(value=request.value)


SUBMIT_AD_STORY_SETTING = ToolDeclaration(
    name="submit_ad_story_setting",
    description="仅在桌面要求回填广告故事设定时调用，一次提交四项草稿，不修改项目或脚本。",
    request_model=AdStorySetting,
    migration=BLOCKED,
    domain_key="ad_story_setting",
    handler=submit_ad_story_setting,
)
