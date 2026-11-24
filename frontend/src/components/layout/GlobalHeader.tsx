import { startTransition, useEffect } from "react";
import { Link, useLocation } from "wouter";
import { ChevronLeft, Download, Loader2 } from "lucide-react";
import { useTranslation } from "react-i18next";
import { ROUTE_APP_PROJECTS, episodeEditViewPath } from "@/app-routes";
import { UsageHeaderEntry } from "@/components/usage/UsageHeaderEntry";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { ONBOARDING_ANCHORS } from "@/onboarding/anchors";
import { DemoReadOnlyBadge } from "@/onboarding/DemoReadOnlyBadge";
import { isDemoProject } from "@/onboarding/demo-project";
import { useDemoWorkbench } from "@/onboarding/use-demo-workbench";
import { useAppStore } from "@/stores/app-store";
import { useProjectsStore } from "@/stores/projects-store";
import { useUsageHeaderStore } from "@/stores/usage-header-store";
import type { WorkspaceNotification } from "@/types";
import { episodeDisplayName } from "@/utils/episode-display";
import { AgentPanelToggle } from "./AgentPanelToggle";
import { ProjectMenu } from "./ProjectMenu";
import { ProjectStatusBar } from "./ProjectStatusBar";
import { useProjectExport } from "./useProjectExport";
import { WorkspaceNotifications } from "./WorkspaceNotificationsDrawer";

/**
 * 工作区顶栏保留项目切换及操作。项目进度和下一步放在独立状态行，全局入口由导航轨提供。
 */
export function GlobalHeader() {
  const { t } = useTranslation(["dashboard", "onboarding"]);
  const [location, setLocation] = useLocation();
  const { currentProjectData, currentProjectName } = useProjectsStore();
  const setUsagePanelOpen = useAppStore((s) => s.setUsagePanelOpen);
  const triggerScrollTo = useAppStore((s) => s.triggerScrollTo);
  const demoMode = useDemoWorkbench();

  // 导出提示里的剪辑视图链接：在集页时指向当前集，否则指向播出顺序上的第一集；文案用集名。
  const routeEpisode = /\/episodes\/(\d+)/.exec(location)?.[1];
  const projectEpisodes = currentProjectData?.episodes ?? [];
  const editViewEpisodeId = routeEpisode !== undefined ? Number(routeEpisode) : projectEpisodes[0]?.episode;
  const editViewEpisode =
    editViewEpisodeId !== undefined && projectEpisodes.some((ep) => ep.episode === editViewEpisodeId)
      ? { episode: editViewEpisodeId, name: episodeDisplayName(projectEpisodes, editViewEpisodeId, t) }
      : null;
  const projectExport = useProjectExport({
    editViewEpisode,
    onOpenEditView: (episode) => {
      if (!currentProjectName) return;
      setLocation(`~${ROUTE_APP_PROJECTS}/${encodeURIComponent(currentProjectName)}${episodeEditViewPath(episode)}`);
    },
  });
  const exporting = projectExport.exporting !== null;

  // 演示项目在后端没有用量记录，入口整个不渲染。demoMode 在演示→真实切换时先于 store
  // 变为 false，currentProjectName 单独判一次兜住这一帧仍读到旧演示项目名的窗口。
  const usageProjectName =
    demoMode || !currentProjectName || isDemoProject(currentProjectName) ? null : currentProjectName;

  // 导出对话框打开期间切到别的项目或演示项目（如浏览器前进 / 后退复用同一路由实例）时随即关闭：
  // 对话框在打开时记下了当时的项目，留着会在选定范围后导出上一个项目；触发按钮已按 demoMode
  // 禁用，但已打开的对话框不受影响，仍可点击「导出」。
  const closeExport = projectExport.close;
  useEffect(() => {
    closeExport();
  }, [currentProjectName, demoMode, closeExport]);

  // 入口的数据随项目走：切到别的项目或演示项目时清空上一项目的用量，并收起悬浮层。
  useEffect(() => {
    void useUsageHeaderStore.getState().setProject(usageProjectName);
    if (usageProjectName === null) setUsagePanelOpen(false);
  }, [usageProjectName, setUsagePanelOpen]);

  const handleNotificationNavigate = (notification: WorkspaceNotification) => {
    const target = notification.target;
    if (!target) return;
    startTransition(() => {
      setLocation(target.route);
    });
    triggerScrollTo({
      type: target.type,
      id: target.id,
      route: target.route,
      highlight_style: target.highlight_style ?? "flash",
      expires_at: Date.now() + 3000,
    });
  };

  return (
    <header className="workspace-chrome @container/header grid shrink-0 grid-cols-[minmax(0,1fr)_auto] items-center gap-x-1 border-b border-border sm:gap-x-3">
      <div className="flex min-w-0 items-center gap-1 px-1 py-1.5 sm:gap-2 sm:px-3">
        <Link href={`~${ROUTE_APP_PROJECTS}`} aria-label={t("dashboard:projects")} className="chrome-control grid size-9 shrink-0 place-items-center outline-none focus-visible:ring-2 focus-visible:ring-sidebar-ring">
          <ChevronLeft aria-hidden className="size-4" />
        </Link>
        <span aria-hidden className="hidden h-6 w-px shrink-0 bg-sidebar-border sm:block" />
        <ProjectMenu />
        {demoMode && <DemoReadOnlyBadge />}
      </div>

      <div className="flex items-center justify-end gap-1 px-1 py-1.5 sm:px-3">
        <WorkspaceNotifications onNavigate={handleNotificationNavigate} />
        {usageProjectName && <UsageHeaderEntry projectName={usageProjectName} />}
        <span aria-hidden className="mx-1 hidden h-5 w-px shrink-0 bg-sidebar-border sm:block" />
        <span className="flex" data-onboarding={ONBOARDING_ANCHORS.workbenchExport}>
          <Tooltip>
            <TooltipTrigger
              render={
                <Button
                  variant="ghost"
                  size="icon"
                  className="chrome-control"
                  aria-label={t("dashboard:export_project_zip")}
                  aria-busy={exporting}
                  disabled={!currentProjectName || exporting || demoMode}
                  onClick={() => currentProjectName && projectExport.open(currentProjectName)}
                />
              }
            >
              {exporting ? (
                <Loader2 aria-hidden data-icon="inline-start" className="animate-spin" />
              ) : (
                <Download aria-hidden data-icon="inline-start" />
              )}
            </TooltipTrigger>
            <TooltipContent side="bottom">
              {demoMode ? t("onboarding:demo_action_unavailable") : t("dashboard:export_project_zip")}
            </TooltipContent>
          </Tooltip>
        </span>
        <AgentPanelToggle />
      </div>
      {currentProjectName && (
        <div className="col-span-full flex min-w-0 flex-wrap items-center gap-2 border-t border-border px-2 py-1 empty:hidden sm:px-4">
          <ProjectStatusBar key={currentProjectName} projectName={currentProjectName} />
        </div>
      )}
      {projectExport.element}
    </header>
  );
}
