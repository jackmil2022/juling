import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import { Loader2, RefreshCw, Sparkles } from "lucide-react";
import { useTranslation } from "react-i18next";

import { API } from "@/api";
import { generateAdStorySetting, type SettingFields } from "./ad-story-setting-agent";
import { OutputTruncationHint } from "@/components/shared/OutputTruncationHint";
import { UnsavedChangesBar } from "@/components/shared/edit-unit/UnsavedChangesBar";
import { useEditUnit } from "@/components/shared/edit-unit/useEditUnit";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { ONBOARDING_ANCHORS } from "@/onboarding/anchors";
import { refreshAfterWrite } from "@/components/canvas/shared/refreshAfterWrite";
import type { StoryGenerateError } from "@/stores/overview-generate-store";
import type { ProjectOverview } from "@/types";
import { errMsg } from "@/utils/async";

type FieldKey = keyof SettingFields;

const FIELD_KEYS: FieldKey[] = ["synopsis", "genre", "theme", "world_setting"];

function fieldsOf(overview: ProjectOverview | undefined): SettingFields {
  return {
    synopsis: overview?.synopsis ?? "",
    genre: overview?.genre ?? "",
    theme: overview?.theme ?? "",
    world_setting: overview?.world_setting ?? "",
  };
}

interface StorySettingProps {
  projectName: string;
  overview: ProjectOverview | undefined;
  readOnly: boolean;
  sourceGeneration?: {
    available: boolean;
    pending: boolean;
    error: StoryGenerateError | null;
    start: () => void;
  };
  /** 定义时启用广告草稿入口，值表示是否已保存创作灵感或商品。 */
  adInputsPresent?: boolean;
  /** 标题下的一句说明，如广告项目「故事设定」tab 里说明保存后脚本的去向。 */
  description?: string;
  /** 不会卸载本编辑单元的应用内跳转（见 `useEditUnit` 的同名参数）。需传稳定引用。 */
  allowNavigation?: (to: string) => boolean;
}

/**
 * 故事设定：梗概、类型、主题、世界观是一个编辑单元，字段为正文样式，修改后在下方出现内联提示条。
 * 「从原文重新生成」整份替换四个字段，用 AlertDialog 确认；有未保存修改时一并放弃。
 */
