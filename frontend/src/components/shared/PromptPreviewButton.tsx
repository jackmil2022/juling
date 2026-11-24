import { Fragment, useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Bot, Check, Copy, Eye, Mic, RefreshCw, RotateCcw } from "lucide-react";
import { cn } from "cn";
import { API } from "@/api";
import { useAppStore } from "@/stores/app-store";
import { useTasksStore } from "@/stores/tasks-store";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { errMsg } from "@/utils/async";
import { copyText } from "@/utils/clipboard";
import type { RenderedPromptPreview } from "@/types";

import { PromptReferenceMedia } from "./PromptReferenceMedia";

const PROMPT_MENTION_RE = /(@\[[^\]\r\n]+\])/g;
type PromptPreviewResult = RenderedPromptPreview & { submitted?: RenderedPromptPreview | null };

function PromptPreviewText({ text }: { text: string }) {
  return (
    <>
      {text.split(PROMPT_MENTION_RE).map((part, index) =>
        part.startsWith("@[") && part.endsWith("]") ? (
          <span key={`prompt-mention-${index}`} className="rounded-sm bg-asset-character/15 px-0.5 text-asset-character">
            {part}
          </span>
        ) : (
          <Fragment key={`prompt-text-${index}`}>{part}</Fragment>
        ),
      )}
    </>
  );
}

export interface PromptPreviewButtonProps<T extends PromptPreviewResult> {
  /** 弹窗标题，同时作为触发按钮的悬停说明，区分同一页面上的多个入口。 */
  title: string;
  projectName?: string;
  /** 取最终提示词：每次打开与刷新各调一次，调用时读到的是调用方最新的闭包（如当前草稿）。 */
  load: (signal: AbortSignal) => Promise<T>;
  /** 标题下的口径说明，如「按已保存内容渲染」或「按当前模型能力计算」。 */
  notice?: ReactNode;
  disabled?: boolean;
  /** 有未保存修改时先保存；失败则保留原处，不打开预览。回调需用 useCallback。 */
  beforeOpen?: () => Promise<boolean>;
  saveFirst?: boolean;
  savePrompt?: (text: string) => Promise<void>;
  onAgentGenerate?: () => void;
  removeReference?: (id: string) => Promise<void>;
  restoreReferences?: () => Promise<void>;
  canGenerateNarratorReference?: boolean;
}

/**
 * 「查看提示词」按钮与最终提示词弹窗：打开才请求，弹窗内可复制与重新渲染。
 *
 * 渲染在后端完成（与执行期同一出口），前端不复刻任何拼接逻辑；可选保存提示词，不触发生成。
 */
