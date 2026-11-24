import { useCallback, useEffect, useId, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { useParams, useSearchParams } from "wouter";

import { API } from "@/api";
import { Textarea } from "@/components/ui/textarea";
import { TruncatedText } from "@/components/shared/TruncatedText";
import { Button } from "@/components/ui/button";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useAppStore } from "@/stores/app-store";
import { useProjectsStore } from "@/stores/projects-store";
import type {
  EditTimelineIssue,
  EditTimelinePreviewMedia,
  EditTimelineReadout,
  EditTimelineSummary,
  TimelineClipOperation,
  TimelineSubtitle,
} from "@/types/edit-timeline";
import { LINK_TIME_PARAM, LINK_TIMELINE_PARAM, parseSeconds } from "@/utils/app-link";
import { errMsg } from "@/utils/async";
import { formatRelativeTime, isJustNow } from "@/utils/date-format";
import type { PreviewAspect } from "@/utils/preview-aspect";

import { ClipInspector, ISSUE_LIST_HEADING_ID, IssueList } from "./EditTimelineDetails";
import { EditTimelineMenu } from "./EditTimelineMenu";
import { EditTimelinePlayer } from "./EditTimelinePlayer";
import { EditTimelineTracks } from "./EditTimelineTracks";
import { buildPlaybackPlan, locate, type PlaybackPlan, type PlaybackSegment } from "./playback-schedule";
import {
  bgmPlacements,
  audioRows, clipAudioPlacements,
  placeSubtitles,
  type AudioKind,
  type AudioPlacement,
  type PlacedSubtitle,
} from "./preview-tracks";
import {
  isReferenceVideoScript,
  issueClipIds,
  pickDefaultTimeline,
  unitPositions,
  unitThumbnails,
  unitVideoPath,
  unusedUnitIds,
} from "./timeline-view";
import { audioAssetKey, useTimelineAudioAnalysis, type AudioAsset, type Waveform } from "./useTimelineAudioAnalysis";
import { useTimelinePlayback } from "./useTimelinePlayback";

/** 标签行右侧操作区拿到的当前剪辑时间线。 */
export interface EditTimelineActionsContext {
  timelineId: string;
  timelineName: string;
  /** 当前读取结果的 issues；读取完成前为 null。 */
  issues: readonly EditTimelineIssue[] | null;
  /** 滚动到「问题」列表并把焦点移过去。 */
  showIssues: () => void;
}

export interface EditTimelineEmptyStateContext {
  /** 新建剪辑时间线后调用，重新读取列表并选中最近修改的那条。 */
  reload: () => void;
}

interface EditTimelineViewProps {
  projectName: string;
  episode: number;
  /** 本集脚本：用于视频单元的源视频路径与缩略图。 */
  script: unknown;
  aspect: PreviewAspect;
  /** 标签行右侧的操作区；不传时不渲染。 */
  renderActions?: (context: EditTimelineActionsContext) => ReactNode;
  /** 本集没有剪辑时间线时的空状态。 */
  renderEmptyState: (context: EditTimelineEmptyStateContext) => ReactNode;
}

/** 应用内链接带来的一次性定位：打开哪条剪辑时间线（缺省为当前选中的）、定位到全局时间的哪一秒（缺省为不动播放头）。 */
interface LinkJump {
  timelineId: string | null;
  seconds: number | null;
}

type Loaded<T> = { key: string; value: T } | { key: string; error: string };

/**
 * 集页的剪辑视图：只读预览一条剪辑时间线，标签菜单可重命名与删除。上方播放器按剪辑时间线实时拼接播放，下方横向时间线；
 * 项目有变更（含 Agent 写入新修订）时重新读取。
 */
