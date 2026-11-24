import { useEffect, useId, useState } from "react";
import { useTranslation } from "react-i18next";
import { Loader2, Mic } from "lucide-react";
import { enqueueCharacterVoiceSample } from "@/actions/generation";
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
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { NarrationVoiceInput } from "@/components/shared/NarrationVoiceInput";
import { Textarea } from "@/components/ui/textarea";
import { useAppStore } from "@/stores/app-store";
import { useConfigStatusStore } from "@/stores/config-status-store";
import { isAssetBusy, useAssetBusyNames } from "./assetBusyGuard";
import { errMsg } from "@/utils/async";

/** 样本文案长度上限（与后端 VOICE_SAMPLE_TEXT_MAX_LENGTH 同值）。
 *  参考音频要求 2-10 秒，而「多少字合成出几秒」随语种与音色而变，无法在提交前精确判定；
 *  此处只作粗护栏挡住整段粘贴——真正的时长判定仍在执行层落盘后做。三语默认文案约 120 字符，
 *  上限取 200 以留出编辑余量。 */
const VOICE_SAMPLE_TEXT_MAX_LENGTH = 200;

interface VoiceOption {
  id: string;
  label: string;
}

interface VoiceSampleButtonProps {
  projectName: string;
  characterName: string;
  voiceStyle: string;
  /** 详情编辑器里其它生成/写入占用中：禁用入口 */
  busy?: boolean;
  beforeGenerate: () => Promise<boolean>;
  saveFirst: boolean;
}

