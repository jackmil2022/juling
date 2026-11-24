import { useId, useState, type ReactNode } from "react";
import { ChevronRight } from "lucide-react";
import { useTranslation } from "react-i18next";
import { cn } from "cn";
import { Button } from "@/components/ui/button";
import { ResizableHandle, ResizablePanel, ResizablePanelGroup } from "@/components/ui/resizable";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";

declare global {
  interface Window {
    julingShotPreview?: { initialSize: number | undefined; saveSize: (size: number) => void };
  }
}

let previewSize = window.julingShotPreview?.initialSize ?? 56;

/** 窄画布上下排列，两栏布局的预览比例只在用户调整后保存。 */
export function ShotDetailLayout({
  header,
  footer,
  main,
  media,
}: {
  header: ReactNode;
  /** 两栏下方横跨整宽的未保存提示条：出现时不推动正在编辑的字段。 */
  footer?: ReactNode;
  main: ReactNode;
  media: ReactNode;
}) {
  const { t } = useTranslation("dashboard");
  const id = useId();
  const editorId = `${id}-editor`;
  const previewId = `${id}-preview`;
  const [defaultLayout] = useState(() => ({ [editorId]: 100 - previewSize, [previewId]: previewSize }));
  const stackedPanel = "@max-[660px]/shot-detail:max-h-none! @max-[660px]/shot-detail:overflow-visible!";

  return (
    <div className="flex min-h-0 min-w-0 flex-col">
      {header}
      <div className="@container/shot-detail min-h-0 flex-1">
        <ResizablePanelGroup
          className="@max-[660px]/shot-detail:block! @max-[660px]/shot-detail:overflow-y-auto!"
          defaultLayout={defaultLayout}
          onLayoutChanged={(layout, { isUserInteraction, requestedLayout }) => {
            if (!isUserInteraction) return;
            const size = Math.round((requestedLayout?.[previewId] ?? layout[previewId]) * 100) / 100;
            if (!Number.isFinite(size) || size <= 0 || size >= 100 || size === previewSize) return;
            previewSize = size;
            window.julingShotPreview?.saveSize(size);
          }}
        >
          <ResizablePanel id={editorId} minSize="320px" className={stackedPanel}>
            <div className="flex flex-col gap-5 px-5 pt-4 pb-8">{main}</div>
          </ResizablePanel>
          <ResizableHandle withHandle aria-label={t("detail_resize_media_preview")} className="@max-[660px]/shot-detail:hidden!" />
          <ResizablePanel id={previewId} minSize="260px" className={stackedPanel}>
            <section aria-label={t("detail_media_preview")} className="@container/shot-media min-w-0 border-t border-border/50 px-4 pt-4 pb-8 @min-[660px]/shot-detail:border-t-0">
              {media}
            </section>
          </ResizablePanel>
        </ResizablePanelGroup>
      </div>
      {footer}
    </div>
  );
}

/** 编辑栏里的一组内容；组与组之间用分隔线隔开。 */
export function ShotGroup({ children }: { children: ReactNode }) {
  return (
    <div className="flex flex-col gap-4 border-t border-border/50 pt-5 first:border-t-0 first:pt-0">{children}</div>
  );
}

/**
 * 编辑栏里的一段：小标题加内容。给了 `htmlFor` 时标题是对应输入框的 label，
 * 否则是一个三级标题；`actions` 放在标题行右侧。
 */
export function ShotSection({
  title,
  icon,
  htmlFor,
  actions,
  children,
}: {
  title: string;
  icon?: ReactNode;
  htmlFor?: string;
  actions?: ReactNode;
  children: ReactNode;
}) {
  const titleId = useId();
  const heading = htmlFor ? (
    <label id={titleId} htmlFor={htmlFor} className="text-xs font-medium text-muted-foreground">
      {title}
    </label>
  ) : (
    <h3 id={titleId} className="text-xs font-medium text-muted-foreground">
      {title}
    </h3>
  );
  return (
    <section aria-labelledby={titleId} className="flex min-w-0 flex-col gap-2">
      <div className="flex min-h-7 flex-wrap items-center gap-1.5">
        {icon ? <span className="flex text-muted-foreground">{icon}</span> : null}
        {heading}
        {actions ? <div className="ml-auto flex flex-wrap items-center justify-end gap-1">{actions}</div> : null}
      </div>
      {children}
    </section>
  );
}

/** 默认折叠的「对应原文与参考」。 */
export function ShotSourceCollapsible({ children }: { children: ReactNode }) {
  const { t } = useTranslation("dashboard");
  return (
    <Collapsible>
      <CollapsibleTrigger render={<Button variant="ghost" size="sm" className="-ml-2" />}>
        <ChevronRight aria-hidden data-icon="inline-start" className="transition-transform group-aria-expanded/button:rotate-90" />
        {t("detail_section_source_and_refs")}
      </CollapsibleTrigger>
      <CollapsibleContent>
        <div className="flex flex-col gap-4 pt-3">{children}</div>
      </CollapsibleContent>
    </Collapsible>
  );
}

/**
 * 媒体栏：媒体栏够宽时参考图与视频并排（竖屏 440px、横屏 720px 起），否则上下排。
 */
export function ShotMediaGrid({
  aspectRatio,
  storyboard,
  video,
}: {
  aspectRatio: "9:16" | "16:9";
  storyboard: ReactNode;
  video: ReactNode;
}) {
  const portrait = aspectRatio === "9:16";
  return (
    <div
      className={cn(
        "grid items-start gap-x-4 gap-y-5",
        storyboard && (portrait ? "@min-[440px]/shot-media:grid-cols-2" : "@min-[720px]/shot-media:grid-cols-2"),
      )}
    >
      {storyboard && <div className="min-w-0">{storyboard}</div>}
      <div className="flex min-w-0 flex-col">{video}</div>
    </div>
  );
}