export function EditTimelineView({
  projectName,
  episode,
  script,
  aspect,
  renderActions,
  renderEmptyState,
}: EditTimelineViewProps) {
  const { t, i18n } = useTranslation("dashboard");
  const snapshotRevision = useProjectsStore((s) => s.projectSnapshotRevisions[projectName] ?? 0);
  const [retry, setRetry] = useState(0);
  const listKey = `${projectName}::${episode}::${snapshotRevision}::${retry}`;
  const [list, setList] = useState<Loaded<EditTimelineSummary[]> | null>(null);
  const [chosenId, setChosenId] = useState<string | null>(null);
  const reload = useCallback(() => setRetry((n) => n + 1), []);
  const tabIdPrefix = useId();

  // 链接参数 tl / t 读入后立刻从地址栏去掉：它们是一次性的定位指令，刷新页面不应再次跳走。
  const [searchParams, setSearchParams] = useSearchParams();
  // 跳到别的项目时，地址先变、当前项目后切：这一刻地址栏里的参数属于即将挂载的那个视图，不在这里消费。
  const routeProject = useParams<{ projectName?: string }>().projectName;
  const linkForOtherProject = routeProject !== undefined && routeProject !== projectName;
  const linkTimeline = searchParams.get(LINK_TIMELINE_PARAM);
  const linkTime = searchParams.get(LINK_TIME_PARAM);
  const [jump, setJump] = useState<LinkJump | null>(null);
  useEffect(() => {
    if (linkForOtherProject || (linkTimeline === null && linkTime === null)) return;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- 订阅地址栏的一次性参数：读入后清掉，再点同一条链接才能重新触发
    setJump({ timelineId: linkTimeline || null, seconds: parseSeconds(linkTime) });
    setSearchParams(
      (params) => {
        params.delete(LINK_TIMELINE_PARAM);
        params.delete(LINK_TIME_PARAM);
        return params;
      },
      { replace: true },
    );
  }, [linkForOtherProject, linkTimeline, linkTime, setSearchParams]);
  // 删除后选中的标签回落到默认那条（最近修改的）。
  const handleDeleted = useCallback(() => {
    setChosenId(null);
    setRetry((n) => n + 1);
  }, []);
  const showIssues = useCallback(() => {
    const heading = document.getElementById(ISSUE_LIST_HEADING_ID);
    heading?.scrollIntoView({ block: "nearest", behavior: "smooth" });
    heading?.focus({ preventScroll: true });
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    API.listEditTimelines(projectName, episode, { signal: controller.signal })
      .then(({ timelines }) => {
        if (controller.signal.aborted) return;
        setList({ key: listKey, value: timelines });
        // 首次看到剪辑时间线时固定默认选中的那条，之后新建或修改其他时间线不会把正在看的标签切走。
        setChosenId((previous) => previous ?? pickDefaultTimeline(timelines));
      })
      .catch((cause: unknown) => {
        if (!controller.signal.aborted) setList({ key: listKey, error: errMsg(cause) });
      });
    return () => controller.abort();
  }, [episode, listKey, projectName]);

  // 刷新期间沿用上一次的列表，避免每次项目变更都闪回加载态。
  const timelines = list && "value" in list ? list.value : null;

  // 列表到了才能判断链接指向的剪辑时间线还在不在：在就直接选中它，不在就提示并放弃这次定位。
  const jumpTimelineId = jump?.timelineId ?? null;
  const jumpTarget =
    timelines !== null && jumpTimelineId !== null && timelines.some((item) => item.id === jumpTimelineId)
      ? jumpTimelineId
      : null;
  // 沿用中的旧列表可能还没有刚新建的那条，只按本轮读到的列表判定「不存在」。
  const listFresh = list?.key === listKey;
  // react-doctor-disable-next-line react-doctor/no-effect-chain -- 地址栏的定位指令与异步读到的列表齐备后才能判定目标不存在，需要提示一次，提示是副作用只能放在 effect
  useEffect(() => {
    if (!jump || !timelines) return;
    if (timelines.length === 0) {
      // react-doctor-disable-next-line react-doctor/no-adjust-state-on-prop-change -- 定位指令来自地址栏、列表异步到达，两者齐备时才能判定作废
      setJump(null); // eslint-disable-line react-hooks/set-state-in-effect -- 没有剪辑时间线可定位，作废这次定位
      return;
    }
    if (jumpTimelineId !== null && jumpTarget === null && listFresh) {
      useAppStore.getState().pushToast(t("edit_view_link_timeline_missing"), "warning");
      // react-doctor-disable-next-line react-doctor/no-adjust-state-on-prop-change -- 与上面的提示同属一次性通知：目标不存在时提示一次并作废定位
      setJump(null);
    }
  }, [jump, jumpTimelineId, jumpTarget, listFresh, timelines, t]);
  // 定位完成后把链接那条记为选中，此后标签不随定位指令清空而回落。
  const handleJumpApplied = useCallback(() => {
    if (jumpTarget !== null) setChosenId(jumpTarget);
    setJump(null);
  }, [jumpTarget]);
  const selectedId =
    jumpTarget ??
    (timelines && chosenId && timelines.some((item) => item.id === chosenId)
      ? chosenId
      : timelines
        ? pickDefaultTimeline(timelines)
        : null);
  const selected = timelines?.find((item) => item.id === selectedId);

  // 每次项目变更都重新读取：读取结果还取决于视频单元的 current 版本，不只取决于修订。
  const readoutKey = `${listKey}::${selectedId ?? ""}`;
  const [readout, setReadout] = useState<(Loaded<EditTimelineReadout> & { timelineId: string }) | null>(null);
  useEffect(() => {
    if (!selectedId) return;
    const controller = new AbortController();
    API.getEditTimeline(projectName, selectedId, { signal: controller.signal })
      .then((value) => {
        if (!controller.signal.aborted) setReadout({ key: readoutKey, timelineId: selectedId, value });
      })
      .catch((cause: unknown) => {
        if (controller.signal.aborted) return;
        // 刷新失败时保留这条剪辑时间线上一次的读取结果，播放不被打断。
        setReadout((previous) =>
          previous?.timelineId === selectedId && "value" in previous
            ? previous
            : { key: readoutKey, timelineId: selectedId, error: errMsg(cause) },
        );
      });
    return () => controller.abort();
  }, [projectName, readoutKey, selectedId]);

  // 旁白配音与字幕随读取结果一起刷新；读取失败时沿用上一次的结果，还没有结果时只是不出旁白、不显示字幕。
  const [previewMedia, setPreviewMedia] = useState<{ timelineId: string; value: EditTimelinePreviewMedia } | null>(
    null,
  );
  useEffect(() => {
    if (!selectedId) return;
    const controller = new AbortController();
    API.getEditTimelinePreviewMedia(projectName, selectedId, { signal: controller.signal })
      .then((value) => {
        if (!controller.signal.aborted) setPreviewMedia({ timelineId: selectedId, value });
      })
      .catch(() => {});
    return () => controller.abort();
  }, [projectName, readoutKey, selectedId]);

  if (list && "error" in list && !timelines) {
    return <LoadFailed message={list.error} onRetry={reload} />;
  }
  if (!timelines) return <Centered>{t("edit_view_loading")}</Centered>;
  if (timelines.length === 0 || !selected) {
    return renderEmptyState({ reload });
  }

  const applyReadout = (value: EditTimelineReadout) => {
    setReadout((previous) => {
      if (!previous || previous.timelineId !== value.timeline.id || !("value" in previous) || previous.value.revision > value.revision) return previous;
      return { key: readoutKey, timelineId: value.timeline.id, value };
    });
    reload();
  };
  const current = readout?.timelineId === selected.id ? readout : null;
  const tabId = (timelineId: string) => `${tabIdPrefix}-tab-${timelineId}`;
  const panelId = `${tabIdPrefix}-panel`;
  const choose = (timelineId: string) => {
    setChosenId(timelineId);
    // 手动切换标签后放弃尚未完成的链接定位。
    setJump(null);
  };
  const authorName = t(`edit_view_author_${selected.updated_by.kind}`);
  const updatedJustNow = isJustNow(selected.updated_at);
  const updatedAt = formatRelativeTime(selected.updated_at, i18n.language) ?? selected.updated_at;

  // 整个视图不滚动：标签行固定高度，下方的播放器、详情栏与轨道分掉剩余高度，只有详情栏自己滚动。
  return (
    <div className="@container-size/edit-view flex h-full min-h-0 flex-col">
      <div className="flex h-12 shrink-0 items-center gap-2 px-4 edit-short:h-10">
        {/* 剪辑时间线多、名称长时标签横向滚动，不把标签行撑高 */}
        <div className="relative flex min-w-0 overflow-x-auto scroll-fade-x">
          {/* 方向键移动焦点即切换：切换标签只换预览内容，不卸载别的东西 */}
          <Tabs value={selected.id} onValueChange={(value: string) => choose(value)} className="shrink-0">
            <TabsList aria-label={t("edit_view_timelines_aria")} activateOnFocus>
              {timelines.map((item) => (
                <TabsTrigger key={item.id} value={item.id} id={tabId(item.id)} aria-controls={panelId}>
                  {item.name}
                </TabsTrigger>
              ))}
            </TabsList>
          </Tabs>
        </div>
        <EditTimelineMenu projectName={projectName} timeline={selected} onRenamed={reload} onDeleted={handleDeleted} />
        <TruncatedText
          className="min-w-0 text-xs text-muted-foreground"
          text={
            updatedJustNow
              ? t("edit_view_updated_just_now", { author: authorName })
              : t("edit_view_updated", { author: authorName, time: updatedAt })
          }
        />
        {renderActions?.({
          timelineId: selected.id,
          timelineName: selected.name,
          issues: current && "value" in current ? current.value.issues : null,
          showIssues,
        })}
      </div>

      <div
        role="tabpanel"
        id={panelId}
        aria-labelledby={tabId(selected.id)}
        // 播放器、详情栏与轨道固定深色：浅底会干扰对画面明暗的判断
        className="dark flex min-h-0 flex-1 flex-col bg-background px-4 pb-4 text-foreground edit-short:pb-2"
      >
        {current && "value" in current ? (
          <TimelinePreview
            key={selected.id}
            projectName={projectName}
            readout={current.value}
            media={previewMedia?.timelineId === selected.id ? previewMedia.value : null}
            script={script}
            aspect={aspect}
            seekRequest={jump && (jump.timelineId === null || jump.timelineId === selected.id) ? jump : null}
            onSeekHandled={handleJumpApplied}
            onUpdate={applyReadout}
            onReload={reload}
          />
        ) : current && "error" in current ? (
          <LoadFailed message={current.error} onRetry={reload} />
        ) : (
          <Centered>{t("edit_view_loading")}</Centered>
        )}
      </div>
    </div>
  );
}

