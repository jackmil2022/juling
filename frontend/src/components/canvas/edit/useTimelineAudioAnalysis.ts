import { useEffect, useState } from "react";
import { API } from "@/api";
import type { TimelineAudioAnalysis } from "@/types/edit-timeline";

export interface Waveform {
  bars: Uint8Array;
  rate: number;
}

export interface AudioAsset {
  path: string;
  version: number | null;
}

type AnalysedAudio = {
  key: string;
  waveform: Waveform;
  stems: { kind: "dialogue" | "sfx"; waveform: Waveform }[];
};

const cache = new Map<string, AnalysedAudio>();

export function audioAssetKey(project: string, asset: AudioAsset): string {
  return JSON.stringify([project, asset.path, asset.version]);
}

function decode({ key, peaks, peaks_per_second: rate, stems }: TimelineAudioAnalysis): AnalysedAudio {
  const waveform = (values: string): Waveform => {
    const bytes = atob(values);
    const bars = new Uint8Array(bytes.length);
    for (let i = 0; i < bytes.length; i++) bars[i] = bytes.charCodeAt(i);
    return { bars, rate };
  };
  return { key, waveform: waveform(peaks), stems: stems.map((stem) => ({ kind: stem.kind, waveform: waveform(stem.peaks) })) };
}

export function useTimelineAudioAnalysis(project: string, requestJson: string) {
  const [results, setResults] = useState<ReadonlyMap<string, AnalysedAudio | null>>(() => new Map());
  useEffect(() => {
    const controller = new AbortController();
    const assets = JSON.parse(requestJson) as AudioAsset[];
    let next = 0;
    let frame = 0;
    const completed = new Map<string, AnalysedAudio | null>();
    const update = (key: string, result: AnalysedAudio | null) => {
      if (controller.signal.aborted) return;
      completed.set(key, result);
      if (!frame) frame = requestAnimationFrame(() => {
        frame = 0;
        const batch = new Map(completed);
        completed.clear();
        setResults((previous) => {
          const active = new Map([...previous, ...batch]);
          for (const key of active.keys()) {
            if (!keys.has(key)) active.delete(key);
          }
          return active;
        });
      });
    };
    const keys = new Set(assets.map((asset) => audioAssetKey(project, asset)));
    const worker = async () => {
      while (!controller.signal.aborted && next < assets.length) {
        const asset = assets[next++];
        const key = audioAssetKey(project, asset);
        const cached = cache.get(key);
        if (cached) {
          update(key, cached);
          continue;
        }
        try {
          const result = decode(await API.getTimelineAudioAnalysis(project, asset.path, controller.signal));
          cache.set(key, result);
          if (cache.size > 128) cache.delete(cache.keys().next().value!);
          update(key, result);
        } catch {
          update(key, null);
        }
      }
    };
    for (let i = 0; i < Math.min(4, assets.length); i++) void worker();
    return () => {
      controller.abort();
      cancelAnimationFrame(frame);
    };
  }, [project, requestJson]);
  return results;
}
