import { useEffect, useId, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "wouter";
import { cn } from "cn";
import { Bot, CheckCircle2, Loader2, RotateCcw, X } from "lucide-react";
import { API } from "@/api";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { isAdScriptTask, useAdScriptEntry } from "@/hooks/useAdScriptEntry";
import { useEpisodeLedger } from "@/hooks/useEpisodeLedger";
import { useAdScriptStore, type AdScriptOpenRequest } from "@/stores/ad-script-store";
import { useAppStore } from "@/stores/app-store";
import { useAssistantStore } from "@/stores/assistant-store";
import { useProjectsStore } from "@/stores/projects-store";
import type { AdScriptTaskResult, ScriptOverwrite } from "@/types";
import { errMsg } from "@/utils/async";
import { episodeAgentRef, itemIdsAsPositionsInText } from "@/utils/episode-display";
import { formatNameList } from "@/utils/list-format";

/** 集页上唯一的广告/短片「AI 生成脚本」弹窗宿主：按 {@link useAdScriptStore} 的请求打开。 */
export function AdScriptHost({ projectName, episode }: { projectName: string; episode: number }) {
  const request = useAdScriptStore((s) => s.request);
  const close = useAdScriptStore((s) => s.close);
  useEffect(() => close, [close, projectName, episode]);
  if (!request || request.projectName !== projectName || request.episode !== episode) return null;
  return (
    <AdScriptDialog
      // 每次打开都重新初始化，不沿用上一次弹窗里未提交的输入。
      key={`${projectName}:${episode}:${request.regenerate}`}
      request={request}
      onClose={close}
    />
  );
}

interface DialogProps {
  request: AdScriptOpenRequest;
  onClose: () => void;
}

/** 「交给 Agent」即授权覆盖清单对应的版本；附加指令只随本次提交，不保存。 */
export function AdScriptDialog({ request, onClose }: DialogProps) {
  const { t } = useTranslation(["dashboard", "workflow"]);
  const episodeLedger = useEpisodeLedger();
  const scripts = useProjectsStore((s) => s.currentScripts);
  const fieldId = useId();
  const { projectName, episode, regenerate } = request;
  const [instructions, setInstructions] = useState("");
  const [overwrite, setOverwrite] = useState<ScriptOverwrite | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);

  useEffect(() => {
    if (!regenerate) return;
    const controller = new AbortController();
    void API.getAdScriptOverwrite(projectName, episode, controller.signal)
      .then((preview) => {
        if (!controller.signal.aborted) setOverwrite(preview);
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) setPreviewError(errMsg(error));
      });
    return () => controller.abort();
  }, [episode, projectName, regenerate]);

  const handOff = () => {
    if (regenerate && !overwrite) return;
    const episodeRef = episodeAgentRef(episodeLedger, episode, t);
    const lines = [
      regenerate && overwrite
        ? t("ad_script_agent_prefill_regenerate", { episodeRef, episodeId: episode, revision: overwrite.revision })
        : t("workflow:agent_prefill_generate_script", { episodeRef }),
    ];
    const extra = instructions.trim();
    if (extra) lines.push(t("workflow:agent_prefill_instructions", { instructions: extra }));
    useAssistantStore.getState().requestAgentMessage(projectName, lines.join("\n"), { newSession: true });
    useAppStore.getState().setAssistantPanelOpen(true);
    onClose();
  };

  const actionLabel = regenerate ? t("ad_script_regenerate") : t("ad_script_generate");

  return (
    <Dialog open onOpenChange={(next) => { if (!next) onClose(); }}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{actionLabel}</DialogTitle>
          <DialogDescription>{regenerate ? t("ad_script_regenerate_desc") : t("ad_script_desc")}</DialogDescription>
        </DialogHeader>
        <DialogBody className="flex flex-col gap-4">
          {regenerate && (
            overwrite ? (
              <p className="whitespace-pre-line wrap-break-word text-sm text-muted-foreground">
                {itemIdsAsPositionsInText(overwrite.text, scripts, t)}
              </p>
            ) : previewError ? (
              <p role="alert" className="text-sm text-destructive">{previewError}</p>
            ) : (
              <p role="status" className="text-sm text-muted-foreground">{t("common:loading")}</p>
            )
          )}
          <div className="flex flex-col gap-1.5">
            <Label htmlFor={fieldId}>{t("ad_script_instructions_label")}</Label>
            <Textarea
              id={fieldId}
              value={instructions}
              onChange={(event) => setInstructions(event.target.value)}
              maxLength={4000}
              placeholder={t("ad_script_instructions_placeholder")}
            />
          </div>
        </DialogBody>
        <DialogFooter>
          <Button variant={regenerate ? "destructive" : "default"} onClick={handOff} disabled={regenerate && !overwrite}>
            <Bot aria-hidden data-icon="inline-start" />
            {t("script_plan_hand_to_agent")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

interface ButtonProps {
  projectName: string;
  episode: number;
  regenerate: boolean;
}

/** 首次生成直接发给 Agent；已有脚本时保留整份重做的确认流程。 */
export function AdScriptButton({ projectName, episode, regenerate }: ButtonProps) {
  const { t } = useTranslation("dashboard");
  const episodeLedger = useEpisodeLedger();
  const open = useAdScriptStore((s) => s.open);
  const { busy, refusedReason } = useAdScriptEntry(projectName, episode);
  const [agentSessionId, setAgentSessionId] = useState<string | null>(null);
  const prompt = regenerate ? null : t("ad_script_agent_generate_prompt", {
    episodeRef: episodeAgentRef(episodeLedger, episode, t),
    episodeId: episode,
  });
  const agentBusy = useAssistantStore((s) => prompt !== null && (
    (s.agentMessageRequest?.projectName === projectName && s.agentMessageRequest.content === prompt) ||
    (agentSessionId !== null && s.currentSessionId === agentSessionId && s.sessionStatus === "running")
  ));
  const generating = busy || agentBusy;
  const reasonId = useId();
  const reason = generating ? t("ad_script_busy") : refusedReason;
  const Icon = generating ? Loader2 : regenerate ? RotateCcw : Bot;
  const generate = () => {
    if (prompt === null) {
      open({ projectName, episode, regenerate });
      return;
    }
    const assistant = useAssistantStore.getState();
    if (assistant.agentMessageRequest?.projectName === projectName && assistant.agentMessageRequest.content === prompt) return;
    assistant.requestAgentMessage(projectName, prompt, { newSession: true, onSent: setAgentSessionId });
    useAppStore.getState().setAssistantPanelOpen(true);
  };
  const button = (
    <Button
      variant={regenerate ? "outline" : "default"}
      size={regenerate ? "sm" : "default"}
      disabled={reason !== null}
      aria-busy={generating}
      aria-describedby={reason !== null ? reasonId : undefined}
      onClick={generate}
    >
      <Icon className={generating ? "animate-spin" : undefined} aria-hidden data-icon="inline-start" />
      {regenerate ? t("ad_script_regenerate") : t("ad_script_generate_with_agent")}
    </Button>
  );
  if (reason === null) return button;
  // 置灰的按钮收不到悬停：提示挂在外层 span 上，原因另以 sr-only 文本作按钮的描述
  return (
    <Tooltip>
      <TooltipTrigger render={<span className="inline-flex" />}>
        {button}
        <span id={reasonId} className="sr-only">
          {reason}
        </span>
      </TooltipTrigger>
      <TooltipContent>{reason}</TooltipContent>
    </Tooltip>
  );
}

interface ProgressProps {
  projectName: string;
  episode: number;
  /**
   * 本集还没有正式脚本：这时本集的脚本文本任务只可能是整份生成，排队与生成中都呈现。
   * 有正式脚本时只呈现整份生成任务（与提示词编写共用占用槽），并在完成后列出新登记的资产。
   */
  noScript: boolean;
  className?: string;
}

const STATUS_CLS = "flex gap-2.5 rounded-xl border border-primary/20 bg-primary/10 px-4 py-3 text-sm text-subtle-foreground";

/**
 * 广告/短片整份生成的任务进度：排队 / 生成中，或本次登记的待生成资产。
 * 失败的原因与出路由集页顶部的 `TextTaskFailureNote` 统一呈现，这里不重复。
 */
export function AdScriptProgress({ projectName, episode, noScript, className = "" }: ProgressProps) {
  const { t, i18n } = useTranslation("dashboard");
  const { busy, latestTask } = useAdScriptEntry(projectName, episode);
  const [dismissed, setDismissed] = useState<string | null>(null);
  const relevant = noScript || isAdScriptTask(latestTask);
  if (!latestTask || !relevant || dismissed === latestTask.task_id) return null;

  if (busy) {
    return (
      <div
        role="status"
        className={cn(STATUS_CLS, "items-center", className)}
      >
        <Loader2 className="size-4 shrink-0 animate-spin text-primary" aria-hidden />
        <span>
          {latestTask.status === "running" ? t("ad_script_progress_running") : t("ad_script_progress_queued")}{" "}
          <span className="text-muted-foreground">{t("ad_script_progress_hint")}</span>
        </span>
      </div>
    );
  }

  const dismiss = (
    <Button
      variant="ghost"
      size="icon-xs"
      onClick={() => setDismissed(latestTask.task_id)}
      aria-label={t("ad_script_dismiss")}
      className="ml-auto"
    >
      <X aria-hidden="true" />
    </Button>
  );

  const registered = (latestTask.result as AdScriptTaskResult | null)?.new_assets ?? [];
  if (latestTask.status !== "succeeded" || registered.length === 0) return null;
  return (
    <div
      role="status"
      className={cn(STATUS_CLS, "items-start", className)}
    >
      <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-primary" aria-hidden />
      <span>
        {t("ad_script_new_assets", {
          count: registered.length,
          names: formatNameList(
            registered.map((asset) => asset.name),
            i18n.language,
          ),
        })}
      </span>
      {dismiss}
    </div>
  );
}

/** 广告/短片在没有正式脚本时的置灰说明附带的去处：创作灵感在项目概览，商品在商品页，都从概览进入。 */
export function AdScriptInputsLink({ className = "" }: { className?: string }) {
  const { t } = useTranslation("dashboard");
  return (
    <Link href="/" className={cn("rounded-sm underline underline-offset-2 focus-ring", className)}>
      {t("ad_script_edit_inputs")}
    </Link>
  );
}
