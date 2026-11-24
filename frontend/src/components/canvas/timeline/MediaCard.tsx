import { useRef, useState } from "react";
import { isResourceBusy } from "@/stores/tasks-store";
import { ImageIcon, Film, Trash2 } from "lucide-react";
import { useTranslation } from "react-i18next";
import { API } from "@/api";
import { usePlaybackStart } from "@/hooks/usePlaybackStart";
import { useProjectsStore } from "@/stores/projects-store";
import { AspectFrame } from "@/components/canvas/shared/AspectFrame";
import { PreviewableImageFrame } from "@/components/canvas/shared/PreviewableImageFrame";
import { PresentationPlayer } from "@/components/shared/PresentationPlayer";
import {
  UPLOAD_IMAGE_ACCEPT,
  UPLOAD_VIDEO_ACCEPT,
  UploadIconButton,
} from "@/components/canvas/shared/UploadIconButton";
import { useDemoWorkbench } from "@/onboarding/use-demo-workbench";
import { useItemPositionLabel } from "@/components/shared/episode-item/useEpisodeItem";
import { ImageEditButton } from "./ImageEditButton";
import { VersionTimeMachine } from "./VersionTimeMachine";
import { TooltipIconButton } from "./TooltipIconButton";

type MediaKind = "storyboard" | "video";

interface MediaCardProps {
  kind: MediaKind;
  restoring?: boolean;
  onRestoringChange?: (restoring: boolean) => void;
  checkBusy?: () => boolean;
  projectName: string;
  segmentId: string;
  /** 资产相对路径，如 storyboards/E1S2_v1.png */
  assetPath: string | null;
  /** 视频海报缩略图（仅 kind=video 用） */
  posterPath?: string | null;
  /** 渲染比例 */
  aspectRatio: "9:16" | "16:9";
  generating?: boolean;
  showEmptyPreview?: boolean;
  /** 版本恢复回调；未提供时不显示版本入口（只读展示无版本可回滚） */
  onRestore?: () => Promise<unknown> | void;
  /** 自主上传回调（替换该分镜的参考图/视频）；未提供时不显示上传入口 */
  onUpload?: (file: File) => Promise<void> | void;
  onDelete?: () => void;
  /** 本卡片的上传请求进行中 */
  uploading?: boolean;
  /** 其他上传进行中等需要互斥的场景：禁用上传入口但不显示 spinner */
  uploadDisabled?: boolean;
  /** 分镜编辑所需的剧集文件；提供时（且 kind=storyboard、已有图）显示编辑入口 */
  editScriptFile?: string | null;
}

const UPLOAD_ACCEPT: Record<MediaKind, string> = {
  storyboard: UPLOAD_IMAGE_ACCEPT,
  video: UPLOAD_VIDEO_ACCEPT,
};

