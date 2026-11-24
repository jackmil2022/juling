import type { CSSProperties } from "react";
import { cn } from "cn";
import { AlertTriangle, Captions, Loader2, Pause, Play, StepBack, StepForward } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { Toggle } from "@/components/ui/toggle";
import { TooltipIconButton } from "@/components/canvas/timeline/TooltipIconButton";
import type { EditClip } from "@/types/edit-timeline";
import type { PreviewAspect } from "@/utils/preview-aspect";

import { TIMELINE_FPS, frameStepTarget, timelineFrameAt, transitionOpacity, type PlaybackPlan } from "./playback-schedule";
import { unitPositionLabel } from "./timeline-view";
import { subtitleAt, subtitleLayout, type PlacedSubtitle } from "./preview-tracks";
import type { TimelinePlayback } from "./useTimelinePlayback";

function formatTimecode(time: number): string {
  const frame = timelineFrameAt(time);
  const seconds = Math.floor(frame / TIMELINE_FPS);
  return [Math.floor(seconds / 60), seconds % 60, frame % TIMELINE_FPS]
    .map((part) => String(part).padStart(2, "0"))
    .join(":");
}

interface EditTimelinePlayerProps {
  plan: PlaybackPlan;
  playback: TimelinePlayback;
  aspect: PreviewAspect;
  /** 当前片段；定格与占位期间同样有值，没有可播放片段时为 undefined。 */
  current: EditClip | undefined;
  /** 视频单元 ID → 它在本集里的当前位置。 */
  positions: ReadonlyMap<string, number>;
  trimIgnored: boolean;
  subtitles: readonly PlacedSubtitle[];
  showSubtitles: boolean;
  onToggleSubtitles: () => void;
}

/**
 * 播放画面与播放控制：两个 `<video>` 叠放，只显示当前那一个；字幕按剪映草稿的样式比例叠在画面上。
 * 画面按所在格子的宽高缩放：舞台是尺寸容器，画框取「容器宽」与「容器高 × 画幅比」中较小的一个。
 */