export function StorySetting({
  projectName,
  overview,
  readOnly,
  sourceGeneration,
  adInputsPresent,
  description,
  allowNavigation,
}: StorySettingProps) {
  const { t } = useTranslation(["dashboard", "common"]);
  const headingId = useId();
  const fieldId = useId();
  const [confirming, setConfirming] = useState(false);
  const [adGenerating, setAdGenerating] = useState(false);
  const [adGenerateError, setAdGenerateError] = useState<StoryGenerateError | null>(null);
  const adRequest = useRef<AbortController | null>(null);
  useEffect(() => () => adRequest.current?.abort(), []);

  const source = useMemo(() => fieldsOf(overview), [overview]);
  const save = useCallback(
    async (value: SettingFields) => {
      // 落盘前裁剪首尾空白，避免持久化纯空白
      const trimmed: SettingFields = {
        synopsis: value.synopsis.trim(),
        genre: value.genre.trim(),
        theme: value.theme.trim(),
        world_setting: value.world_setting.trim(),
      };
      await API.updateOverview(projectName, trimmed);
      await refreshAfterWrite(projectName, t);
      return trimmed;
    },
    [projectName, t],
  );
  const unit = useEditUnit({ source, save, allowNavigation });

  const hasContent = FIELD_KEYS.some((key) => unit.savedValue[key] !== "");
  const needsConfirm = hasContent || unit.dirty;
  const isAd = adInputsPresent !== undefined;
  const generateError = isAd ? adGenerateError : sourceGeneration?.error;
  const generateLabel = isAd
    ? t("ad_setting_generate")
    : unit.dirty
      ? t("overview_discard_and_regenerate")
      : hasContent
        ? t("overview_regenerate")
        : t("overview_generate");
  const GenerateIcon = isAd ? (adGenerating ? Loader2 : Sparkles) : RefreshCw;

  const generate = async () => {
    if (unit.status === "saving") return;
    if (!isAd) {
      unit.discard();
      sourceGeneration?.start();
      return;
    }
    if (!adInputsPresent || adRequest.current) return;
    const request = new AbortController();
    adRequest.current = request;
    setAdGenerating(true);
    setAdGenerateError(null);
    try {
      const generated = await generateAdStorySetting(projectName, request.signal, t("ad_setting_agent_no_result"));
      if (!request.signal.aborted) unit.setValue(generated);
    } catch (error) {
      if (!request.signal.aborted) {
        setAdGenerateError({ kind: "generate", message: errMsg(error), truncation: null });
      }
    } finally {
      adRequest.current = null;
      if (!request.signal.aborted) setAdGenerating(false);
    }
  };

  const startGenerate = () => {
    if (needsConfirm) {
      setConfirming(true);
      return;
    }
    void generate();
  };

  const confirmGenerate = () => {
    setConfirming(false);
    void generate();
  };

  const setField = (key: FieldKey) => (event: { target: { value: string } }) =>
    unit.setValue((prev) => ({ ...prev, [key]: event.target.value }));

  let body;
  if (sourceGeneration?.pending) {
    body = (
      <div className="flex flex-col gap-3">
        <p role="status" className="flex items-center gap-2 text-sm text-subtle-foreground">
          <span aria-hidden className="size-1.5 shrink-0 animate-breath rounded-full bg-primary" />
          {t("overview_reading_source")}
        </p>
        <Skeleton className="h-4 w-full" />
        <Skeleton className="h-4 w-11/12" />
        <Skeleton className="h-4 w-3/5" />
        <div className="flex gap-2 pt-1">
          <Skeleton className="h-6 w-24" />
          <Skeleton className="h-6 w-28" />
        </div>
      </div>
    );
  } else if (readOnly) {
    body = (
      <dl className="flex max-w-[40em] flex-col gap-3">
        {FIELD_KEYS.filter((key) => unit.savedValue[key] !== "").map((key) => (
          <div key={key}>
            <dt className="text-xs font-medium text-muted-foreground">{t(`overview_field_${key}`)}</dt>
            <dd className="mt-1 text-sm leading-relaxed whitespace-pre-wrap text-subtle-foreground">
              {unit.savedValue[key]}
            </dd>
          </div>
        ))}
      </dl>
    );
  } else {
    body = (
      <fieldset disabled={adGenerating} className="flex min-w-0 max-w-[40em] flex-col gap-3">
        <FieldBlock id={`${fieldId}-synopsis`} label={t("overview_field_synopsis")}>
          <Textarea
            id={`${fieldId}-synopsis`}
            variant="plain"
            value={unit.value.synopsis}
            onChange={setField("synopsis")}
            placeholder={t(isAd ? "ad_setting_placeholder_synopsis" : "overview_placeholder_synopsis")}
            className="max-h-none"
          />
        </FieldBlock>
        <div className="grid grid-cols-1 gap-3 @md/canvas:grid-cols-2">
          <FieldBlock id={`${fieldId}-genre`} label={t("overview_field_genre")}>
            <Input
              id={`${fieldId}-genre`}
              variant="plain"
              value={unit.value.genre}
              onChange={setField("genre")}
              placeholder={t("overview_placeholder_genre")}
            />
          </FieldBlock>
          <FieldBlock id={`${fieldId}-theme`} label={t("overview_field_theme")}>
            <Input
              id={`${fieldId}-theme`}
              variant="plain"
              value={unit.value.theme}
              onChange={setField("theme")}
              placeholder={t("overview_placeholder_theme")}
            />
          </FieldBlock>
        </div>
        <FieldBlock id={`${fieldId}-world`} label={t("overview_field_world_setting")}>
          <Textarea
            id={`${fieldId}-world`}
            variant="plain"
            value={unit.value.world_setting}
            onChange={setField("world_setting")}
            placeholder={t("overview_placeholder_world_setting")}
            className="max-h-none"
          />
        </FieldBlock>
      </fieldset>
    );
  }

  return (
    <section
      aria-labelledby={headingId}
      data-onboarding={ONBOARDING_ANCHORS.workbenchOverview}
      className="flex flex-col gap-3"
    >
      <div className="flex min-h-7 items-center gap-2">
        <h2 id={headingId} className="flex-1 text-sm font-medium text-subtle-foreground">
          {t("overview_story_setting")}
        </h2>
        {!readOnly && (isAd || (sourceGeneration?.available && !sourceGeneration.pending)) ? (
          <Button
            variant="ghost"
            size="sm"
            disabled={adInputsPresent === false || adGenerating || unit.status === "saving"}
            aria-busy={adGenerating}
            onClick={startGenerate}
          >
            <GenerateIcon aria-hidden data-icon="inline-start" className={adGenerating ? "animate-spin" : undefined} />
            {generateLabel}
          </Button>
        ) : null}
      </div>
      {description ? <p className="max-w-[40em] text-sm text-muted-foreground">{description}</p> : null}
      {!readOnly && adInputsPresent === false ? (
        <p className="text-sm text-muted-foreground">{t("ad_setting_inputs_missing")}</p>
      ) : null}
      {adGenerating ? <span role="status" className="sr-only">{t("ad_setting_generating")}</span> : null}

      {generateError && !sourceGeneration?.pending && !adGenerating && !readOnly ? (
        <div role="alert" className="flex flex-col gap-1.5 text-sm text-destructive">
          {generateError.kind === "refresh" ? (
            <p>{t("overview_generate_refresh_failed")}</p>
          ) : (
            <>
              <p>{t("overview_generate_failed", { message: generateError.message })}</p>
              {generateError.truncation ? <OutputTruncationHint truncation={generateError.truncation} /> : null}
            </>
          )}
        </div>
      ) : null}

      {body}

      {readOnly || adGenerating ? null : <UnsavedChangesBar unit={unit} className="max-w-[40em]" />}

      <AlertDialog open={confirming} onOpenChange={setConfirming}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t(isAd ? "ad_setting_generate_confirm_title" : "overview_regenerate_confirm_title")}</AlertDialogTitle>
            <AlertDialogDescription>
              {isAd
                ? t(unit.dirty ? "ad_setting_generate_confirm_desc_dirty" : "ad_setting_generate_confirm_desc")
                : t(unit.dirty ? "overview_regenerate_confirm_desc_dirty" : "overview_regenerate_confirm_desc")}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t("common:cancel")}</AlertDialogCancel>
            <AlertDialogAction variant={!isAd || unit.dirty ? "destructive" : "default"} onClick={confirmGenerate}>
              {t(!isAd && unit.dirty ? "overview_discard_and_regenerate" : "overview_regenerate_confirm")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </section>
  );
}

function FieldBlock({ id, label, children }: { id: string; label: string; children: React.ReactNode }) {
  return (
    <div className="flex min-w-0 flex-col gap-1">
      <label htmlFor={id} className="text-xs font-medium text-muted-foreground">
        {label}
      </label>
      {/* 字段向两侧伸出自身的内边距，静止时正文与标签左对齐 */}
      <div className="-mx-2.5">{children}</div>
    </div>
  );
}