export function MediaCard({
  kind,
  projectName,
  segmentId,
  assetPath,
  posterPath,
  aspectRatio,
  generating,
  showEmptyPreview,
  onRestore,
  onUpload,
  onDelete,
  uploading,
  uploadDisabled,
  editScriptFile,
  restoring: externalRestoring,
  onRestoringChange,
  checkBusy,
}: MediaCardProps) {
  const { t } = useTranslation("dashboard");
  const itemLabel = useItemPositionLabel(segmentId);
  const [restoring, setRestoring] = useState(false);
  const restoringRef = useRef(false);
  const freshBusy = () => restoringRef.current || Boolean(checkBusy?.()) || isResourceBusy(kind, projectName, segmentId);
  const setRestoreBusy = (next: boolean) => {
    restoringRef.current = next;
    setRestoring(next);
    onRestoringChange?.(next);
  };
  const demoReadOnly = useDemoWorkbench();

  const assetFp = useProjectsStore((s) =>
    assetPath ? s.getAssetFingerprint(assetPath) : null,
  );
  const playbackStart = usePlaybackStart("videos", segmentId);
  // 原图只给全屏预览；卡片里按媒体栏宽度从 640 / 1280 两档缩略图中取，媒体栏最宽约 720px。
  const assetUrl = assetPath ? API.getFileUrl(projectName, assetPath, assetFp) : null;
  const storyboardSrcSet =
    assetPath && kind === "storyboard"
      ? `${API.getFileUrl(projectName, assetPath, assetFp, { width: 640 })} 640w, ${API.getFileUrl(projectName, assetPath, assetFp, { width: 1280 })} 1280w`
      : undefined;

  const Icon = kind === "storyboard" ? ImageIcon : Film;
  const title =
    kind === "storyboard" ? t("media_storyboard_title") : t("media_video_title");
  const resourceType: "storyboards" | "videos" =
    kind === "storyboard" ? "storyboards" : "videos";
  // uploadDisabled 是本卡片之外的互斥占用（如同一分镜另一张卡在上传中）；
  // 编辑和版本恢复同样写这个资源，须一并禁用。
  const resourceBusy = generating || uploading || uploadDisabled || restoring || externalRestoring;
  const actionsOnly = kind === "storyboard" && !assetUrl && !showEmptyPreview;
  if (actionsOnly && (demoReadOnly || (!onUpload && !onRestore))) return null;

  return (
    <div>
      <div className="mb-2 flex min-h-7 items-center gap-1.5">
        {!actionsOnly && (
          <>
            <Icon aria-hidden className="size-3.5 text-muted-foreground" />
            <h3 className="text-xs font-medium text-subtle-foreground">{title}</h3>
          </>
        )}
        <span className="flex-1" />
        {onDelete && assetPath && !demoReadOnly && (
          <TooltipIconButton label={t("common:delete")} disabled={resourceBusy} onClick={() => { if (!freshBusy()) onDelete(); }}>
            <Trash2 className="size-4" />
          </TooltipIconButton>
        )}
        {onUpload && !demoReadOnly && (
          <UploadIconButton
            accept={UPLOAD_ACCEPT[kind]}
            label={
              kind === "storyboard"
                ? t("media_upload_storyboard")
                : t("media_upload_video")
            }
            busy={uploading}
            disabled={resourceBusy}
            onSelect={(f) => { if (!freshBusy()) void onUpload(f); }}
          />
        )}
        {kind === "storyboard" && editScriptFile && !demoReadOnly && (
          <ImageEditButton
            projectName={projectName}
            resourceType="storyboard"
            resourceId={segmentId}
            scriptFile={editScriptFile}
            hasImage={Boolean(assetPath)}
            busy={resourceBusy}
          />
        )}
        {onRestore && !demoReadOnly && (
          <VersionTimeMachine
            projectName={projectName}
            resourceType={resourceType}
            resourceId={segmentId}
            onRestore={onRestore}
            busy={resourceBusy}
            checkBusy={freshBusy}
            onRestoringChange={setRestoreBusy}
          />
        )}
      </div>

      {assetUrl ? (
        kind === "storyboard" ? (
          <PreviewableImageFrame src={assetUrl} alt={`${itemLabel} ${title}`}>
            <AspectFrame ratio={aspectRatio}>
              <img
                src={assetUrl}
                srcSet={storyboardSrcSet}
                sizes="(min-width: 1280px) 720px, 640px"
                alt={`${itemLabel} ${title}`}
                loading="lazy"
                decoding="async"
                className="size-full object-contain"
              />
            </AspectFrame>
          </PreviewableImageFrame>
        ) : (
          <div className="overflow-hidden rounded-lg ring-1 ring-border">
            <AspectFrame ratio={aspectRatio}>
              <PresentationPlayer
                key={`${segmentId}:${assetFp ?? "current"}`}
                projectName={projectName}
                resourceType="videos"
                resourceId={segmentId}
                posterPath={posterPath}
                {...playbackStart}
              />
            </AspectFrame>
          </div>
        )
      ) : !actionsOnly ? (
        <AspectFrame ratio={aspectRatio}>
          <div className="flex size-full flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-border bg-muted/30 text-muted-foreground">
            <Icon aria-hidden className="size-5" />
            <span className="text-xs">{t(kind === "storyboard" && generating ? "generating_status" : "media_not_generated")}</span>
          </div>
        </AspectFrame>
      ) : null}
    </div>
  );
}