export function EditTimelinePlayer({
  plan,
  playback,
  aspect,
  current,
  positions,
  trimIgnored,
  subtitles,
  showSubtitles,
  onToggleSubtitles,
}: EditTimelinePlayerProps) {
  const { t } = useTranslation("dashboard");
  const segment = plan.segments[playback.index];
  const showVideo = Boolean(segment?.hasVideo);
  const opacity = segment ? transitionOpacity(segment, playback.t) : 1;
  const hasTransitions = plan.segments.some((item) => item.fadeOut > 0);
  const subtitle = showSubtitles ? subtitleAt(subtitles, playback.t) : null;
  const layout = subtitleLayout(aspect);
  const portrait = aspect === "9:16";

  return (
    <div
      role="region"
      aria-label={t("edit_view_player_aria")}
      tabIndex={0}
      onKeyDown={(event) => {
        if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey || event.defaultPrevented) return;
        if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
        event.preventDefault();
        playback.stepFrame(event.key === "ArrowLeft" ? -1 : 1);
      }}
      className="focus-ring flex h-full min-h-0 flex-col gap-2"
    >
      <div className="@container-size relative flex min-h-0 flex-1 items-center justify-center">
        <div
          className={cn(
            "@container-size relative overflow-hidden rounded-lg bg-black",
            portrait
              ? "aspect-[9/16] w-[min(100cqw,calc(100cqh*9/16))]"
              : "aspect-video w-[min(100cqw,calc(100cqh*16/9))]",
          )}
        >
          <div
            className="pointer-events-none absolute inset-0 isolate opacity-(--stage-opacity)"
            style={{ "--stage-opacity": showVideo ? opacity : 0 } as CSSProperties}
          >
            {playback.videoRefs.map((ref, slot) => (
              // react-doctor-disable-next-line react-doctor/media-has-caption -- 字幕由剪辑时间线的字幕轨叠加显示，不走 <track>
              <video // eslint-disable-line jsx-a11y/media-has-caption -- 字幕由字幕轨叠加显示
                key={slot}
                ref={ref}
                playsInline
                // 播放过之前只拉元数据与定位处的画面；开始播放后整段缓冲，切换片段才能无缝
                preload={playback.started ? "auto" : "metadata"}
                data-testid={`edit-player-video-${slot}`}
                className={cn("absolute inset-0 size-full object-contain", playback.visibleSlot !== slot && "opacity-0")}
              />
            ))}
            <canvas
              ref={playback.handoffFrameRef}
              aria-hidden="true"
              hidden
              className="absolute inset-0 z-10 size-full bg-black object-contain"
            />
          </div>
          {segment && !segment.hasVideo && (
            <div
              className="absolute inset-0 flex items-center justify-center text-sm text-muted-foreground opacity-(--stage-opacity)"
              style={{ "--stage-opacity": opacity } as CSSProperties}
            >
              {t("edit_view_stage_video_missing")}
            </div>
          )}
          {subtitle && (
            <p
              data-testid="edit-player-subtitle"
              className="pointer-events-none absolute top-(--subtitle-top) left-1/2 m-0 w-(--subtitle-width) -translate-x-1/2 -translate-y-1/2 text-center burned-subtitle"
              style={
                {
                  "--subtitle-top": `${layout.centerFromTopPercent}%`,
                  "--subtitle-width": `${layout.maxWidthPercent}%`,
                  "--subtitle-size": `${layout.fontSizePercentOfShortSide}cqmin`,
                } as CSSProperties
              }
            >
              {subtitle.text}
            </p>
          )}
          {current && (
            <div className="pointer-events-none absolute inset-x-2.5 top-2.5 flex flex-wrap gap-1.5 text-xs">
              <span className="max-w-full truncate rounded-sm bg-black/60 px-1.5 py-0.5 text-white tabular-nums">
                {current.id} · {unitPositionLabel(positions, current.unit_id, t)}
              </span>
              {trimIgnored && (
                <span className="inline-flex max-w-full items-center gap-1 rounded-sm bg-warn px-1.5 py-0.5 text-black">
                  <AlertTriangle aria-hidden className="size-3 shrink-0" />
                  <span className="truncate">{t("edit_view_stage_trim_ignored")}</span>
                </span>
              )}
            </div>
          )}
          {playback.buffering && (
            <span
              role="status"
              className="pointer-events-none absolute top-2.5 right-2.5 inline-flex items-center gap-1 rounded-sm bg-black/60 px-1.5 py-0.5 text-xs text-white"
            >
              <Loader2 aria-hidden className="size-3 animate-spin" />
              {t("edit_view_buffering")}
            </span>
          )}
        </div>
      </div>
      <div className="flex shrink-0 items-center gap-3">
        <div className="flex shrink-0 items-center gap-1">
          <TooltipIconButton
            label={t("edit_view_previous_frame")}
            shortcut="ArrowLeft"
            onClick={() => playback.stepFrame(-1)}
            disabled={frameStepTarget(playback.t, plan.duration, -1) === null}
          >
            <StepBack aria-hidden />
          </TooltipIconButton>
          <Button
            size="icon-sm"
            onClick={playback.toggle}
            disabled={plan.segments.length === 0}
            aria-label={playback.playing ? t("edit_view_pause") : t("edit_view_play")}
          >
            {playback.playing ? <Pause aria-hidden /> : <Play aria-hidden />}
          </Button>
          <TooltipIconButton
            label={t("edit_view_next_frame")}
            shortcut="ArrowRight"
            onClick={() => playback.stepFrame(1)}
            disabled={frameStepTarget(playback.t, plan.duration, 1) === null}
          >
            <StepForward aria-hidden />
          </TooltipIconButton>
        </div>
        <span className="text-sm text-subtle-foreground tabular-nums">
          <span data-testid="edit-playback-clock">{formatTimecode(playback.t)}</span>{" "}
          <span className="text-muted-foreground">/ {formatTimecode(plan.duration)}</span>
        </span>
        <span className="text-xs text-muted-foreground">
          {t("edit_view_clip_count", { count: plan.segments.length })}
        </span>
        <Toggle size="sm" pressed={showSubtitles} onPressedChange={onToggleSubtitles} className="ml-auto">
          <Captions data-icon="inline-start" aria-hidden />
          {t("edit_view_subtitles_toggle")}
        </Toggle>
      </div>
      {(playback.blocked || hasTransitions) && (
        <div className="flex shrink-0 flex-col gap-1 text-xs">
          {playback.blocked && (
            <p role="status" className="m-0 text-warn">
              {t("edit_view_playback_blocked")}
            </p>
          )}
          {hasTransitions && <p className="m-0 text-muted-foreground">{t("edit_view_transition_note")}</p>}
        </div>
      )}
    </div>
  );
}
