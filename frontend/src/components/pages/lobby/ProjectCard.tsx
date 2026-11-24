/** 项目大厅的片目行。新手引导复用只读形态，保持演示外观与真实项目一致。 */

import { Link } from "wouter";
import { ROUTE_APP_PROJECTS } from "@/app-routes";
import { Clapperboard, Download, MoreHorizontal, Pencil, Trash2 } from "lucide-react";
import { useTranslation } from "react-i18next";
import { cn } from "cn";
import { Button } from "@/components/ui/button";
import { TruncatedText } from "@/components/shared/TruncatedText";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { API_BASE } from "@/api/transport";
import { formatRelativeTime, isJustNow } from "@/utils/date-format";
import { getProjectDisplayName } from "@/utils/project-display";
import type { ProjectStatus, ProjectSummary } from "@/types";
import { asProjectStatus, projectProgress, repairReasonOf, type ProjectProgress } from "./lobby-projects";

export interface ProjectCardActions {
  onRename: (project: ProjectSummary) => void;
  onExport: (project: ProjectSummary) => void;
  onDelete: (project: ProjectSummary) => void;
}

/** 大厅里的真实卡片必须给 `actions`；只读演示卡不接受它。 */
type ProjectCardProps = { project: ProjectSummary } & (
  | { readOnly: true; actions?: never }
  | { readOnly?: false; actions: ProjectCardActions }
);

const PROGRESS_DOT: Record<ProjectProgress, string> = {
  empty: "bg-muted-foreground",
  in_progress: "bg-primary",
  completed: "bg-good",
};

export function ProjectCard({ project, readOnly, actions }: ProjectCardProps) {
  const { t, i18n } = useTranslation(["dashboard", "onboarding"]);
  const status = asProjectStatus(project.status);
  const progress = projectProgress(status);
  const title = getProjectDisplayName(project.title, t("dashboard:untitled_project"));
  const repairReason = repairReasonOf(status);
  const updated = updatedText(project.last_activity_at, i18n.language, t);

  return (
    <article
      className="group relative min-w-0 border-b border-border bg-card transition-colors duration-fast hover:bg-muted/60"
    >
      <Link
        href={`${ROUTE_APP_PROJECTS}/${encodeURIComponent(project.name)}`}
        className={cn(
          "grid min-w-0 items-center gap-x-4 gap-y-2 px-3 py-3 text-foreground no-underline outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset sm:px-4",
          actions && "project-index-columns pr-12 sm:pr-14",
        )}
      >
        <div className="flex min-w-0 items-center gap-3">
          <Poster project={project} />
          <div className="min-w-0">
            {readOnly ? (
              <h3 className="min-w-0 text-sm font-semibold"><TruncatedText text={title} focusable={false} /></h3>
            ) : (
              <h2 className="min-w-0 text-sm font-semibold"><TruncatedText text={title} focusable={false} /></h2>
            )}
            {repairReason && <p className="line-clamp-2 text-xs break-words text-muted-foreground">{repairReason}</p>}
          </div>
        </div>
        <div className="flex min-w-0 flex-wrap items-center gap-1.5 text-xs text-subtle-foreground">
          <span className="inline-flex items-center gap-1.5">
            <span aria-hidden className={cn("size-2 shrink-0 rounded-full", PROGRESS_DOT[progress])} />
            {t(`dashboard:lobby_card_status_${progress}`)}
          </span>
          {status?.needs_repair && (
            <span className="border border-warn/40 px-1.5 py-0.5 font-medium text-warn">
              {t("dashboard:lobby_card_needs_repair")}
            </span>
          )}
        </div>
        <div className="flex min-w-0 flex-col gap-1.5 text-xs text-muted-foreground">
          <span>{episodesText(status, progress, t)}</span>
          <EpisodeStrip summary={status?.episodes_summary} />
        </div>
        <span className="project-index-activity min-w-0 text-xs text-muted-foreground empty:hidden">{updated}</span>
        {readOnly && <span className="sr-only">{t("onboarding:demo_badge")}</span>}
      </Link>

      {actions && (
        <div className="absolute top-3 right-2 sm:top-1/2 sm:right-3 sm:-translate-y-1/2">
          <DropdownMenu>
            <DropdownMenuTrigger
              render={
                <Button variant="ghost" size="icon" aria-label={t("dashboard:lobby_card_actions", { title })} />
              }
            >
              <MoreHorizontal aria-hidden />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem onClick={() => actions.onRename(project)}>
                <Pencil aria-hidden />
                {t("dashboard:lobby_card_rename")}
              </DropdownMenuItem>
              <DropdownMenuItem onClick={() => actions.onExport(project)}>
                <Download aria-hidden />
                {t("dashboard:lobby_card_export")}
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem variant="destructive" onClick={() => actions.onDelete(project)}>
                <Trash2 aria-hidden />
                {t("dashboard:lobby_card_delete")}
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      )}
    </article>
  );
}