/** 配置角色参考音频并提交后台生成。 */
export function VoiceSampleButton({
  projectName,
  characterName,
  voiceStyle,
  busy = false,
  beforeGenerate,
  saveFirst,
}: VoiceSampleButtonProps) {
  const { t } = useTranslation("dashboard");
  const occupied = useAssetBusyNames("character", projectName).has(characterName);
  const [open, setOpen] = useState(false);
  const [voicesLoading, setVoicesLoading] = useState(false);
  const [voicesConfigured, setVoicesConfigured] = useState(true);
  const [voices, setVoices] = useState<VoiceOption[]>([]);
  const [supportsVoiceDesign, setSupportsVoiceDesign] = useState(false);
  const [usePreset, setUsePreset] = useState(false);
  const [selectedVoice, setSelectedVoice] = useState("");
  const [text, setText] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const modeLabelId = useId();
  const designModeId = useId();
  const presetModeId = useId();
  const voiceFieldId = useId();
  const textFieldId = useId();

  // audio 供应商可用性走全局 config-status-store（路由启动时已拉取一次），不为每个角色
  // 预取音色列表——入口在未配置时即禁用，符合「audio_backend 未配置该入口不可用」的口径。
  const audioConfigured = useConfigStatusStore((s) => s.availableMediaTypes.includes("audio"));

  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    API.getAudioBackendVoices(projectName, { signal: controller.signal })
      .then((res) => {
        // 响应已 resolve 之后才发生的 abort 也要拦住，别把过期结果写进组件状态。
        if (controller.signal.aborted) return;
        setVoicesConfigured(res.configured);
        setVoices(res.voices);
        setSupportsVoiceDesign(res.supports_voice_design);
      })
      .catch((err) => {
        if (controller.signal.aborted) return;
        setVoicesConfigured(false);
        useAppStore.getState().pushToast(errMsg(err), "error");
      })
      .finally(() => {
        if (!controller.signal.aborted) setVoicesLoading(false);
      });
    return () => controller.abort();
  }, [open, projectName]);

  const disabled = busy || occupied || submitting || !audioConfigured;

  const openModal = () => {
    if (disabled) return;
    // 打开时复核占用态：渲染快照之外，角色可能刚被 Agent 或其他标签页的任务占用。
    if (busy || isAssetBusy("character", projectName, characterName)) {
      useAppStore.getState().pushToast(t("voice_sample_resource_busy"), "error");
      return;
    }
    setText(t("voice_sample_text_default"));
    setSelectedVoice("");
    setUsePreset(false);
    setVoicesLoading(true);
    setOpen(true);
  };

  const voiceDesign = supportsVoiceDesign && !usePreset;
  const canGenerate = voiceDesign ? !!voiceStyle.trim() : !!selectedVoice.trim() || voices.length > 0;

  const handleGenerate = async () => {
    const trimmed = text.trim();
    const voice = voiceDesign ? "" : selectedVoice.trim();
    if (!trimmed || !canGenerate || submitting || voicesLoading || !voicesConfigured) return;
    // 弹窗打开期间占用态可能已变化，提交前从 store 读取最新占用态复核（见 docs/standards/frontend.md）。
    if (busy || isAssetBusy("character", projectName, characterName)) {
      useAppStore.getState().pushToast(t("voice_sample_resource_busy"), "error");
      return;
    }
    setSubmitting(true);
    try {
      if (!(await beforeGenerate())) return;
      if (isAssetBusy("character", projectName, characterName)) {
        useAppStore.getState().pushToast(t("voice_sample_resource_busy"), "error");
        return;
      }
      await enqueueCharacterVoiceSample(projectName, characterName, trimmed, voice, voiceDesign);
      setOpen(false);
    } catch (err) {
      useAppStore.getState().pushToast(errMsg(err), "error");
    } finally {
      setSubmitting(false);
    }
  };

  const voiceHint = voicesLoading
    ? t("voice_sample_voice_loading")
    : voices.length === 0
      ? t("voice_sample_no_voices")
      : t("voice_sample_voice_hint");

  return (
    <>
      <span className="flex flex-col items-start gap-1">
        <Button variant="outline" size="sm" onClick={openModal} disabled={disabled}>
          <Mic aria-hidden data-icon="inline-start" />
          {t("voice_sample_action")}
        </Button>
        {audioConfigured ? null : (
          <span className="text-xs text-muted-foreground">{t("voice_sample_not_configured_hint")}</span>
        )}
      </span>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t("voice_sample_modal_title")}</DialogTitle>
            <DialogDescription>{t("voice_sample_modal_desc", { name: characterName })}</DialogDescription>
          </DialogHeader>
          <DialogBody>
            {!voicesLoading && !voicesConfigured ? (
              <p className="text-sm text-muted-foreground">{t("voice_sample_not_configured_hint")}</p>
            ) : (
              <div className="flex flex-col gap-4">
                {supportsVoiceDesign && !voicesLoading && (
                  <div className="flex flex-col gap-2">
                    <span id={modeLabelId} className="text-sm font-medium">{t("voice_sample_voice_label")}</span>
                    <RadioGroup
                      aria-labelledby={modeLabelId}
                      className="flex flex-wrap gap-4"
                      value={voiceDesign ? "design" : "preset"}
                      disabled={submitting}
                      onValueChange={(value) => setUsePreset(value === "preset")}
                    >
                      <div className="flex items-center gap-2">
                        <RadioGroupItem id={designModeId} value="design" />
                        <Label htmlFor={designModeId}>{t("voice_sample_design_mode")}</Label>
                      </div>
                      <div className="flex items-center gap-2">
                        <RadioGroupItem id={presetModeId} value="preset" />
                        <Label htmlFor={presetModeId}>{t("voice_sample_preset_mode")}</Label>
                      </div>
                    </RadioGroup>
                  </div>
                )}
                {voiceDesign && !voicesLoading ? (
                  <p className="text-sm text-muted-foreground">
                    {voiceStyle.trim() || t("voice_sample_design_style_required")}
                  </p>
                ) : (
                  <div className="flex flex-col gap-1.5">
                    <Label htmlFor={voiceFieldId}>{t("voice_sample_voice_label")}</Label>
                    <NarrationVoiceInput
                      id={voiceFieldId}
                      value={selectedVoice}
                      onChange={setSelectedVoice}
                      voices={voices}
                      disabled={voicesLoading || submitting}
                      aria-describedby={`${voiceFieldId}-hint`}
                    />
                    <p id={`${voiceFieldId}-hint`} className="text-xs text-muted-foreground">
                      {voiceHint}
                    </p>
                  </div>
                )}

                <div className="flex flex-col gap-1.5">
                  <Label htmlFor={textFieldId}>{t("voice_sample_text_label")}</Label>
                  <Textarea
                    id={textFieldId}
                    value={text}
                    onChange={(e) => setText(e.target.value)}
                    maxLength={VOICE_SAMPLE_TEXT_MAX_LENGTH}
                    rows={3}
                    disabled={submitting}
                  />
                  <p className="text-xs text-muted-foreground">{t("voice_sample_text_hint")}</p>
                </div>
              </div>
            )}
          </DialogBody>
          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)}>
              {t("common:close")}
            </Button>
            <Button
              onClick={() => void handleGenerate()}
              disabled={disabled || voicesLoading || !voicesConfigured || !canGenerate || !text.trim()}
            >
              {submitting ? (
                <Loader2 aria-hidden data-icon="inline-start" className="animate-spin" />
              ) : (
                <Mic aria-hidden data-icon="inline-start" />
              )}
              {submitting ? t("voice_sample_submitting") : saveFirst ? t("common:save_and_generate") : t("voice_sample_generate")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