export function PromptPreviewButton<T extends PromptPreviewResult>({
  title,
  projectName,
  load,
  notice,
  disabled,
  beforeOpen,
  saveFirst,
  savePrompt,
  onAgentGenerate,
  removeReference,
  restoreReferences,
  canGenerateNarratorReference,
}: PromptPreviewButtonProps<T>) {
  const { t } = useTranslation("dashboard");
  const [preparing, setPreparing] = useState(false);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [preview, setResult] = useState<T | null>(null);
  const [showCurrent, setShowCurrent] = useState(false);
  const submitted = !showCurrent ? preview?.submitted : null;
  const result = submitted ?? preview;
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);
  const narratorReferencePending = useTasksStore((s) => !!canGenerateNarratorReference && s.tasks.some((task) =>
    task.project_name === projectName && task.task_type === "voice_sample" && task.resource_id === "旁白"
    && (task.status === "queued" || task.status === "running"),
  ));

  // 接管方轮换 controller：新一轮加载先作废上一轮，被作废方不再回写共享状态。
  const inflight = useRef<AbortController | null>(null);
  const narratorWasPending = useRef(narratorReferencePending);
  const fetchPreview = useCallback(async (prepared?: AbortController) => {
    if (!prepared) inflight.current?.abort();
    const controller = prepared ?? new AbortController();
    inflight.current = controller;
    const { signal } = controller;
    setLoading(true);
    setError(null);
    try {
      const next = await load(signal);
      if (signal.aborted || inflight.current !== controller) return;
      setResult(next);
      setDraft(next.text ?? "");
    } catch (e) {
      if (signal.aborted || inflight.current !== controller) return;
      setError(errMsg(e));
    } finally {
      // react-doctor-disable-next-line react-doctor/no-loading-flag-reset-outside-finally -- 已在 finally 中复位；只有仍持有 inflight 的请求才复位，被接管的请求交给接管方收尾
      if (!signal.aborted && inflight.current === controller) setLoading(false);
    }
  }, [load]);

  // 卸载时作废在途请求：清理函数不写 state，只切断被接管方的回写。
  useEffect(() => () => inflight.current?.abort(), []);

  useEffect(() => {
    const finished = narratorWasPending.current && !narratorReferencePending;
    narratorWasPending.current = narratorReferencePending;
    if (finished && open && !saving && !loading) void fetchPreview();
  }, [narratorReferencePending, open, saving, loading, fetchPreview]);

  useEffect(() => {
    if (!copied) return;
    const timer = setTimeout(() => setCopied(false), 1500);
    return () => clearTimeout(timer);
  }, [copied]);

  const handleOpen = async () => {
    if (preparing) return;
    inflight.current?.abort();
    const controller = new AbortController();
    inflight.current = controller;
    setPreparing(true);
    try {
      if (beforeOpen && !(await beforeOpen())) return;
      if (controller.signal.aborted || inflight.current !== controller) return;
      setOpen(true);
      await fetchPreview(controller);
    } finally {
      if (!controller.signal.aborted && inflight.current === controller) setPreparing(false);
    }
  };

  // 每次打开都重新取：关闭时丢弃结果，免得下次打开先闪出过期的文本。
  const handleClose = (): boolean => {
    if (saving) return false;
    if (savePrompt && result?.text && draft !== result.text && !window.confirm(t("prompt_preview_discard"))) return false;
    inflight.current?.abort();
    inflight.current = null;
    setOpen(false);
    setLoading(false);
    setPreparing(false);
    setResult(null);
    setShowCurrent(false);
    setError(null);
    setCopied(false);
    return true;
  };

  const handleSave = async (reset: boolean) => {
    if (!savePrompt || saving) return;
    setSaving(true);
    setError(null);
    try {
      await savePrompt(reset ? "" : draft);
      if (reset) {
        setResult(null);
        setDraft("");
        await fetchPreview();
      } else {
        setResult((current) => current ? { ...current, text: draft } : current);
      }
    } catch (e) {
      setError(errMsg(e));
    } finally {
      setSaving(false);
    }
  };

  const updatePreview = async (action: () => Promise<void>) => {
    if (saving || loading) return;
    setSaving(true);
    setError(null);
    try {
      await action();
      await fetchPreview();
    } catch (e) {
      setError(errMsg(e));
    } finally {
      setSaving(false);
    }
  };

  // 复制成功才显示「已复制」：非安全上下文走 execCommand 兜底，兜底也失败时不假报成功
  const handleCopy = (text: string) => {
    void copyText(text).then(
      () => setCopied(true),
      () => undefined,
    );
  };

  const handToAgent = () => {
    if (onAgentGenerate && handleClose()) onAgentGenerate();
  };

  return (
    <>
      <Button variant="ghost" size="xs" onClick={() => void handleOpen()} disabled={disabled || preparing} title={title}>
        <Eye aria-hidden data-icon="inline-start" />
        {t(saveFirst ? "prompt_preview_save_first" : "prompt_preview_open")}
      </Button>
      <Dialog
        open={open}
        onOpenChange={(next) => {
          if (!next) handleClose();
        }}
      >
        <DialogContent size="lg">
          <DialogHeader>
            <DialogTitle>{title}</DialogTitle>
            {notice ? <DialogDescription>{notice}</DialogDescription> : null}
          </DialogHeader>
          <DialogBody>
            <div className="flex flex-col gap-3">
              {preview?.submitted ? (
                <ToggleGroup aria-label={title} className="self-start" variant="outline" size="sm" spacing={0}
                             value={[showCurrent ? "current" : "submitted"]}
                             onValueChange={([view]: string[]) => {
                               if (!view) return;
                               setShowCurrent(view === "current");
                               setCopied(false);
                             }}>
                  <ToggleGroupItem value="submitted">{t("prompt_preview_submitted")}</ToggleGroupItem>
                  <ToggleGroupItem value="current">{t("prompt_preview_current")}</ToggleGroupItem>
                </ToggleGroup>
              ) : null}
              {loading && !result ? (
                <p className="text-sm text-muted-foreground">{t("prompt_preview_loading")}</p>
              ) : null}
              {error ? <p className="text-sm text-destructive">{error}</p> : null}
              {result?.unavailable ? <p className="text-sm text-muted-foreground">{result.unavailable}</p> : null}
              {result?.warnings?.length ? (
                <ul
                  aria-label={t("prompt_preview_warnings_label")}
                  className="flex flex-col gap-1 rounded-md border border-warn/30 bg-warn/10 px-3 py-2 text-xs text-warn"
                >
                  {result.warnings.map((warning, index) => (
                    // react-doctor-disable-next-line react-doctor/no-array-index-as-key -- 一次预览结果里的只读提示文本，可能重复且无标识；条目不带状态，整份随预览结果替换
                    <li key={`prompt-preview-warning-${index}`}>{warning}</li>
                  ))}
                </ul>
              ) : null}
              {result?.text && savePrompt ? (
                <>
                  <p className="text-xs text-muted-foreground">{t("prompt_preview_edit_hint")}</p>
                  <Textarea aria-label={t("prompt_preview_edit_label")} mono rows={12} value={draft} onChange={(event) => setDraft(event.target.value)} disabled={saving || loading} />
                </>
              ) : result?.text ? (
                <pre className="rounded-md border bg-card p-3 font-mono text-xs leading-relaxed whitespace-pre-wrap text-subtle-foreground wrap-break-word">
                  <PromptPreviewText text={result.text} />
                </pre>
              ) : null}
              {result?.narrator_reference_missing && canGenerateNarratorReference && projectName ? (
                <Button variant="outline" size="sm" className="self-start" disabled={saving || loading || narratorReferencePending}
                        onClick={() => void updatePreview(async () => {
                          const { message } = await API.generateNarratorVoiceSample(projectName);
                          if (message) useAppStore.getState().pushToast(message, "success");
                          await useTasksStore.getState().refreshTasks();
                        })}>
                  <Mic aria-hidden data-icon="inline-start" />
                  {t(narratorReferencePending ? "prompt_narrator_reference_pending" : "prompt_narrator_reference_generate")}
                </Button>
              ) : null}
              {projectName && result?.references?.length ? (
                <PromptReferenceMedia projectName={projectName} references={result.references} disabled={saving || loading}
                  onRemove={!submitted && removeReference ? (id) => void updatePreview(() => removeReference(id)) : undefined} />
              ) : null}
              {!submitted && restoreReferences ? (
                <Button variant="ghost" size="xs" className="self-start" disabled={saving || loading}
                        onClick={() => void updatePreview(restoreReferences)}>
                  <RotateCcw aria-hidden data-icon="inline-start" />
                  {t("prompt_reference_restore_images")}
                </Button>
              ) : null}
            </div>
          </DialogBody>
          <DialogFooter>
            {savePrompt && !result && !loading ? (
              <Button variant="outline" onClick={() => void fetchPreview()} disabled={saving}>
                {t("prompt_preview_refresh")}
              </Button>
            ) : savePrompt ? (
              <>
                <Button variant="outline" onClick={() => void handleSave(true)} disabled={loading || saving || !result?.text}>
                  {t("prompt_preview_restore")}
                </Button>
                <Button onClick={() => void handleSave(false)} disabled={loading || saving || !draft.trim() || draft === result?.text}>
                  {t("prompt_preview_save")}
                </Button>
              </>
            ) : (
              <Button variant="outline" onClick={() => void fetchPreview()} disabled={loading || saving}>
                <RefreshCw aria-hidden data-icon="inline-start" className={cn(loading && "animate-spin")} />
                {t("prompt_preview_refresh")}
              </Button>
            )}
            {onAgentGenerate ? (
              <Button
                variant="outline"
                onClick={handToAgent}
                disabled={saving}
              >
                <Bot aria-hidden data-icon="inline-start" />
                {t("prompt_preview_agent_generate")}
              </Button>
            ) : null}
            {result?.text ? (
              <Button variant={savePrompt ? "outline" : "default"} onClick={() => handleCopy(savePrompt ? draft : result.text ?? "")}>
                {copied ? <Check aria-hidden data-icon="inline-start" /> : <Copy aria-hidden data-icon="inline-start" />}
                {copied ? t("message_copied") : t("prompt_preview_copy")}
              </Button>
            ) : null}
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
