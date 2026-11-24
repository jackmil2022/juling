/** One decoder for timeline thumbnails, independent of the playback slots. */
const CACHE_LIMIT = 256;
const WIDTH = 144;
const HEIGHT = 80;
const cache = new Map<string, string | null>();
const queue: {
  url: string;
  time: number;
  signal: AbortSignal;
  resolve: (image: string | null) => void;
}[] = [];
let running = false;

function waitForMedia(video: HTMLVideoElement, event: string, signal: AbortSignal): Promise<boolean> {
  return new Promise((resolve) => {
    const finish = (e?: Event) => {
      window.clearTimeout(timeout);
      video.removeEventListener(event, finish);
      video.removeEventListener("error", finish);
      signal.removeEventListener("abort", finish);
      resolve(e?.type === event);
    };
    const timeout = window.setTimeout(finish, 1800);
    video.addEventListener(event, finish);
    video.addEventListener("error", finish);
    signal.addEventListener("abort", finish);
    if (signal.aborted || video.error) finish();
  });
}

async function capture(video: HTMLVideoElement, context: CanvasRenderingContext2D, url: string, time: number, signal: AbortSignal) {
  if (video.getAttribute("src") !== url) video.src = url;
  if (video.readyState < 1 && !await waitForMedia(video, "loadedmetadata", signal)) return null;
  if (signal.aborted || !video.videoWidth || !Number.isFinite(video.duration)) return null;
  const target = Math.min(time, Math.max(0, video.duration - 0.001));
  if (video.seeking || Math.abs(video.currentTime - target) > 0.001) {
    video.currentTime = target;
    if (video.seeking && !await waitForMedia(video, "seeked", signal)) return null;
  }
  if (video.readyState < 2 && !await waitForMedia(video, "loadeddata", signal)) return null;
  if (signal.aborted) return null;
  const scale = Math.max(WIDTH / video.videoWidth, HEIGHT / video.videoHeight);
  const width = video.videoWidth * scale;
  const height = video.videoHeight * scale;
  context.drawImage(video, (WIDTH - width) / 2, (HEIGHT - height) / 2, width, height);
  return context.canvas.toDataURL("image/jpeg", 0.7);
}

async function drain() {
  running = true;
  const video = document.createElement("video");
  video.muted = true;
  video.preload = "auto";
  const canvas = document.createElement("canvas");
  canvas.width = WIDTH;
  canvas.height = HEIGHT;
  const context = canvas.getContext("2d");
  try {
    for (let job = queue.shift(); job; job = queue.shift()) {
      const { url, time, signal, resolve } = job;
      const key = JSON.stringify([url, time]);
      let image = cache.get(key);
      if (context && !signal.aborted) {
        if (image === undefined) {
          try { image = await capture(video, context, url, time, signal); }
          catch { image = null; }
        }
        if (!signal.aborted) {
          cache.delete(key);
          cache.set(key, image);
          if (cache.size > CACHE_LIMIT) cache.delete(cache.keys().next().value!);
        }
      }
      resolve(signal.aborted ? null : image ?? null);
    }
  } finally {
    video.removeAttribute("src");
    video.load();
    running = false;
  }
}

export function timelineThumbnail(url: string, time: number, signal: AbortSignal): Promise<string | null> {
  return new Promise((resolve) => {
    queue.push({ url, time, signal, resolve });
    if (!running) void drain();
  });
}
