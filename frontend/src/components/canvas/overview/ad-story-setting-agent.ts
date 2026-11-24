import { API } from "@/api";
import { useAppStore } from "@/stores/app-store";
import { useAssistantStore } from "@/stores/assistant-store";
import type { ProjectOverview, TimelineEntry } from "@/types";
import type { SseStreamHandle } from "@/utils/sse-stream";

export type SettingFields = Pick<ProjectOverview, "synopsis" | "genre" | "theme" | "world_setting">;

function draftFrom(input: Record<string, unknown> | undefined): SettingFields | null {
  const { synopsis, genre, theme, world_setting } = input ?? {};
  if (typeof synopsis !== "string" || !synopsis.trim() || typeof genre !== "string" || !genre.trim() ||
      typeof theme !== "string" || !theme.trim() || typeof world_setting !== "string" || !world_setting.trim()) {
    return null;
  }
  return { synopsis: synopsis.trim(), genre: genre.trim(), theme: theme.trim(), world_setting: world_setting.trim() };
}

export async function generateAdStorySetting(
  projectName: string,
  formSignal: AbortSignal,
  noResult: string,
): Promise<SettingFields> {
  const signal = AbortSignal.any([formSignal, AbortSignal.timeout(5 * 60_000)]);
  const { prompt } = await API.getAdStorySettingPrompt(projectName, signal);
  signal.throwIfAborted();

  return new Promise((resolve, reject) => {
    let stream: SseStreamHandle | undefined;
    const drafts = new Map<string, SettingFields>();
    const stop = () => {
      stream?.close();
      signal.removeEventListener("abort", abort);
      const state = useAssistantStore.getState();
      if (state.agentMessageRequest?.signal === signal) state.clearAgentMessageRequest(state.agentMessageRequest);
    };
    const fail = (error: unknown) => {
      stop();
      reject(error);
    };
    const abort = () => fail(formSignal.aborted ? formSignal.reason : new Error(noResult));
    signal.addEventListener("abort", abort, { once: true });

    useAssistantStore.getState().requestAgentMessage(projectName, prompt, {
      newSession: true,
      signal,
      onSent(sessionId) {
        if (signal.aborted) return;
        if (!sessionId) {
          fail(new Error(useAssistantStore.getState().error || noResult));
          return;
        }
        // 授权只随本次新会话；切换右侧聊天也不影响当前表单接收结果。
        stream = API.openAssistantEntriesStream({
          projectName,
          sessionId,
          onEvent(event, payload) {
            if (event === "status" && ["completed", "error", "interrupted"].includes(String(payload.status))) {
              fail(new Error(noResult));
              return;
            }
            if (event !== "entry") return;
            const entry = payload as unknown as TimelineEntry;
            if (entry.parent_tool_use_id) return;
            if (entry.type === "assistant" && Array.isArray(entry.content)) {
              for (const block of entry.content) {
                if (block.type !== "tool_use" || block.name !== "mcp__juling__submit_ad_story_setting" || !block.id) continue;
                const draft = draftFrom(block.input);
                if (draft) drafts.set(block.id, draft);
              }
            } else if (entry.type === "tool_result" && entry.tool_use_id) {
              const draft = drafts.get(entry.tool_use_id);
              drafts.delete(entry.tool_use_id);
              if (draft && entry.is_error === false) {
                stop();
                resolve(draft);
              }
            }
          },
          onError(error) {
            if (!error.retryable) fail(error);
          },
        });
      },
    });
    useAppStore.getState().setAssistantPanelOpen(true);
  });
}