interface TimelinePreviewProps {
  projectName: string;
  readout: EditTimelineReadout;
  media: EditTimelinePreviewMedia | null;
  script: unknown;
  aspect: PreviewAspect;
  /** 链接要求定位的位置；处理完调用 `onSeekHandled`。 */
  seekRequest: LinkJump | null;
  onSeekHandled: () => void;
  onUpdate: (readout: EditTimelineReadout) => void;
  onReload: () => void;
}

const TRACKS_HEIGHT_STORAGE_KEY = "juling.edit.track-height";

function TimelinePreview({
  projectName,
  readout,
  media,
  script,
  aspect,
  seekRequest,
  onSeekHandled,
  onUpdate,
  onReload,
}: TimelinePreviewProps) {
  const { t } = useTranslation("dashboard");
  const workspace = useRef<HTMLDivElement>(null);
  const tracksPanel = useRef<HTMLDivElement>(null);
  const divider = useRef<{ from: number; height: number; max: number; next: number; frame: number } | null>(null);
  const resizeTracks = (height: number, max: number, remember = false) => {
    const clamped = Math.min(max, Math.max(0, height));
    workspace.current?.style.setProperty("--timeline-height", `${clamped}px`);
    if (remember) {
      try { localStorage.setItem(TRACKS_HEIGHT_STORAGE_KEY, String(clamped)); }
      catch { /* Resizing still works without local storage. */ }
    }
  };
  useLayoutEffect(() => {
    try {
      const height = Number(localStorage.getItem(TRACKS_HEIGHT_STORAGE_KEY));
      if (Number.isFinite(height) && height > 0) {
        workspace.current?.style.setProperty("--timeline-height", `${height}px`);
      }
    } catch { /* Keep the default minimum height. */ }
    return () => cancelAnimationFrame(divider.current?.frame ?? 0);
  }, []);
  const [selectedClipId, setSelectedClipId] = useState<string | null>(null);
  const [showSubtitles, setShowSubtitles] = useState(true);
  const [selectedSubtitleId, setSelectedSubtitleId] = useState<string | null>(null);
  const subtitleInput = useRef<HTMLTextAreaElement>(null);
  const [selectedAudioId, setSelectedAudioId] = useState<string | null>(null);
  const selectClip = useCallback((id: string | null) => {
    setSelectedClipId(id);
    setSelectedSubtitleId(null);
    setSelectedAudioId(null);
  }, []);
  const selectSubtitle = useCallback((id: string) => {
    setSelectedAudioId(null);
    setSelectedSubtitleId(id);
    setSelectedClipId(null);
  }, []);
  const [saving, setSaving] = useState(false);
  const savingRef = useRef(false);
  const [history, setHistory] = useState({ revision: 0, undo: [] as number[], redo: [] as number[] });
  const canUndo = history.revision === readout.revision && history.undo.length > 0;
  const canRedo = history.revision === readout.revision && history.redo.length > 0;
  const save = async (action: TimelineClipOperation | "undo" | "redo" | { subtitles: TimelineSubtitle[] }) => {
    if (savingRef.current) return;
    if ((action === "undo" && !canUndo) || (action === "redo" && !canRedo)) return;
    const timelineId = readout.timeline.id;
    const base = readout.revision;
    const undo = history.revision === base ? history.undo : [];
    const redo = history.revision === base ? history.redo : [];
    savingRef.current = true;
    setSaving(true);
    playback.pause();
    let revision: number | undefined;
    try {
      if (action === "undo" || action === "redo") {
        const target = (action === "undo" ? undo : redo).at(-1)!;
        revision = (await API.restoreEditTimeline(projectName, timelineId, target, base)).revision;
        setHistory({ revision, undo: action === "undo" ? undo.slice(0, -1) : [...undo, base], redo: action === "undo" ? [...redo, base] : redo.slice(0, -1) });
      } else if ("subtitles" in action) {
        revision = (await API.replaceTimelineSubtitles(projectName, timelineId, base, action.subtitles)).revision;
        if (revision !== base) {
          setHistory({ revision, undo: [...undo, base], redo: [] });
          onUpdate({ ...readout, revision, latest_revision: revision, subtitles: action.subtitles });
        }
        return;
      } else {
        revision = (await API.editTimelineClip(projectName, timelineId, base, action)).revision;
        setHistory({ revision, undo: revision === base + 1 ? [...undo, base] : [], redo: [] });
        if (action.op === "delete") setSelectedClipId(null);
      }
      onUpdate(await API.getEditTimeline(projectName, timelineId));
    } catch (cause) {
      onReload();
      useAppStore.getState().pushToast(revision === undefined ? errMsg(cause) : t("edit_view_edit_refresh_failed"), "error");
    } finally {
      savingRef.current = false;
      setSaving(false);
    }
  };

  // 内容相同的重新读取不换计划引用，播放不因项目的无关变更而重新定位。
  const planJson = useMemo(() => JSON.stringify(buildPlaybackPlan(readout, media)), [readout, media]);
  const plan = useMemo(() => JSON.parse(planJson) as PlaybackPlan, [planJson]);
  // 源视频地址只随视频单元的 current 版本变化；脚本对象每次刷新都换引用，这里只取它的形状。
  const referenceVideo = isReferenceVideoScript(script);
  const sourceUrl = useCallback(
    (segment: PlaybackSegment) =>
      segment.hasVideo && segment.videoVersion !== null
        ? API.getFileUrl(projectName, unitVideoPath(referenceVideo, segment.unitId), segment.videoVersion)
        : null,
    [projectName, referenceVideo],
  );
  const videoUrls = useMemo(
    () =>
      new Map(
        readout.clips.flatMap((clip) =>
          clip.status === "ready" && clip.video_version !== null
            ? [[clip.id, API.getFileUrl(projectName, unitVideoPath(referenceVideo, clip.unit_id), clip.video_version)] as const]
            : [],
        ),
      ),
    [projectName, readout.clips, referenceVideo],
  );
  // 音频摆放与旁白配音地址同样按内容去重，内容不变的刷新不打断正在播放的音频。
  const selectAudio = useCallback((id: string) => {
    selectClip(null);
    setSelectedAudioId(id);
  }, [selectClip]);
  const audioJson = useMemo(
    () => JSON.stringify([...clipAudioPlacements(readout, media), ...bgmPlacements(readout, media)]),
    [readout, media],
  );
  const baseAudio = useMemo(() => JSON.parse(audioJson) as AudioPlacement[], [audioJson]);
  const sourceRefsJson = useMemo(() => JSON.stringify({
    narration: Object.fromEntries((media?.units ?? []).flatMap((unit) =>
      unit.narration_audio ? [[unit.unit_id, unit.narration_audio]] : [])),
    bgm: Object.fromEntries((media?.bgm ?? []).map((item) => [item.bgm_id, { path: item.path, version: null }])),
    source: Object.fromEntries(readout.clips.flatMap((clip) =>
      clip.status === "ready" && clip.video_version !== null
        ? [[clip.id, { path: unitVideoPath(referenceVideo, clip.unit_id), version: clip.video_version }]] : [])),
  }), [media, readout.clips, referenceVideo]);
  const sourceAsset = useMemo(() => {
    const refs = JSON.parse(sourceRefsJson) as Record<"narration" | "source" | "bgm", Record<string, AudioAsset>>;
    return (item: AudioPlacement) =>
      refs[item.stem || item.kind === "source" ? "source" : item.kind === "narration" ? "narration" : "bgm"][item.sourceId];
  }, [sourceRefsJson]);
  const requests = useMemo(() => {
    const assets = new Map<string, AudioAsset>();
    for (const item of baseAudio) {
      const asset = sourceAsset(item);
      if (asset) assets.set(audioAssetKey(projectName, asset), asset);
    }
    return [...assets.values()];
  }, [projectName, baseAudio, sourceAsset]);
  const requestJson = useMemo(() => JSON.stringify(requests), [requests]);
  const analyses = useTimelineAudioAnalysis(projectName, requestJson);
  const { audio, playbackAudio, urls, waveforms, splitClips } = useMemo(() => {
    const audio: AudioPlacement[] = [];
    const playbackAudio: AudioPlacement[] = [];
    const urls = new Map<string, string>();
    const waveforms = new Map<string, Waveform>();
    const splitClips = new Set(readout.clips.filter((clip) =>
      clip.source_audio != null || clip.dialogue_audio != null || clip.sfx_audio != null,
    ).map((clip) => clip.id));
    for (const item of baseAudio) {
      const asset = sourceAsset(item);
      const analysis = asset ? analyses.get(audioAssetKey(projectName, asset)) : undefined;
      if (item.stem) {
        const kind = item.kind === "dialogue" ? "dialogue" : "sfx";
        const stem = analysis?.stems.find((entry) => entry.kind === kind);
        if (!analysis || !stem) continue;
        const { bars, rate } = stem.waveform;
        if (!item.detachedStem && !bars.subarray(Math.floor(item.sourceIn * rate),
          Math.ceil((item.sourceIn + item.end - item.start) * rate)).some(Boolean)) continue;
        audio.push(item);
        playbackAudio.push(item);
        waveforms.set(item.id, stem.waveform);
        urls.set(item.id, API.getTimelineAudioStemUrl(projectName, analysis.key, kind));
        continue;
      }
      if (item.kind === "source" && analysis?.stems.length) {
        splitClips.add(item.sourceId);
        continue;
      }
      if (item.kind !== "source") audio.push(item);
      if (asset && !item.pictureAudio) {
        playbackAudio.push(item);
        urls.set(item.id, API.getFileUrl(projectName, asset.path, asset.version));
      }
      if (analysis?.waveform.bars.length) waveforms.set(item.id, analysis.waveform);
    }
    return { audio, playbackAudio, urls, waveforms, splitClips };
  }, [analyses, baseAudio, projectName, readout.clips, sourceAsset]);
  const audioUrl = useCallback((item: AudioPlacement) => urls.get(item.id) ?? null, [urls]);
  const [mutedTracks, setMutedTracks] = useState<ReadonlySet<string>>(() => new Set());
  const toggleTrack = useCallback((id: string) => setMutedTracks((muted) => {
    const next = new Set(muted);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    return next;
  }), []);
  const rows = useMemo(() => audioRows(audio), [audio]);
  const mutedAudio = useMemo(() => new Set(rows.flatMap(({ id, items }) =>
    mutedTracks.has(id) ? items.map((item) => item.id) : [],
  )), [rows, mutedTracks]);
  const playback = useTimelinePlayback(plan, sourceUrl, playbackAudio, audioUrl, splitClips, mutedAudio,
    mutedTracks.has("dialogue-0") && mutedTracks.has("sfx-0"));
  const analysisStatus = useMemo(() => {
    const results = requests.map((asset) => analyses.get(audioAssetKey(projectName, asset)));
    return results.includes(undefined) ? "pending" : results.includes(null) ? "failed" : null;
  }, [analyses, projectName, requests]);
  const subtitles = useMemo(() => placeSubtitles(readout, plan, media), [readout, plan, media]);
  const selectedSubtitle = useMemo(() => subtitles.find((item) => item.id === selectedSubtitleId), [subtitles, selectedSubtitleId]);
  const editSubtitle = (id: string, change: Partial<Omit<TimelineSubtitle, "id">> | null) => {
    const track = readout.subtitles ?? subtitles.map((item) => ({
      id: item.id, start_us: Math.round(item.start * 1e6), end_us: Math.round(item.end * 1e6), text: item.text,
    }));
    if (!track.some((item) => item.id === id)) return;
    const updated = track.flatMap((item) => item.id !== id ? [item] : change ? [{ ...item, ...change }] : []);
    updated.sort((a, b) => a.start_us - b.start_us);
    void save({ subtitles: updated });
  };
  const focusSubtitle = useCallback((item: PlacedSubtitle) => {
    selectSubtitle(item.id);
    playback.pause();
    playback.seek(item.start);
    setShowSubtitles(true);
    requestAnimationFrame(() => subtitleInput.current?.focus());
  }, [playback.pause, playback.seek, selectSubtitle]);

  // 链接带了时间点：播放头移过去（暂停在那一刻），并选中落在该时间的片段。
  const { seek } = playback;
  useEffect(() => {
    if (!seekRequest) return;
    if (seekRequest.seconds !== null) {
      seek(seekRequest.seconds);
      const location = locate(plan, seekRequest.seconds);
      // eslint-disable-next-line react-hooks/set-state-in-effect -- 一次性的链接定位：移动播放头的同时选中对应片段
      if (location) selectClip(plan.segments[location.index].clipId);
    }
    // 处理完立即作废，plan 随后的刷新不会再把播放头拉回去。
    onSeekHandled();
  }, [seekRequest, seek, plan, onSeekHandled, selectClip]);

  const trimIgnored = useMemo(() => issueClipIds(readout, "trim_ignored"), [readout]);
  const unused = useMemo(() => unusedUnitIds(readout), [readout]);
  const thumbnails = useMemo(() => unitThumbnails(script), [script]);
  const positions = useMemo(() => unitPositions(script), [script]);
  const activeClipId = plan.segments[playback.index]?.clipId ?? null;
  const currentClip = useMemo(() => readout.clips.find((clip) => clip.id === activeClipId), [readout.clips, activeClipId]);
  const selectedClip = useMemo(() => readout.clips.find((clip) => clip.id === selectedClipId), [readout.clips, selectedClipId]);
  const clipIds = useMemo(() => new Set(readout.clips.map((clip) => clip.id)), [readout]);

  // 播放器在左、详情栏在右，轨道横跨底部全宽。详情栏随画布宽度取 280px 或 340px。
  return (
    <div ref={workspace} className="@container-size/edit-workspace grid min-h-0 flex-1 grid-cols-[minmax(0,1fr)_280px] grid-rows-[minmax(0,1fr)_auto_auto] gap-x-3 @6xl/canvas:grid-cols-[minmax(0,1fr)_340px]">
      <div className="min-h-0 min-w-0">
        <EditTimelinePlayer
          plan={plan}
          playback={playback}
          aspect={aspect}
          current={currentClip}
          positions={positions}
          trimIgnored={currentClip ? trimIgnored.has(currentClip.id) : false}
          subtitles={subtitles}
          showSubtitles={showSubtitles}
          onToggleSubtitles={() => setShowSubtitles((shown) => !shown)}
        />
      </div>
      {/* 详情栏是视图里唯一的滚动区；可以只有说明文字，所以自身可聚焦，键盘也能滚动 */}
      <div
        role="region"
        aria-label={t("edit_view_details_aria")}
        // eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex -- 详情栏可能只有说明文字，须能用键盘聚焦后滚动
        tabIndex={0}
        className="focus-ring relative flex min-h-0 flex-col gap-4 overflow-y-auto rounded-lg border border-border bg-card p-4"
      >
        <section className="shrink-0" aria-label={t("edit_view_inspector_aria")}>
          {selectedSubtitle ? (
            <SubtitleInspector
              key={`${selectedSubtitle.id}:${selectedSubtitle.text}`}
              subtitle={selectedSubtitle}
              input={subtitleInput}
              saving={saving}
              onSave={(text) => editSubtitle(selectedSubtitle.id, { text })}
            />
          ) : (
            <ClipInspector
              projectName={projectName}
              clip={selectedClip}
              trimIgnored={selectedClip ? trimIgnored.has(selectedClip.id) : false}
              thumbnail={selectedClip ? thumbnails.get(selectedClip.unit_id) : undefined}
              videoUrl={selectedClip ? videoUrls.get(selectedClip.id) : undefined}
              positions={positions}
            />
          )}
        </section>
        <div className="shrink-0 border-t border-border pt-4">
          <IssueList issues={readout.issues} clipIds={clipIds} positions={positions} onSelectClip={selectClip} />
        </div>
      </div>
      <div
        role="separator"
        aria-orientation="horizontal"
        aria-label={t("edit_view_resize_tracks")}
        tabIndex={0}
        className="focus-ring group col-span-2 flex h-4 touch-none cursor-row-resize select-none items-center justify-center"
        onPointerDown={(event) => {
          if (event.button !== 0 || divider.current || !workspace.current || !tracksPanel.current) return;
          event.currentTarget.setPointerCapture(event.pointerId);
          const height = tracksPanel.current.offsetHeight;
          divider.current = { from: event.clientY, height, next: height, max: Math.max(133, workspace.current.clientHeight - 128), frame: 0 };
        }}
        onPointerMove={(event) => {
          const drag = divider.current;
          if (!drag || !event.currentTarget.hasPointerCapture(event.pointerId)) return;
          drag.next = drag.height + drag.from - event.clientY;
          if (!drag.frame) drag.frame = requestAnimationFrame(() => {
            drag.frame = 0;
            resizeTracks(drag.next, drag.max);
          });
        }}
        onLostPointerCapture={() => {
          const drag = divider.current;
          if (drag && (drag.frame || drag.next !== drag.height)) {
            cancelAnimationFrame(drag.frame);
            resizeTracks(drag.next, drag.max, true);
          }
          divider.current = null;
        }}
        onKeyDown={(event) => {
          const current = tracksPanel.current?.offsetHeight ?? 0;
          const max = Math.max(133, (workspace.current?.clientHeight ?? 0) - 128);
          const height = event.key === "Home" ? 0 : event.key === "End" ? max
            : event.key === "ArrowUp" ? current + 24 : event.key === "ArrowDown" ? current - 24 : null;
          if (height !== null) {
            event.preventDefault();
            resizeTracks(height, max, true);
          }
        }}
      >
        <div className="h-0.5 w-12 rounded-full bg-muted-foreground/50 group-hover:bg-cyan-400 group-focus-visible:bg-cyan-400" />
      </div>
      <div ref={tracksPanel} className="col-span-2 min-w-0">
        <EditTimelineTracks
          projectName={projectName}
          readout={readout}
          t={playback.t}
          playing={playback.playing}
          selectedClipId={selectedClipId}
          activeClipId={activeClipId}
          trimIgnored={trimIgnored}
          unusedUnits={unused}
          positions={positions}
          thumbnails={thumbnails}
          videoUrls={videoUrls}
          audio={audio}
          rows={rows}
          waveforms={waveforms}
          analysisStatus={analysisStatus}
          mutedTracks={mutedTracks}
          onToggleTrack={toggleTrack}
          selectedAudioId={selectedAudioId}
          onSelectAudio={selectAudio}
          subtitles={subtitles}
          onSelectClip={selectClip}
          selectedSubtitleId={selectedSubtitle?.id ?? null}
          onSelectSubtitle={selectSubtitle}
          onFocusSubtitle={focusSubtitle}
          onEditSubtitle={editSubtitle}
          onSeek={playback.seek}
          onPause={playback.pause}
          onTogglePlayback={playback.toggle}
          onStepFrame={playback.stepFrame}
          saving={saving}
          canUndo={canUndo}
          canRedo={canRedo}
          onEdit={save}
        />
      </div>
    </div>
  );
}

