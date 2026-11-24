import { ContextMenu } from "@base-ui/react/context-menu";
import { cn } from "cn";
import { AlertTriangle, AudioLines, Captions, Loader2, Magnet, Maximize, Music2, Redo2, Scissors, Trash2, Undo2, Upload, Video, Volume2, VolumeX, ZoomIn, ZoomOut } from "lucide-react";
import {
  memo,
  useEffect,
  useEffectEvent,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type ChangeEvent,
  type CSSProperties,
  type PointerEvent,
  type ReactNode,
} from "react";
import { useTranslation } from "react-i18next";

import { API } from "@/api";
import { Button } from "@/components/ui/button";
import { Dialog, DialogBody, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { TooltipIconButton } from "@/components/canvas/timeline/TooltipIconButton";
import { useAppStore } from "@/stores/app-store";
import { useProjectsStore } from "@/stores/projects-store";
import { errMsg } from "@/utils/async";
import type { EditClip, EditTimelineReadout, ProjectBgm, TimelineClipOperation, TimelineSubtitle } from "@/types/edit-timeline";

import type { AudioPlacement, AudioRow, PlacedSubtitle } from "./preview-tracks";
import { ItemPositionBadge } from "@/components/shared/episode-item/ItemPositionBadge";
import { itemPositionLabel } from "@/utils/episode-display";
import { episodeItemKind } from "@/utils/episode-item";
import { formatSeconds, unitPositionLabel } from "./timeline-view";
import { TIMELINE_FPS, timelineFrameAt, trimApplies } from "./playback-schedule";
import type { Waveform } from "./useTimelineAudioAnalysis";
import { timelineThumbnail } from "./timeline-thumbnails";

function percentOf(seconds: number, duration: number): string {
  return duration > 0 ? `${(seconds / duration) * 100}%` : "0%";
}
const SCROLL_BAND = 256;
const TRAILING_SPACE = 32;
const MAX_PIXELS_PER_SECOND = TIMELINE_FPS * 60;
const VIDEO_HEIGHT = "h-(--edit-video-height)";
const ROW_HEIGHT = "h-(--edit-subtitle-height)";
const AUDIO_HEIGHT = "h-(--edit-audio-height)";
const AUDIO_LABELS = {
  narration: "edit_view_track_narration",
  dialogue: "edit_view_track_dialogue",
  source: "edit_view_track_source",
  sfx: "edit_view_track_sfx",
  bgm: "edit_view_track_bgm",
} as const;

const MIN_TRIM = 0.1;

type EditDrag = {
  mode: "move" | "in" | "out";
  from: number;
  scroll: number;
  moved: boolean;
  revision: number;
} & ({ clip: EditClip } | { subtitle: PlacedSubtitle; gaps?: TimeBounds[] }
  | { audio: AudioPlacement; ghost: HTMLElement | null; gaps: TimeBounds[] });

type TimeBounds = { start: number; end: number };
type MediaTarget = { clip: EditClip } | { audio: AudioPlacement };
type BlockTarget = MediaTarget | { subtitle: PlacedSubtitle };

function audioEdit(item: AudioPlacement, bounds: TimeBounds | null, mode?: EditDrag["mode"]): TimelineClipOperation {
  if (item.kind === "bgm" || (item.kind === "sfx" && !item.stem)) {
    if (!bounds) return { op: "delete_bgm", clip: item.editId };
    if (mode === "move") return { op: "set_bgm", clip: item.editId, start: bounds.start };
    return mode === "in"
      ? { op: "set_bgm", clip: item.editId, start: bounds.start, source_in: item.sourceIn + bounds.start - item.start }
      : { op: "set_bgm", clip: item.editId, source_out: item.sourceIn + bounds.end - item.start };
  }
  if (!bounds) return { op: "set_clip_audio", clip: item.editId,
    kind: item.kind, window: false };
  const offset = mode === "in" ? bounds.start - item.start : 0;
  const length = mode === "out" ? bounds.end - bounds.start : item.length - offset;
  return audioWindowEdit(item, bounds.start, item.sourceIn + offset, item.sourceIn + offset + length);
}

function audioWindowEdit(item: AudioPlacement, start: number, sourceIn: number, sourceOut: number): TimelineClipOperation {
  if (item.kind === "bgm" || (item.kind === "sfx" && !item.stem)) {
    return { op: "set_bgm", clip: item.editId, start, source_in: sourceIn, source_out: sourceOut };
  }
  return { op: "set_clip_audio", clip: item.editId, kind: item.kind,
    window: { start_us: Math.round(start * 1e6), source_in_us: Math.round(sourceIn * 1e6),
      duration_us: Math.round(sourceOut * 1e6) - Math.round(sourceIn * 1e6) } };
}

function canEditBlock(target: BlockTarget | null) {
  if (!target) return false;
  if ("clip" in target) return target.clip.status === "ready" && target.clip.video_version != null &&
    (target.clip.source_duration ?? 0) >= MIN_TRIM;
  return true;
}

function trackGaps(items: readonly (TimeBounds & { id: string })[], id: string, duration: number) {
  const gaps: TimeBounds[] = [];
  let start = 0;
  for (const item of items) {
    if (item.id === id) continue;
    if (item.start >= duration) break;
    if (item.start > start) gaps.push({ start, end: item.start });
    start = Math.max(start, item.end);
  }
  if (duration > start) gaps.push({ start, end: duration });
  return gaps;
}

function lowerBound<T>(items: readonly T[], value: number, position: (item: T) => number): number {
  let low = 0;
  let high = items.length;
  while (low < high) {
    const mid = (low + high) >>> 1;
    if (position(items[mid]) < value) low = mid + 1;
    else high = mid;
  }
  return low;
}

function sourceBounds(clip: EditClip) {
  return trimApplies(clip) && clip.trim ? [clip.trim.source_in, clip.trim.source_out] : [0, clip.source_duration ?? 0];
}

interface EditTimelineTracksProps {
  projectName: string;
  readout: EditTimelineReadout;
  t: number;
  playing: boolean;
  selectedClipId: string | null;
  activeClipId: string | null;
  trimIgnored: ReadonlySet<string>;
  unusedUnits: readonly string[];
  positions: ReadonlyMap<string, number>;
  thumbnails: ReadonlyMap<string, string>;
  videoUrls: ReadonlyMap<string, string>;
  audio: readonly AudioPlacement[];
  waveforms: ReadonlyMap<string, Waveform>;
  rows: readonly AudioRow[];
  mutedTracks: ReadonlySet<string>;
  onToggleTrack: (id: string) => void;
  analysisStatus: "pending" | "failed" | null;
  selectedAudioId: string | null;
  onSelectAudio: (id: string) => void;
  subtitles: readonly PlacedSubtitle[];
  selectedSubtitleId: string | null;
  onSelectSubtitle: (id: string) => void;
  onFocusSubtitle: (subtitle: PlacedSubtitle) => void;
  onEditSubtitle: (id: string, change: Partial<Omit<TimelineSubtitle, "id">> | null) => void;
  onSelectClip: (clipId: string | null) => void;
  onSeek: (t: number, byFrame?: boolean) => void;
  onPause: () => void;
  onTogglePlayback: () => void;
  onStepFrame: (direction: -1 | 1) => void;
  saving: boolean;
  canUndo: boolean;
  canRedo: boolean;
  onEdit: (action: TimelineClipOperation | "undo" | "redo") => void;
}

export function EditTimelineTracks({
  projectName, readout, t, playing, selectedClipId, activeClipId, trimIgnored, unusedUnits,
  positions, thumbnails, videoUrls, audio, selectedAudioId, onSelectAudio, subtitles, onSelectClip, onSeek, onPause, onTogglePlayback, onStepFrame,
  saving, canUndo, canRedo, onEdit, selectedSubtitleId, onSelectSubtitle, onFocusSubtitle, onEditSubtitle,
  rows, waveforms, mutedTracks, onToggleTrack, analysisStatus,
}: EditTimelineTracksProps) {
  const { t: translate } = useTranslation("dashboard");
  const { t: common } = useTranslation("common");
  const viewport = useRef<HTMLDivElement>(null);
  const trackArea = useRef<HTMLDivElement>(null);
  const [shownRows, setShownRows] = useState(Infinity);
  const [menuTarget, setMenuTarget] = useState<BlockTarget | null>(null);
  const [editor, setEditor] = useState<{ target: MediaTarget; revision: number } | null>(null);
  const drag = useRef<{ id: number; x: number; left: number; frame: number; last: number; edit?: EditDrag } | null>(null);
  const guide = useRef<HTMLDivElement>(null);
  const subtitleGhost = useRef<HTMLDivElement>(null);
  const suppressClick = useRef(false);
  const zoomAnchor = useRef<{ time: number; x: number } | null>(null);
  const [width, setWidth] = useState(0);
  const [band, setBand] = useState(0);
  const [zoom, setZoom] = useState(0);
  const [snap, setSnap] = useState(true);
  const [scrubbing, setScrubbing] = useState(false);
  const duration = readout.duration;
  const fit = Math.min(MAX_PIXELS_PER_SECOND, Math.max(1, width - TRAILING_SPACE) / (duration || 1));
  const scale = fit * (MAX_PIXELS_PER_SECOND / fit) ** (zoom / 100);
  const span = duration * scale;
  const start = Math.max(0, (band - 1) * SCROLL_BAND) / scale;
  const end = ((band + 2) * SCROLL_BAND + width) / scale;
  const clips = readout.clips;
  const cuts = useMemo(() => [...new Set([0, ...clips.map((clip) => clip.start), duration])].sort((a, b) => a - b), [clips, duration]);
  const visibleClips = useMemo(() => clips.slice(
    lowerBound(clips, start, (clip) => clip.start + clip.duration),
    lowerBound(clips, end, (clip) => clip.start),
  ), [clips, start, end]);
  const hasSubtitles = subtitles.length > 0;
  const horizontalScrollbar = width > 0 && span + TRAILING_SPACE > width + 0.5 ? 10 : 0;
  const foldedCount = Math.max(0, rows.length + Number(hasSubtitles) - shownRows);
  const overlayHeight = foldedCount ? Math.min(12, 26 / foldedCount) : 0;
  const foldStyle = (index: number) => index < shownRows ? undefined : {
    height: overlayHeight,
    top: `calc(var(--edit-video-height) - ${(shownRows + foldedCount - index) * overlayHeight}px)`,
  };
  const bgmSpans = useMemo(() => readout.bgm.filter((item) => item.kind !== "sfx").map((item) => ({
    id: item.id, start: item.start, end: item.start + item.source_out - item.source_in,
  })), [readout.bgm]);
  const visibleAudio = useMemo(() => rows.map(({ items }) => items.slice(
    lowerBound(items, start, (item) => item.end), lowerBound(items, end, (item) => item.start),
  )), [rows, start, end]);
  const audioById = useMemo(() => new Map(audio.map((item) => [item.id, item])), [audio]);
  const selectedAudio = selectedAudioId ? audioById.get(selectedAudioId) : undefined;
  const visibleSubtitles = useMemo(() => subtitles.slice(
    lowerBound(subtitles, start, (item) => item.end), lowerBound(subtitles, end, (item) => item.start),
  ), [subtitles, start, end]);
  const liveClips = useMemo(() => clips.filter((clip) => clip.status !== "unit_deleted"), [clips]);
  const lastLiveId = liveClips.at(-1)?.id;
  const selected = useMemo(() => clips.find((clip) => clip.id === selectedClipId), [clips, selectedClipId]);
  const active = useMemo(() => clips.find((clip) => clip.id === activeClipId), [clips, activeClipId]);
  const selectedSubtitle = useMemo(() => subtitles.find((item) => item.id === selectedSubtitleId), [subtitles, selectedSubtitleId]);
  const splitClip = selectedSubtitle || selectedAudio ? undefined : selected ?? active;
  const removeBlock = (target: BlockTarget | null) => {
    if (saving || !target) return;
    viewport.current?.focus({ preventScroll: true });
    if ("audio" in target) onEdit(audioEdit(target.audio, null));
    else if ("subtitle" in target) onEditSubtitle(target.subtitle.id, null);
    else onEdit({ op: "delete", clip: target.clip.id });
  };
  const removeSelection = () => removeBlock(selectedAudio ? { audio: selectedAudio }
    : selectedSubtitle ? { subtitle: selectedSubtitle } : selected ? { clip: selected } : null);
  const splitTime = splitClip ? sourceBounds(splitClip)[0] + timelineFrameAt(t) / TIMELINE_FPS - splitClip.start : 0;
  const splitBounds = splitClip ? sourceBounds(splitClip) : [0, 0];
  const canSplit = splitClip?.video_version != null && splitTime - splitBounds[0] >= MIN_TRIM - 0.0001
    && splitBounds[1] - splitTime >= MIN_TRIM - 0.0001;
  const split = () => {
    if (!saving && canSplit && splitClip.video_version != null) {
      onEdit({ op: "split", clip: splitClip.id, source_time: splitTime, source_version: splitClip.video_version });
    }
  };

  useLayoutEffect(() => {
    const node = viewport.current;
    if (!node) return;
    const measure = () => setWidth(node.clientWidth);
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  useLayoutEffect(() => {
    const area = trackArea.current;
    if (!area) return;
    const measure = () => {
      const style = getComputedStyle(area);
      const height = (name: string) => parseFloat(style.getPropertyValue(`--edit-${name}-height`));
      let available = area.getBoundingClientRect().height - 28 - horizontalScrollbar - height("video");
      const subtitleHeight = height("subtitle");
      const audioHeight = height("audio");
      let count = 0;
      // Always measure original row positions, not rows already moved onto video.
      if (hasSubtitles) {
        if (available < subtitleHeight * 0.1) { setShownRows(0); return; }
        count++;
        available -= subtitleHeight;
      }
      while (count < rows.length + Number(hasSubtitles) && available >= audioHeight * 0.1) {
        count++;
        available -= audioHeight;
      }
      setShownRows(count);
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(area);
    return () => observer.disconnect();
  }, [hasSubtitles, horizontalScrollbar, rows.length]);

  useLayoutEffect(() => {
    const node = viewport.current;
    const anchor = zoomAnchor.current;
    if (!node || !anchor) return;
    zoomAnchor.current = null;
    node.scrollLeft = anchor.time * scale - anchor.x;
    setBand(Math.floor(node.scrollLeft / SCROLL_BAND));
  }, [scale, zoom]);

  const changeZoom = (value: number, at?: number) => {
    const node = viewport.current;
    const next = Math.min(100, Math.max(0, value));
    if (!node || next === zoom || drag.current) return;
    const playhead = t * scale - node.scrollLeft;
    const x = at ?? (playhead >= 0 && playhead < width ? playhead : width / 2);
    zoomAnchor.current = { x, time: (node.scrollLeft + x) / scale };
    setZoom(next);
  };

  const wheel = useEffectEvent((event: WheelEvent) => {
    const node = viewport.current;
    if (!node || event.deltaY === 0) return;
    if (event.ctrlKey) {
      event.preventDefault();
      changeZoom(zoom - Math.sign(event.deltaY) * 4, event.clientX - node.getBoundingClientRect().left);
    } else if (event.deltaX === 0 && node.scrollWidth > node.clientWidth &&
        (event.shiftKey || !node.parentElement || node.parentElement.scrollHeight <= node.parentElement.clientHeight)) {
      event.preventDefault();
      const pixels = event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? width : 1;
      node.scrollLeft += event.deltaY * pixels;
    }
  });
  useEffect(() => {
    const node = viewport.current;
    if (!node) return;
    const onWheel = (event: WheelEvent) => wheel(event);
    node.addEventListener("wheel", onWheel, { passive: false });
    return () => node.removeEventListener("wheel", onWheel);
  }, []);

  const snapTime = (raw: number) => {
    if (snap) {
      const i = lowerBound(cuts, raw, (cut) => cut);
      const before = cuts[i - 1] ?? -Infinity;
      const after = cuts[i] ?? Infinity;
      const closest = raw - before <= after - raw ? before : after;
      if (Math.abs(closest - raw) * scale <= 8) return closest;
    }
    return Math.round(raw * TIMELINE_FPS) / TIMELINE_FPS;
  };

  const subtitleAtPointer = (edit: Extract<EditDrag, { subtitle: PlacedSubtitle }>, x: number, scroll: number) => {
    const { subtitle, mode } = edit;
    const gaps = edit.gaps ??= trackGaps(subtitles, subtitle.id, duration).filter((gap) =>
      mode !== "move" || gap.end - gap.start >= subtitle.end - subtitle.start - 1e-7,
    );
    const delta = (x + scroll - edit.from - edit.scroll) / scale;
    const length = subtitle.end - subtitle.start;
    const minimum = Math.min(length, 1 / TIMELINE_FPS);
    const clamp = (value: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, value));
    if (mode === "move") {
      const desired = snapTime(subtitle.start + delta);
      const min = (gap: { start: number; end: number }) => gap.start;
      const i = lowerBound(gaps, desired, min);
      // Only gaps that can fit the entire subtitle are kept at gesture start.
      const choices = [gaps[i - 1], gaps[i]].filter((gap) => gap !== undefined);
      let nearest = subtitle.start;
      let distance = Infinity;
      for (const gap of choices) {
        const at = clamp(desired, gap.start, Math.max(gap.start, gap.end - length));
        if (Math.abs(desired - at) < distance) {
          nearest = at;
          distance = Math.abs(desired - at);
        }
      }
      return { start: nearest, end: nearest + length };
    }
    const gap = gaps[lowerBound(gaps, subtitle.end, (item) => item.end)];
    if (!gap) return subtitle;
    return mode === "in"
      ? { start: clamp(snapTime(subtitle.start + delta), gap.start, subtitle.end - minimum), end: subtitle.end }
      : { start: subtitle.start, end: clamp(snapTime(subtitle.end + delta), subtitle.start + minimum, gap.end) };
  };

  const audioAtPointer = (edit: Extract<EditDrag, { audio: AudioPlacement }>, x: number, scroll: number): TimeBounds => {
    const { audio: item, mode, gaps } = edit;
    const delta = (x + scroll - edit.from - edit.scroll) / scale;
    const min = Math.min(MIN_TRIM, item.end - item.start);
    const clamp = (value: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, value));
    if (mode === "in") return { start: clamp(snapTime(item.start + delta), item.start, item.end - min), end: item.end };
    if (mode === "out") return { start: item.start, end: clamp(snapTime(item.end + delta), item.start + min, item.end) };
    const desired = snapTime(item.start + delta);
    const i = lowerBound(gaps, desired, (gap) => gap.start);
    let at = item.start;
    let distance = Infinity;
    const length = Math.min(item.length, duration);
    for (const gap of [gaps[i - 1], gaps[i]]) {
      if (!gap) continue;
      const next = clamp(desired, gap.start, Math.max(gap.start, gap.end - length));
      if (Math.abs(next - desired) < distance) {
        at = next;
        distance = Math.abs(next - desired);
      }
    }
    return { start: at, end: Math.min(duration, at + item.length) };
  };

  const editAtPointer = (edit: Extract<EditDrag, { clip: EditClip }>, x: number, scroll: number) => {
    const { clip, mode } = edit;
    if (mode === "move") {
      const raw = (x + scroll) / scale;
      const index = lowerBound(liveClips, raw, (item) => item.start + item.duration / 2);
      const next = liveClips[liveClips[index]?.id === clip.id ? index + 1 : index];
      const previous = liveClips[liveClips[index - 1]?.id === clip.id ? index - 2 : index - 1];
      const at = next?.start ?? (previous ? previous.start + previous.duration : 0);
      return { at, operation: { op: "move", clip: clip.id, after: previous?.id ?? null } as const };
    }
    const [lo, hi] = sourceBounds(clip);
    const dx = (x + scroll - edit.from - edit.scroll) / scale;
    const delta = Math.round(dx * TIMELINE_FPS) / TIMELINE_FPS;
    const whole = clip.source_duration ?? hi;
    const source_in = mode === "in" ? Math.min(hi - MIN_TRIM, Math.max(0, lo + delta)) : lo;
    const source_out = mode === "out" ? Math.max(lo + MIN_TRIM, Math.min(whole, hi + delta)) : hi;
    const at = clip.start + (mode === "in" ? source_in - lo : source_out - lo + clip.hold);
    const operation = clip.video_version != null && (Math.abs(source_in - lo) > 0.0001 || Math.abs(source_out - hi) > 0.0001)
      ? { op: "set_trim", clip: clip.id, trim: { source_in, source_out, source_version: clip.video_version } } as const
      : null;
    return { at, operation };
  };

  const syncPointer = () => {
    const node = viewport.current;
    const pointer = drag.current;
    if (!node || !pointer) return;
    const x = pointer.x - pointer.left;
    if (pointer.edit) {
      const edit = pointer.edit;
      edit.moved ||= Math.abs(x - edit.from) >= 4 || Math.abs(node.scrollLeft - edit.scroll) >= 4;
      if (edit.moved && "subtitle" in edit && subtitleGhost.current) {
        const bounds = subtitleAtPointer(edit, x, node.scrollLeft);
        const ghost = subtitleGhost.current;
        ghost.hidden = false;
        ghost.style.transform = `translateX(${bounds.start * scale}px)`;
        ghost.style.width = `${Math.max(1, (bounds.end - bounds.start) * scale)}px`;
      } else if (edit.moved && "audio" in edit && edit.ghost) {
        const bounds = audioAtPointer(edit, x, node.scrollLeft);
        edit.ghost.hidden = false;
        edit.ghost.style.transform = `translateX(${bounds.start * scale}px)`;
        edit.ghost.style.width = `${Math.max(1, (bounds.end - bounds.start) * scale)}px`;
      } else if (edit.moved && "clip" in edit && guide.current) {
        const { at } = editAtPointer(edit, x, node.scrollLeft);
        guide.current.hidden = false;
        guide.current.style.transform = `translateX(${Math.max(0, at) * scale}px)`;
      }
      return;
    }
    const raw = (node.scrollLeft + Math.min(node.clientWidth, Math.max(0, x))) / scale;
    const time = Math.max(0, Math.min(duration, snapTime(raw)));
    if (time === pointer.last) return;
    pointer.last = time;
    onSeek(time, true);
  };

  const scrubFrame = () => {
    const node = viewport.current;
    const pointer = drag.current;
    if (!node || !pointer) return;
    pointer.frame = 0;
    const x = pointer.x - pointer.left;
    const right = node.clientWidth - 24;
    const delta = x < 24 ? x - 24 : x > right ? x - right : 0;
    const previous = node.scrollLeft;
    if (delta) node.scrollLeft += Math.max(-32, Math.min(32, delta * 0.5));
    syncPointer();
    if (node.scrollLeft !== previous) pointer.frame = requestAnimationFrame(scrubFrame);
  };

  const blockAt = (target: Element) => {
    const button = target.closest<HTMLElement>("button");
    const clip = button?.dataset.clipId ? visibleClips.find((item) => item.id === button.dataset.clipId) : undefined;
    const subtitle = button?.dataset.subtitleId ? visibleSubtitles.find((item) => item.id === button.dataset.subtitleId) : undefined;
    const item = button?.dataset.audioId ? audioById.get(button.dataset.audioId) : undefined;
    return { button, clip, subtitle, item };
  };
  const startScrub = (event: PointerEvent<HTMLDivElement>) => {
    if (event.button !== 0 || !event.isPrimary || drag.current || !duration) return;
    suppressClick.current = false;
    const target = event.target as Element;
    const { button, clip, subtitle, item } = blockAt(target);
    if (button && ((!clip && !subtitle && !item) || saving)) return;
    const node = event.currentTarget;
    // Keep the native horizontal scrollbar draggable.
    if (event.clientY - node.getBoundingClientRect().top >= node.clientHeight) return;
    const left = node.getBoundingClientRect().left;
    const edge = target.closest<HTMLElement>("[data-trim-edge]")?.dataset.trimEdge;
    const mode = edge === "in" || edge === "out" ? edge : "move";
    const gesture = { mode, from: event.clientX - left, scroll: node.scrollLeft, moved: false, revision: readout.revision } as const;
    let edit: EditDrag | undefined;
    if (clip?.status === "unit_deleted") return;
    if (clip) edit = { ...gesture, clip };
    else if (subtitle) edit = { ...gesture, subtitle };
    else if (item) edit = {
      ...gesture, audio: item, ghost: button?.parentElement?.querySelector<HTMLElement>("[data-audio-ghost]") ?? null,
      gaps: item.kind === "bgm" && mode === "move"
        ? trackGaps(bgmSpans, item.editId, duration).filter((gap) => gap.end - gap.start >= Math.min(item.length, duration) - 1e-7)
        : [{ start: 0, end: duration }],
    };
    node.focus({ preventScroll: true });
    // Keep native clicks and double-clicks on subtitle buttons until an actual drag starts.
    if (!subtitle && !item) node.setPointerCapture(event.pointerId);
    drag.current = { id: event.pointerId, x: event.clientX, left, frame: 0, last: -1, edit };
    setScrubbing(true);
    if (playing) onPause();
    if (clip) onSelectClip(clip.id);
    else if (subtitle) onSelectSubtitle(subtitle.id);
    else if (item) onSelectAudio(item.id);
    else {
      onSelectClip(null);
      syncPointer();
    }
  };

  const stopScrub = (event: PointerEvent<HTMLDivElement>) => {
    const pointer = drag.current;
    if (!pointer || pointer.id !== event.pointerId) return;
    cancelAnimationFrame(pointer.frame);
    if (event.type === "pointerup") {
      pointer.x = event.clientX;
      syncPointer();
      const edit = pointer.edit;
      const node = viewport.current;
      if (edit?.moved && node && !saving && edit.revision === readout.revision) {
        const x = pointer.x - pointer.left;
        if ("subtitle" in edit) {
          const bounds = subtitleAtPointer(edit, x, node.scrollLeft);
          if (Math.abs(bounds.start - edit.subtitle.start) > 0.000001 || Math.abs(bounds.end - edit.subtitle.end) > 0.000001) {
            onEditSubtitle(edit.subtitle.id, { start_us: Math.round(bounds.start * 1e6), end_us: Math.round(bounds.end * 1e6) });
          }
        } else if ("audio" in edit) {
          const bounds = audioAtPointer(edit, x, node.scrollLeft);
          if (Math.abs(bounds.start - edit.audio.start) > 1e-6 || Math.abs(bounds.end - edit.audio.end) > 1e-6) {
            onEdit(audioEdit(edit.audio, bounds, edit.mode));
          }
        } else {
          const { operation } = editAtPointer(edit, x, node.scrollLeft);
          const index = liveClips.findIndex((item) => item.id === edit.clip.id);
          const previous = liveClips[index - 1]?.id ?? null;
          if (operation && (operation.op !== "move" || operation.after !== previous)) onEdit(operation);
        }
      }
    }
    if (guide.current) guide.current.hidden = true;
    if (subtitleGhost.current) subtitleGhost.current.hidden = true;
    if (pointer.edit && "audio" in pointer.edit && pointer.edit.ghost) pointer.edit.ghost.hidden = true;
    suppressClick.current = pointer.edit?.moved ?? false;
    drag.current = null;
    setScrubbing(false);
  };
  useEffect(() => () => cancelAnimationFrame(drag.current?.frame ?? 0), []);

  const insertAudio = (kind: "bgm" | "sfx", asset: ProjectBgm) => {
    const min = Math.min(MIN_TRIM, asset.duration);
    if (min <= 0) return false;
    const desired = Math.min(Math.max(0, duration - min), timelineFrameAt(t) / TIMELINE_FPS);
    const gaps = kind === "bgm" ? trackGaps(bgmSpans, "", duration) : [{ start: 0, end: duration }];
    let choice: { at: number; length: number } | undefined;
    for (const gap of gaps) {
      if (gap.end - gap.start < min - 1e-7) continue;
      const at = Math.min(gap.end - min, Math.max(desired, gap.start));
      if (!choice || Math.abs(at - desired) < Math.abs(choice.at - desired)) choice = { at, length: Math.min(gap.end - at, asset.duration) };
    }
    if (!choice || choice.length < min - 1e-7 || saving) return false;
    onEdit({ op: "insert_bgm", bgm_id: asset.id, kind, start: choice.at, source_out: choice.length,
      ...(kind === "sfx" ? { volume: 1, fade_in: 0, fade_out: 0 } : {}) });
    return true;
  };

  return (
    <div className="edit-track-panel flex flex-col overflow-hidden rounded-lg border border-border bg-sidebar/60"
      style={{ "--edit-track-scrollbar": `${horizontalScrollbar}px` } as CSSProperties}>
      <div className="flex h-9 shrink-0 items-center justify-between gap-2 border-b border-border px-2">
        <div className="flex min-w-0 items-center gap-1">
          <TooltipIconButton label={translate("edit_view_timeline_undo")} shortcut="Ctrl+Z" onClick={() => onEdit("undo")} disabled={!canUndo || saving}>
            <Undo2 aria-hidden />
          </TooltipIconButton>
          <TooltipIconButton label={translate("edit_view_timeline_redo")} shortcut="Ctrl+Shift+Z" onClick={() => onEdit("redo")} disabled={!canRedo || saving}>
            <Redo2 aria-hidden />
          </TooltipIconButton>
          <TooltipIconButton label={translate("edit_view_timeline_split")} shortcut="Ctrl+B" onClick={split} disabled={!canSplit || saving}>
            <Scissors aria-hidden />
          </TooltipIconButton>
          <TooltipIconButton label={translate(selectedAudio ? "edit_view_audio_delete" : selectedSubtitle ? "edit_view_subtitle_delete" : "edit_view_timeline_delete")} shortcut="Delete" onClick={removeSelection} disabled={(!selected && !selectedSubtitle && !selectedAudio) || saving}>
            <Trash2 aria-hidden />
          </TooltipIconButton>
          <Button
            variant="ghost"
            size="icon-sm"
            aria-label={translate("edit_view_timeline_snap")}
            title={translate("edit_view_timeline_snap")}
            onClick={() => setSnap(!snap)}
            aria-pressed={snap}
            className={snap ? "text-cyan-400" : undefined}
          >
            <Magnet aria-hidden />
          </Button>
          <AudioUploadButton projectName={projectName} kind="sfx" disabled={saving || duration <= 0} onInsert={insertAudio} />
          <AudioUploadButton projectName={projectName} kind="bgm" disabled={saving || duration <= 0} onInsert={insertAudio} />
          {analysisStatus && <span role="status" className="truncate px-1 text-xs text-muted-foreground" title={translate(`edit_view_audio_analysis_${analysisStatus}`)}>
            {translate(`edit_view_audio_analysis_${analysisStatus}`)}
          </span>}
        </div>
        <div className="flex min-w-0 items-center gap-1">
          <TooltipIconButton label={translate("edit_view_timeline_fit")} onClick={() => changeZoom(0)} disabled={zoom === 0}>
            <Maximize aria-hidden />
          </TooltipIconButton>
          <TooltipIconButton label={translate("edit_view_timeline_zoom_out")} onClick={() => changeZoom(zoom - 8)} disabled={zoom === 0}>
            <ZoomOut aria-hidden />
          </TooltipIconButton>
          <input
            type="range"
            min={0}
            max={100}
            value={zoom}
            aria-label={translate("edit_view_timeline_zoom_label")}
            className="h-4 w-12 min-w-0 cursor-pointer accent-cyan-400 sm:w-28"
            onChange={(event) => changeZoom(Number(event.target.value))}
          />
          <TooltipIconButton label={translate("edit_view_timeline_zoom_in")} onClick={() => changeZoom(zoom + 8)} disabled={zoom === 100}>
            <ZoomIn aria-hidden />
          </TooltipIconButton>
        </div>
      </div>
      <div ref={trackArea} className="edit-track-area flex min-h-0 flex-auto overflow-y-auto"
        style={{ height: `calc(28px + var(--edit-video-height) + var(--edit-subtitle-height) * ${Number(hasSubtitles)} + var(--edit-audio-height) * ${rows.length} + var(--edit-track-scrollbar))` }}>
        <div className="w-24 shrink-0 self-start border-r border-border bg-sidebar">
          <div className="h-7 border-b border-border" />
          <TrackLabel icon={Video} label={translate("edit_view_track_video")} height={VIDEO_HEIGHT} />
          {shownRows > 0 && hasSubtitles && <TrackLabel icon={Captions} label={translate("edit_view_track_subtitles")} height={ROW_HEIGHT} />}
          {rows.slice(0, Math.max(0, shownRows - Number(hasSubtitles))).map(({ id, kind }) => (
            <TrackLabel key={id} icon={kind === "bgm" ? Music2 : AudioLines} label={translate(AUDIO_LABELS[kind])} height={AUDIO_HEIGHT}>
              <TooltipIconButton
                label={translate(mutedTracks.has(id) ? "edit_view_track_unmute" : "edit_view_track_mute", { track: translate(AUDIO_LABELS[kind]) })}
                size="icon-xs" onClick={() => onToggleTrack(id)}
              >{mutedTracks.has(id) ? <VolumeX aria-hidden /> : <Volume2 aria-hidden />}</TooltipIconButton>
            </TrackLabel>
          ))}
        </div>
        <ContextMenu.Root onOpenChange={(open, details) => {
          if (!open) return;
          const target = details.event.target;
          if (!(target instanceof Element) || drag.current) { details.cancel(); return; }
          const { clip, subtitle, item } = blockAt(target);
          if (item) { setMenuTarget({ audio: item }); onSelectAudio(item.id); }
          else if (subtitle) { setMenuTarget({ subtitle }); onSelectSubtitle(subtitle.id); }
          else if (clip) { setMenuTarget({ clip }); onSelectClip(clip.id); }
          else details.cancel();
        }}>
          <ContextMenu.Trigger
            ref={viewport}
            className="focus-ring min-w-0 flex-1 self-start touch-none select-none overflow-x-auto overflow-y-hidden"
            aria-label={translate("edit_view_track_aria")}
            role="region"
            tabIndex={0}
            onScroll={(event) => setBand(Math.floor(event.currentTarget.scrollLeft / SCROLL_BAND))}
            onPointerDown={startScrub}
            onPointerMove={(event) => {
              const pointer = drag.current;
              if (!pointer || pointer.id !== event.pointerId) return;
              pointer.x = event.clientX;
              if (pointer.edit && !("clip" in pointer.edit) && !event.currentTarget.hasPointerCapture(pointer.id)) {
                if (Math.abs(pointer.x - pointer.left - pointer.edit.from) < 4) return;
                event.currentTarget.setPointerCapture(pointer.id);
              }
              if (!pointer.frame) pointer.frame = requestAnimationFrame(scrubFrame);
            }}
            onPointerUp={stopScrub}
            onPointerCancel={stopScrub}
            onPointerLeave={(event) => { if (!event.currentTarget.hasPointerCapture(event.pointerId)) stopScrub(event); }}
            onLostPointerCapture={stopScrub}
            onClickCapture={(event) => {
              if (suppressClick.current) {
                suppressClick.current = false;
                event.stopPropagation();
              }
            }}
            onKeyDown={(event) => {
              const control = event.ctrlKey || event.metaKey;
              const key = event.key.toLowerCase();
              if (event.repeat && (control || event.key === "Delete")) return;
              if (key === "escape" && drag.current) {
                const id = drag.current.id;
                if (event.currentTarget.hasPointerCapture(id)) event.currentTarget.releasePointerCapture(id);
                else {
                  drag.current = null;
                  setScrubbing(false);
                }
              } else if (drag.current) return;
              else if (control && key === "b") split();
              else if (control && (key === "z" || key === "y")) onEdit(event.shiftKey || key === "y" ? "redo" : "undo");
              else if (event.key === "Delete" && (selected || selectedSubtitle || selectedAudio)) removeSelection();
              else if ((event.key === "F2" || event.key === "Enter") && selectedSubtitle && !saving) onFocusSubtitle(selectedSubtitle);
              else if (event.code === "Space" && event.target === event.currentTarget) onTogglePlayback();
              else if (event.key === "ArrowLeft" || event.key === "ArrowRight") onStepFrame(event.key === "ArrowLeft" ? -1 : 1);
              else if (event.key === "Home" || event.key === "End") onSeek(event.key === "Home" ? 0 : duration, true);
              else return;
              event.preventDefault();
            }}
          >
            <div className="relative cursor-col-resize" style={{ width: Math.max(width, span + TRAILING_SPACE) }}>
              <Ruler duration={duration} scale={scale} start={start} end={end} />
              <div className="relative" style={{ width: span }}>
                <TrackRow height={VIDEO_HEIGHT}>
                  <VideoClips
                    clips={visibleClips}
                    lastLiveId={lastLiveId}
                    duration={duration}
                    scale={scale}
                    start={start}
                    end={end}
                    decode={!playing && !scrubbing}
                    projectName={projectName}
                    thumbnails={thumbnails}
                    videoUrls={videoUrls}
                    selectedClipId={selectedClipId}
                    activeClipId={activeClipId}
                    trimIgnored={trimIgnored}
                    positions={positions}
                    onSelectClip={onSelectClip}
                  />
                </TrackRow>
                {hasSubtitles && <TrackRow height={ROW_HEIGHT} overlay={foldStyle(0)}>
                  <SubtitleBlocks
                    subtitles={visibleSubtitles}
                    duration={duration}
                    scale={scale}
                    selectedId={selectedSubtitleId}
                    onSelect={onSelectSubtitle}
                    onFocus={onFocusSubtitle}
                  />
                  <div ref={subtitleGhost} hidden aria-hidden className="pointer-events-none absolute inset-y-1 left-0 z-10 rounded-sm border border-white bg-orange-500/40 will-change-transform" />
                </TrackRow>}
                {rows.map(({ id }, index) => (
                  <TrackRow key={id} height={AUDIO_HEIGHT} overlay={foldStyle(index + Number(hasSubtitles))}>
                    <AudioBlocks items={visibleAudio[index]} duration={duration} scale={scale} selectedId={selectedAudio?.id}
                      start={start} end={end} waveforms={waveforms} muted={mutedTracks.has(id)} positions={positions} onSelect={onSelectAudio} />
                    <div data-audio-ghost hidden aria-hidden className="pointer-events-none absolute inset-y-1 left-0 z-10 rounded-sm border border-white bg-cyan-500/40 will-change-transform" />
                  </TrackRow>
                ))}
              </div>
              <div ref={guide} hidden aria-hidden className="pointer-events-none absolute inset-y-0 left-0 z-10 w-0.5 bg-cyan-400 will-change-transform" />
              <div
                aria-hidden
                data-testid="edit-playhead"
                className="pointer-events-none absolute inset-y-0 left-0 z-10 w-px bg-white will-change-transform"
                style={{ transform: `translateX(${Math.max(0, Math.min(t, duration)) * scale}px)` }}
              >
                <span className="absolute top-0 -left-[3px] h-3 w-[7px] rounded-b-sm border-2 border-white bg-sidebar" />
              </div>
            </div>
          </ContextMenu.Trigger>
          <ContextMenu.Portal>
            <ContextMenu.Positioner className="z-overlay">
              <ContextMenu.Popup className="min-w-32 rounded-lg bg-popover p-1 text-sm text-popover-foreground shadow-overlay ring-1 ring-foreground/10 outline-none [&>[role=menuitem]]:cursor-default [&>[role=menuitem]]:rounded-sm [&>[role=menuitem]]:px-2 [&>[role=menuitem]]:py-1.5 [&>[data-highlighted]]:bg-accent [&>[data-disabled]]:opacity-50">
                <ContextMenu.Item disabled={saving} onClick={() => removeBlock(menuTarget)}>{common("delete")}</ContextMenu.Item>
                <ContextMenu.Item disabled={saving || !canEditBlock(menuTarget)} onClick={() => {
                  if (!menuTarget) return;
                  if ("subtitle" in menuTarget) onFocusSubtitle(menuTarget.subtitle);
                  else {
                    onPause();
                    setEditor({ target: menuTarget, revision: readout.revision });
                  }
                }}>{common("edit")}</ContextMenu.Item>
                <ContextMenu.Item disabled>{translate("edit_view_regenerate_block")}</ContextMenu.Item>
              </ContextMenu.Popup>
            </ContextMenu.Positioner>
          </ContextMenu.Portal>
        </ContextMenu.Root>
      </div>
      {editor && <MediaBlockEditor target={editor.target} duration={duration} bgmSpans={bgmSpans}
        saving={saving || editor.revision !== readout.revision} onClose={() => setEditor(null)} onSave={onEdit} />}
      {/* 视图矮时不显示这一行：未使用的视频单元同时列在详情栏的问题里 */}
      {unusedUnits.length > 0 && (
        <div className="edit-unused-units shrink-0 overflow-hidden edit-short:hidden" inert={shownRows === 0}>
          <div
            role="region"
            aria-label={translate("edit_view_unused")}
            // eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex -- 条目多时这一行横向滚动，里面没有可聚焦的元素，键盘要能聚焦后滚动
            tabIndex={0}
            className="focus-ring relative flex items-center gap-2 overflow-x-auto px-2 pb-2 border-t edit-short:hidden border-border/50 pt-2 text-xs whitespace-nowrap text-muted-foreground scroll-fade-x">
            <span className="shrink-0">{translate("edit_view_unused")}</span>
            {unusedUnits.map((unitId) => {
              const thumbnail = thumbnails.get(unitId);
              return (
                <span
                  key={unitId}
                  className="inline-flex shrink-0 items-center gap-1.5 rounded-sm border border-dashed border-border px-1.5 py-0.5"
                >
                  {thumbnail && <UnusedUnitThumbnail projectName={projectName} path={thumbnail} />}
                  <ItemPositionBadge position={positions.get(unitId) ?? null} kind={episodeItemKind(unitId)} />
                </span>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}

function MediaBlockEditor({ target, duration, bgmSpans, saving, onSave, onClose }: {
  target: MediaTarget;
  duration: number;
  bgmSpans: readonly (TimeBounds & { id: string })[];
  saving: boolean;
  onSave: (operation: TimelineClipOperation) => void;
  onClose: () => void;
}) {
  const { t } = useTranslation("dashboard");
  const { t: common } = useTranslation("common");
  const item = "audio" in target ? target.audio : null;
  const clip = "clip" in target ? target.clip : null;
  const [from, to] = clip ? sourceBounds(clip) : [item!.sourceIn, item!.sourceIn + item!.length];
  const seconds = (value: number) => String(Math.round(value * 1e6) / 1e6);
  const [start, setStart] = useState(seconds(item?.start ?? 0));
  const [sourceIn, setSourceIn] = useState(seconds(from));
  const [sourceOut, setSourceOut] = useState(seconds(to));
  const [at, lo, hi] = [start, sourceIn, sourceOut].map((input) => input === "" ? NaN : Number(input));
  const min = item ? Math.min(MIN_TRIM, item.length) : MIN_TRIM;
  const max = clip?.source_duration ?? to;
  const overlaps = item?.kind === "bgm" && bgmSpans.some((span) => span.id !== item.editId &&
    at + hi - lo > span.start + 1e-7 && at < span.end - 1e-7);
  const valid = !saving && !overlaps && lo >= (item ? from : 0) - 1e-7 && hi <= max + 1e-7 &&
    hi - lo >= min - 1e-7 && (!item || (at >= 0 && at < duration));
  const changed = start !== seconds(item?.start ?? 0) || sourceIn !== seconds(from) || sourceOut !== seconds(to);
  return (
    <Dialog open onOpenChange={(open) => { if (!open) onClose(); }}>
      <DialogContent size="sm" render={<form onSubmit={(event) => {
        event.preventDefault();
        if (!valid || !changed) return;
        if (item) onSave(audioWindowEdit(item, at, lo, hi));
        else if (clip?.video_version != null) onSave({ op: "set_trim", clip: clip.id,
          trim: { source_in: lo, source_out: hi, source_version: clip.video_version } });
        onClose();
      }} />}>
        <DialogHeader><DialogTitle>{common("edit")}</DialogTitle></DialogHeader>
        <DialogBody className="grid gap-3">
          {item && <label className="grid gap-1">{t("edit_view_block_start")}
            <Input type="number" min={0} max={Math.max(0, duration - 0.000001)} step="any" required value={start} onChange={(event) => setStart(event.target.value)} />
          </label>}
          <label className="grid gap-1">{t("edit_view_block_in")}
            <Input type="number" min={item ? seconds(from) : 0} max={seconds(max)} step="any" required value={sourceIn} onChange={(event) => setSourceIn(event.target.value)} />
          </label>
          <label className="grid gap-1">{t("edit_view_block_out")}
            <Input type="number" min={0} max={seconds(max)} step="any" required value={sourceOut} onChange={(event) => setSourceOut(event.target.value)} />
          </label>
          {changed && !valid && !saving && <p role="status" className="text-sm text-muted-foreground">{t("edit_view_block_invalid")}</p>}
        </DialogBody>
        <DialogFooter showCloseButton><Button type="submit" disabled={!valid || !changed}>{common("save")}</Button></DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/** 未使用单元的小缩略图；单独订阅这张图的指纹，指纹变化只重渲这一张。 */
function UnusedUnitThumbnail({ projectName, path }: { projectName: string; path: string }) {
  const fingerprint = useProjectsStore((s) => s.getAssetFingerprint(path));
  return (
    <img
      src={API.getFileUrl(projectName, path, fingerprint, { width: 160 })}
      alt=""
      loading="lazy"
      decoding="async"
      className="h-4 w-7 rounded-xs object-cover"
    />
  );
}

const RULER_STEPS = [1, 2, 5, 10, 15, 30, 60, 150, 300, 450, 900, 1800, 3600, 9000, 18000, 36000];

const Ruler = memo(function Ruler({ duration, scale, start, end }: {
  duration: number;
  scale: number;
  start: number;
  end: number;
}) {
  const pixelsPerFrame = scale / TIMELINE_FPS;
  const step = RULER_STEPS.find((frames) => frames * pixelsPerFrame >= 84)
    ?? 36000 * Math.ceil(84 / (36000 * pixelsPerFrame));
  const minor = step % 5 === 0 ? step / 5 : step % 2 === 0 ? step / 2 : step;
  const segmentLeft = Math.floor(start * TIMELINE_FPS / minor) * minor * pixelsPerFrame;
  const segmentWidth = Math.max(0, Math.min(duration, end) * scale - segmentLeft);
  const last = Math.floor(Math.min(end, duration) * TIMELINE_FPS / step) * step;
  const ticks = [];
  for (let frame = Math.floor(start * TIMELINE_FPS / step) * step; frame <= last; frame += step) {
    const time = Math.floor(frame / TIMELINE_FPS);
    const remainder = frame % TIMELINE_FPS;
    const seconds = String(time % 60).padStart(2, "0");
    const minutes = String(Math.floor(time / 60)).padStart(2, "0");
    ticks.push(
      <span key={frame} className="absolute top-1 whitespace-nowrap border-l border-muted-foreground/50 pl-1 leading-4"
        style={{ left: frame * pixelsPerFrame }}>
        {remainder === 0 ? `${minutes}:${seconds}` : `${remainder}f`}
      </span>,
    );
  }
  return (
    <div aria-hidden className="relative h-7 border-b border-border bg-sidebar/70 text-[10px] text-muted-foreground tabular-nums">
      <div className="absolute bottom-0 left-0 h-1 opacity-60" style={{
        left: segmentLeft,
        width: segmentWidth,
        backgroundImage: `repeating-linear-gradient(to right, currentColor 0 1px, transparent 1px ${minor * pixelsPerFrame}px)`,
      }} />
      {ticks}
    </div>
  );
});

function TrackLabel({ icon: Icon, label, height, children }: { icon: typeof Video; label: string; height: string; children?: ReactNode }) {
  return <div className={cn("flex items-center gap-1 border-b border-border/60 px-2 text-xs text-muted-foreground", height)}>
    <Icon aria-hidden className="size-3.5 shrink-0" />
    <span className="min-w-0 flex-1 truncate" title={label}>{label}</span>
    {children}
  </div>;
}

function TrackRow({ height, overlay, children }: { height: string; overlay?: CSSProperties; children: ReactNode }) {
  return <div data-folded-track={overlay ? "" : undefined} style={overlay}
    className={overlay ? "edit-folded-track" : cn("relative border-b border-border/60", height)}>{children}</div>;
}

const BGM_ACCEPT = ".mp3,.wav,.m4a,audio/mpeg,audio/wav,audio/mp4";

function AudioUploadButton({ projectName, kind, disabled, onInsert }: {
  projectName: string;
  kind: "bgm" | "sfx";
  disabled: boolean;
  onInsert: (kind: "bgm" | "sfx", asset: ProjectBgm) => boolean;
}) {
  const { t } = useTranslation("dashboard");
  const input = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);
  const insertRef = useRef<typeof onInsert | null>(null);
  useLayoutEffect(() => {
    insertRef.current = onInsert;
    return () => { insertRef.current = null; };
  }, [onInsert]);
  const upload = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    setUploading(true);
    const { pushToast } = useAppStore.getState();
    try {
      const { bgm } = await API.uploadBgm(projectName, file);
      if (insertRef.current && !insertRef.current(kind, bgm)) pushToast(t("edit_view_audio_no_room", { name: bgm.name }), "info");
    } catch (cause) {
      pushToast(t("edit_view_audio_upload_failed", { message: errMsg(cause) }), "error");
    } finally {
      setUploading(false);
    }
  };
  const label = uploading ? t("edit_view_audio_uploading") : t(kind === "sfx" ? "edit_view_sfx_upload" : "edit_view_bgm_upload");
  return (
    <>
      <Button
        variant="ghost"
        size="icon-xs"
        aria-label={label}
        title={label}
        disabled={disabled || uploading}
        data-testid={`edit-${kind}-upload`}
        onPointerDown={(event) => event.stopPropagation()}
        onClick={() => input.current?.click()}
      >
        {uploading ? <Loader2 aria-hidden className="animate-spin" /> : <Upload aria-hidden />}
      </Button>
      <input
        ref={input}
        type="file"
        accept={BGM_ACCEPT}
        hidden
        data-testid={`edit-${kind}-upload-input`}
        onChange={(event) => void upload(event)}
      />
    </>
  );
}

interface VideoClipsProps {
  clips: readonly EditClip[];
  lastLiveId?: string;
  duration: number;
  scale: number;
  start: number;
  end: number;
  decode: boolean;
  projectName: string;
  thumbnails: ReadonlyMap<string, string>;
  videoUrls: ReadonlyMap<string, string>;
  selectedClipId: string | null;
  activeClipId: string | null;
  trimIgnored: ReadonlySet<string>;
  positions: ReadonlyMap<string, number>;
  onSelectClip: (clipId: string) => void;
}

const VideoClips = memo(function VideoClips({
  clips, lastLiveId, duration, scale, start, end, decode, projectName, thumbnails, videoUrls,
  selectedClipId, activeClipId, trimIgnored, positions, onSelectClip,
}: VideoClipsProps) {
  const { t } = useTranslation("dashboard");
  const percent = (seconds: number) => percentOf(seconds, duration);
  return (
    <>
      {clips.map((clip) => clip.status !== "unit_deleted" && (
        <ClipBlock
          key={clip.id}
          clip={clip}
          projectName={projectName}
          poster={thumbnails.get(clip.unit_id)}
          videoUrl={videoUrls.get(clip.id)}
          scale={scale}
          start={Math.max(0, start - clip.start)}
          end={Math.min(clip.duration, end - clip.start)}
          decode={decode}
          left={percent(clip.start)}
          width={percent(clip.duration)}
          selected={selectedClipId === clip.id}
          active={activeClipId === clip.id}
          trimIgnored={trimIgnored.has(clip.id)}
          position={positions.get(clip.unit_id) ?? null}
          onSelect={onSelectClip}
        />
      ))}
      {clips.map((clip) => clip.status !== "unit_deleted" && clip.id !== lastLiveId && clip.transition_to_next && (
        <span
          key={`transition-${clip.id}`}
          aria-hidden
          title={t("edit_view_transition_marker", {
            type: t(`edit_transition_${clip.transition_to_next.type}`, { defaultValue: clip.transition_to_next.type }),
            duration: formatSeconds(clip.transition_to_next.duration),
          })}
          className="pointer-events-none absolute top-1/2 left-[calc(var(--at)-var(--span)/2)] h-5 w-(--span) -translate-y-1/2 rounded-xs bg-primary/35 ring-1 ring-primary"
          style={{ "--at": percent(clip.start + clip.duration), "--span": percent(clip.transition_to_next.duration) } as CSSProperties}
        />
      ))}
      {clips.map((clip) => clip.status === "unit_deleted" && (
        <button
          key={clip.id}
          type="button"
          onClick={() => onSelectClip(clip.id)}
          title={t("edit_view_clip_deleted_marker", { clip: clip.id })}
          aria-label={t("edit_view_clip_deleted_marker", { clip: clip.id })}
          aria-pressed={selectedClipId === clip.id}
          data-clip-id={clip.id}
          data-testid={`edit-clip-deleted-${clip.id}`}
          className="focus-ring absolute inset-y-0 left-(--at) flex w-6 -translate-x-1/2 flex-col items-center"
          style={{ "--at": percent(clip.start) } as CSSProperties}
        >
          <span className="h-full w-0.5 bg-destructive" />
          <span className="absolute -bottom-1 rounded-xs bg-destructive px-1 text-xs leading-3.5 text-black">{clip.id}</span>
        </button>
      ))}
    </>
  );
});

interface ClipBlockProps {
  clip: EditClip;
  projectName: string;
  poster?: string;
  videoUrl?: string;
  scale: number;
  start: number;
  end: number;
  decode: boolean;
  left: string;
  width: string;
  selected: boolean;
  active: boolean;
  trimIgnored: boolean;
  position: number | null;
  onSelect: (clipId: string) => void;
}

const ClipBlock = memo(function ClipBlock({
  clip, projectName, poster, videoUrl, scale, start, end, decode, left, width, selected, active, trimIgnored, position, onSelect,
}: ClipBlockProps) {
  const { t } = useTranslation("dashboard");
  const missingVideo = clip.status !== "ready";
  const unit = itemPositionLabel(episodeItemKind(clip.unit_id), position, t);
  return (
    <button
      type="button"
      onClick={() => onSelect(clip.id)}
      aria-pressed={selected}
      title={t("edit_view_clip_title", { clip: clip.id, unit, duration: formatSeconds(clip.duration) })}
      data-clip-id={clip.id}
      data-testid={`edit-clip-${clip.id}`}
      data-trim-ignored={trimIgnored || undefined}
      className={cn(
        "focus-ring absolute inset-y-1 left-(--at) w-[max(1px,calc(var(--span)-1px))] cursor-grab overflow-hidden rounded-sm border text-left",
        trimIgnored ? "border-dashed border-warn" : missingVideo ? "border-dashed border-input" : "border-cyan-800/80",
        missingVideo ? "bg-muted" : "bg-cyan-950",
        selected ? "z-[1] ring-1 ring-white" : active && "ring-1 ring-cyan-400/70",
      )}
      style={{ "--at": left, "--span": width } as CSSProperties}
    >
      {!missingVideo && (videoUrl || poster) && clip.duration * scale >= 12 && (
        <VideoFilmstrip clip={clip} projectName={projectName} poster={poster} url={videoUrl} scale={scale} start={start} end={end} decode={decode} />
      )}
      <span className={cn(
        "absolute inset-x-0 top-0 flex h-4 items-center gap-1 overflow-hidden px-1 text-[10px] leading-none whitespace-nowrap text-white",
        missingVideo ? "bg-muted" : "bg-cyan-950/90",
      )}>
        <b>{clip.id}</b>
        <span className="sr-only">{unit}</span>
        <span className="num" aria-hidden>{position ?? t("common:deleted")}</span>
        {trimIgnored && <AlertTriangle aria-hidden className="size-3 shrink-0 text-warn" />}
      </span>
      {selected && clip.video_version != null && clip.source_duration != null && clip.duration - clip.hold >= MIN_TRIM && clip.duration * scale >= 24 && (
        <>
          <span aria-hidden data-trim-edge="in" className="absolute inset-y-0 left-0 w-2 cursor-ew-resize bg-white/20 hover:bg-white/50" />
          <span aria-hidden data-trim-edge="out" className="absolute inset-y-0 right-0 w-2 cursor-ew-resize bg-white/20 hover:bg-white/50" />
        </>
      )}
    </button>
  );
});

const VideoFilmstrip = memo(function VideoFilmstrip({ clip, projectName, poster, url, scale, start, end, decode }: {
  clip: EditClip;
  projectName: string;
  poster?: string;
  url?: string;
  scale: number;
  start: number;
  end: number;
  decode: boolean;
}) {
  const fingerprint = useProjectsStore((s) => poster ? s.getAssetFingerprint(poster) : null);
  const fallback = poster ? API.getFileUrl(projectName, poster, fingerprint, { width: 160 }) : undefined;
  const sourceIn = trimApplies(clip) && clip.trim ? clip.trim.source_in : 0;
  const pictureLength = Math.max(0, clip.duration - clip.hold);
  const tileWidth = 64;
  const tiles = [];
  for (let i = Math.floor(start * scale / tileWidth); i * tileWidth < end * scale; i++) {
    const x = i * tileWidth;
    const offset = Math.min((x + tileWidth / 2) / scale, Math.max(0, pictureLength - 1 / TIMELINE_FPS));
    const time = sourceIn + Math.floor(offset * TIMELINE_FPS) / TIMELINE_FPS;
    tiles.push(<FilmstripTile key={i} url={url} time={time} fallback={fallback} decode={decode} left={x} width={tileWidth} />);
  }
  return <span aria-hidden className="pointer-events-none absolute inset-x-0 top-4 bottom-0.5 overflow-hidden bg-cyan-950">{tiles}</span>;
});

const FilmstripTile = memo(function FilmstripTile({ url, time, fallback, decode, left, width }: {
  url?: string;
  time: number;
  fallback?: string;
  decode: boolean;
  left: number;
  width: number;
}) {
  const [image, setImage] = useState<{ url: string; time: number; src: string } | null>(null);
  const decoded = image && image.url === url && image.time === time ? image.src : undefined;
  const src = decoded ?? fallback;
  useEffect(() => {
    if (!url || !decode || decoded) return;
    const controller = new AbortController();
    void timelineThumbnail(url, time, controller.signal).then((result) => {
      if (!controller.signal.aborted && result) setImage({ url, time, src: result });
    });
    return () => controller.abort();
  }, [decode, decoded, time, url]);
  return src ? (
    <img alt="" draggable={false} decoding="async" src={src} className="absolute h-full object-cover" style={{ left, width }} />
  ) : null;
});

/**
 * 旁白按实际起止画在轨上，可以越过承载片段；重叠的旁白分两行。TTS 项目没有旁白配音的按承载片段占位，画成虚线；
 * 后期配音项目的旁白画成中性占位，提示由后期配音、预览不出声。
 */
const SubtitleBlocks = memo(function SubtitleBlocks({ subtitles, duration, scale, selectedId, onSelect, onFocus }: {
  subtitles: readonly PlacedSubtitle[];
  duration: number;
  scale: number;
  selectedId: string | null;
  onSelect: (id: string) => void;
  onFocus: (item: PlacedSubtitle) => void;
}) {
  return subtitles.map((item) => {
    const selected = selectedId === item.id;
    return (
      <button
        key={item.id}
        type="button"
        data-subtitle-id={item.id}
        aria-pressed={selected}
        title={item.text}
        onClick={() => onSelect(item.id)}
        onDoubleClick={() => onFocus(item)}
        className={cn("focus-ring absolute inset-y-1 left-(--at) w-[max(1px,calc(var(--span)-1px))] cursor-grab overflow-hidden rounded-sm border border-orange-400/50 bg-orange-900/80 px-1 text-left text-xs leading-none text-orange-50", selected && "z-[1] ring-1 ring-white")}
        style={{ "--at": percentOf(item.start, duration), "--span": percentOf(item.end - item.start, duration) } as CSSProperties}
      >
        <span className="block truncate">{item.text}</span>
        {selected && (item.end - item.start) * scale >= 12 && (
          <>
            <span aria-hidden data-trim-edge="in" className="absolute inset-y-0 left-0 w-1 cursor-ew-resize bg-white/35 hover:bg-white/75" />
            <span aria-hidden data-trim-edge="out" className="absolute inset-y-0 right-0 w-1 cursor-ew-resize bg-white/35 hover:bg-white/75" />
          </>
        )}
      </button>
    );
  });
});

const AUDIO_COLORS = {
  narration: "border-violet-500/70 bg-violet-900 text-violet-50",
  dialogue: "border-cyan-500/70 bg-cyan-900 text-cyan-50",
  source: "border-slate-500/70 bg-slate-800 text-slate-50",
  sfx: "border-amber-500/70 bg-amber-900 text-amber-50",
  bgm: "border-emerald-500/70 bg-emerald-900 text-emerald-50",
} as const;

const AudioBlocks = memo(function AudioBlocks({ items, duration, scale, selectedId, positions, onSelect, start, end, waveforms, muted }: {
  items: readonly AudioPlacement[];
  duration: number;
  scale: number;
  selectedId?: string;
  start: number;
  end: number;
  waveforms: ReadonlyMap<string, Waveform>;
  muted: boolean;
  positions: ReadonlyMap<string, number>;
  onSelect: (id: string) => void;
}) {
  const { t } = useTranslation("dashboard");
  return items.map((item) => {
    const selected = item.id === selectedId;
    const length = item.end - item.start;
    const position = item.unitId ? positions.get(item.unitId) : undefined;
    const label = item.name ?? (position === undefined ? t(AUDIO_LABELS[item.kind]) : `${t(AUDIO_LABELS[item.kind])} ${position}`);
    return (
      <button key={item.id} type="button" data-audio-id={item.id} aria-pressed={selected}
        data-testid={`edit-${item.id}`} title={`${label} · ${formatSeconds(item.start)} – ${formatSeconds(item.end)}`}
        onClick={() => onSelect(item.id)}
        className={cn("focus-ring absolute top-1 left-(--at) h-[calc(100%-0.5rem)] w-[max(1px,calc(var(--span)-1px))] cursor-grab overflow-hidden rounded-sm border px-1 text-left text-xs leading-none", AUDIO_COLORS[item.kind], muted && "opacity-45", selected && "z-[1] ring-1 ring-white")}
        style={{ "--at": percentOf(item.start, duration), "--span": percentOf(length, duration) } as CSSProperties}>
        {(item.fadeIn > 0 || item.fadeOut > 0) && (
          <span aria-hidden className="pointer-events-none absolute inset-0" style={{
            background: `linear-gradient(to right, rgb(0 0 0 / 45%) 0%, transparent ${100 * item.fadeIn / length}%, transparent ${100 * (1 - item.fadeOut / length)}%, rgb(0 0 0 / 45%) 100%)`,
          }} />
        )}
        <WaveformBars item={item} waveform={waveforms.get(item.id)} scale={scale} start={start} end={end} />
        <span className="absolute inset-x-1 top-0.5 truncate">{label}</span>
        {selected && length * scale >= 12 && (
          <>
            <span aria-hidden data-trim-edge="in" className="absolute inset-y-0 left-0 w-1 cursor-ew-resize bg-white/35 hover:bg-white/75" />
            <span aria-hidden data-trim-edge="out" className="absolute inset-y-0 right-0 w-1 cursor-ew-resize bg-white/35 hover:bg-white/75" />
          </>
        )}
      </button>
    );
  });
});


const WaveformBars = memo(function WaveformBars({ item, waveform, scale, start, end }: {
  item: AudioPlacement;
  waveform?: Waveform;
  scale: number;
  start: number;
  end: number;
}) {
  if (!waveform) return null;
  const stride = 3;
  const left = Math.max(0, Math.floor((start - item.start) * scale / stride) * stride);
  const right = Math.ceil((Math.min(item.end, end) - item.start) * scale);
  if (right <= left) return null;
  const { bars, rate } = waveform;
  const origin = item.sourceIn * rate;
  const perPixel = rate / scale;
  const hot: string[] = [];
  const normal: string[] = [];
  for (let x = left; x < right; x += stride) {
    const first = Math.max(0, Math.floor(origin + x * perPixel));
    const last = Math.min(bars.length, Math.ceil(origin + Math.min(right, x + stride) * perPixel));
    let peak = 0;
    for (let i = first; i < last; i++) peak = Math.max(peak, bars[i]);
    if (!peak) continue;
    const height = Math.max(1, Math.round(peak / 255 * 16));
    (peak > 244 ? hot : normal).push(`M${x - left + 0.5} 16v-${height}`);
  }
  return <span aria-hidden data-waveform className="pointer-events-none absolute top-3 bottom-px text-cyan-300/80"
    style={{ left, width: right - left }}>
    <svg className="block size-full" viewBox={`0 0 ${right - left} 16`} preserveAspectRatio="none">
      <path d={normal.join("")} fill="none" stroke="currentColor" />
      <path d={hot.join("")} fill="none" stroke="var(--color-orange-400)" />
    </svg>
  </span>;
});