const FILES_URL_PREFIX = `${API_BASE}/files/`;

/**
 * 封面走项目文件路由时请求 320 像素宽的缩略图，覆盖列表缩略图的高分屏显示。
 * 后端给的地址可能已带 `?v=` 版本键；演示卡的 data: 等其他来源原样返回。
 */
function posterSrc(url: string): string {
  if (!url.startsWith(FILES_URL_PREFIX)) return url;
  return `${url}${url.includes("?") ? "&" : "?"}w=320`;
}

/** 片目索引缩略图。 */
function Poster({ project }: { project: ProjectSummary }) {
  return (
    <div className="relative grid aspect-video w-16 shrink-0 place-items-center overflow-hidden rounded-sm bg-muted sm:w-24">
      {project.thumbnail ? (
        <img
          src={posterSrc(project.thumbnail)}
          alt=""
          loading="lazy"
          decoding="async"
          className="absolute inset-0 size-full object-cover"
        />
      ) : (
        <Clapperboard aria-hidden className="size-5 text-muted-foreground" />
      )}
    </div>
  );
}

/** 每集一格：已完成、制作中、已有脚本、尚未开始。数量已写在下方的次要文字里，这里只作示意。 */
function EpisodeStrip({ summary }: { summary: ProjectStatus["episodes_summary"] | undefined }) {
  if (!summary || summary.total === 0) return null;
  const inProductionEnd = summary.completed + summary.in_production;
  // `scripted` 数的是有脚本的集，已包含完成与制作中的集。
  const scriptedEnd = Math.max(summary.scripted, inProductionEnd);
  return (
    <div aria-hidden className="flex gap-0.5">
      {Array.from({ length: summary.total }, (_, i) => (
        <span
          key={i}
          className={cn(
            "h-1 flex-1 rounded-full",
            i < summary.completed
              ? "bg-good"
              : i < inProductionEnd
                ? "bg-primary"
                : i < scriptedEnd
                  ? "bg-muted-foreground"
                  : "bg-muted",
          )}
        />
      ))}
    </div>
  );
}

type Translate = ReturnType<typeof useTranslation>["t"];

function episodesText(status: ProjectStatus | null, progress: ProjectProgress, t: Translate): string {
  const episodes = status?.episodes_summary;
  if (!episodes || episodes.total === 0) return t("dashboard:lobby_card_no_episodes");
  if (progress === "completed") return t("dashboard:lobby_card_episode_count", { count: episodes.total });
  return t("dashboard:lobby_card_progress", { completed: episodes.completed, total: episodes.total });
}

function updatedText(lastActivityAt: string | null | undefined, lang: string, t: Translate): string | null {
  if (isJustNow(lastActivityAt)) return t("dashboard:lobby_card_updated_just_now");
  const time = formatRelativeTime(lastActivityAt, lang);
  return time ? t("dashboard:lobby_card_updated", { time }) : null;
}