function SubtitleInspector({ subtitle, input, saving, onSave }: {
  subtitle: PlacedSubtitle;
  input: React.RefObject<HTMLTextAreaElement | null>;
  saving: boolean;
  onSave: (text: string) => void;
}) {
  const { t } = useTranslation("dashboard");
  const [draft, setDraft] = useState(subtitle.text);
  const text = draft.trim();
  const canSave = !saving && !!text && text !== subtitle.text;
  return (
    <form className="space-y-2" onSubmit={(event) => { event.preventDefault(); if (canSave) onSave(text); }}>
      <h3 className="text-sm font-medium">{t("edit_view_subtitle_text")}</h3>
      <Textarea
        ref={input}
        aria-label={t("edit_view_subtitle_text")}
        value={draft}
        maxLength={2000}
        disabled={saving}
        onChange={(event) => setDraft(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter" && (event.ctrlKey || event.metaKey) && !event.nativeEvent.isComposing) {
            event.preventDefault();
            if (canSave) onSave(text);
          }
        }}
      />
      <Button type="submit" size="sm" disabled={!canSave}>{t("edit_view_subtitle_save")}</Button>
    </form>
  );
}

function Centered({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-0 flex-1 flex-col items-center justify-center gap-3 px-6 text-center text-sm text-muted-foreground">
      {children}
    </div>
  );
}

function LoadFailed({ message, onRetry }: { message: string; onRetry: () => void }) {
  const { t } = useTranslation("dashboard");
  return (
    <Centered>
      <p role="alert" className="text-destructive">
        {t("edit_view_load_failed", { message })}
      </p>
      <Button variant="outline" size="sm" onClick={onRetry}>
        {t("edit_view_retry")}
      </Button>
    </Centered>
  );
}
