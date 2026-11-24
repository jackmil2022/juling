import { useCallback, useId, useMemo, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { cn } from "cn";
import { API } from "@/api";
import { CrossfadeImage } from "@/components/canvas/shared/CrossfadeImage";
import { useLeaveGuard } from "@/components/shared/edit-unit/LeaveGuard";
import { UnsavedChangesBar } from "@/components/shared/edit-unit/UnsavedChangesBar";
import { useEditUnit } from "@/components/shared/edit-unit/useEditUnit";
import { PromptPreviewButton } from "@/components/shared/PromptPreviewButton";
import { TruncatedText } from "@/components/shared/TruncatedText";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { SheetBody, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Textarea } from "@/components/ui/textarea";
import { useProjectsStore } from "@/stores/projects-store";
import { useAppStore } from "@/stores/app-store";
import { useAssistantStore } from "@/stores/assistant-store";
import { DEFAULT_CHARACTER_VOICE_BINDING } from "@/types";
import type { AssetSheetStatusRow, AssetSheetType, Character, Product } from "@/types";
import { refreshAfterWrite } from "@/components/canvas/shared/refreshAfterWrite";
import { ASSET_SHEET_TYPE_ICON } from "@/components/assets/asset-type-icons";
import { rejectIfAssetBusy, useAssetBusyNames } from "./assetBusyGuard";
import { AssetAliasesField } from "./AssetAliasesField";
import { AssetImageDialog } from "./AssetImageDialog";
import { AssetOriginalsField } from "./AssetOriginalsField";
import { hasUsableDescription } from "./AssetSheetStatusBadge";
import {
  assetFieldsEqual,
  assetFieldsOf,
  assetFieldsPatch,
  normalizeAssetFields,
  updateAssetFields,
  type AssetFields,
} from "./asset-editor-model";
import { CharacterDerivativesField } from "./CharacterDerivativesField";
import { CharacterVoiceField } from "./CharacterVoiceField";
import { EditableAssetName } from "./EditableAssetName";
import { markerOf, toGalleryAsset, type GalleryAssetSource } from "./gallery-model";
import { GalleryStatusMarker } from "./GalleryStatusMarker";
import { GenerateButton } from "./GenerateButton";
import { AssetWriteProvider, useAssetWrites } from "./useAssetWrites";
import { useStaleRegenerateConfirm } from "./useStaleRegenerateConfirm";

const DESCRIPTION_PLACEHOLDER = {
  character: "dashboard:character_desc_placeholder",
  scene: "dashboard:scene_desc_placeholder",
  prop: "dashboard:prop_desc_placeholder",
  product: "dashboard:product_desc_placeholder",
} as const satisfies Record<AssetSheetType, string>;

function EditorSection({
  title,
  htmlFor,
  action,
  children,
}: {
  title: string;
  /** 区块只有一个输入框时，标题即它的标签。 */
  htmlFor?: string;
  action?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="flex flex-col gap-2">
      <div className="flex min-h-7 items-center justify-between gap-2">
        {htmlFor ? <Label htmlFor={htmlFor}>{title}</Label> : <h3 className="text-sm font-medium">{title}</h3>}
        {action}
      </div>
      {children}
    </section>
  );
}

export interface AssetDetailEditorProps {
  projectName: string;
  assetType: AssetSheetType;
  name: string;
  asset: GalleryAssetSource;
  /** 产物清单对这张资产图的判定；未取到时按条目上是否登记了资产图展示。 */
  sheetStatus: AssetSheetStatusRow | undefined;
  /** 资产图任务占用中。 */
  generating: boolean;
  writing?: boolean;
  readOnly: boolean;
  onGenerate: (name: string) => unknown;
  /** 改名已提交时调用。 */
  onRenamed: (from: string, to: string) => void;
  /** 头部右侧的上一个与下一个。 */
  navigation?: ReactNode;
}

/**
 * 一个资产的详情编辑器，放在详情 Sheet 里。一个资产是一个编辑单元：描述、声音风格、品牌与卖点
 * 进入未保存修改，由 Sheet 底部的提示条统一保存；改名、上传、增删别名立即执行。
 * 四类资产共用这一个编辑器，类型差异只体现在字段区块的开关上。
 */
export function AssetDetailEditor({
  projectName,
  assetType,
  name,
  asset,
  sheetStatus,
  generating,
  writing = false,
  readOnly,
  onGenerate,
  onRenamed,
  navigation,
}: AssetDetailEditorProps) {
  const { t } = useTranslation(["assets", "dashboard", "common"]);
  const descriptionId = useId();
  const brandId = useId();
  const sellingPointsId = useId();
  const [viewingSheet, setViewingSheet] = useState(false);
  const [failedUrl, setFailedUrl] = useState<string | null>(null);
  const voiceBinding = useProjectsStore(
    (s) => s.currentProjectData?.character_voice_binding ?? DEFAULT_CHARACTER_VOICE_BINDING,
  );
  const writes = useAssetWrites();
  const occupied = useAssetBusyNames(assetType, projectName).has(name);

  const source = useMemo(() => assetFieldsOf(assetType, asset), [assetType, asset]);
  const save = useCallback(
    async (value: AssetFields, saved: AssetFields) => {
      await updateAssetFields(projectName, assetType, name, assetFieldsPatch(assetType, value, saved));
      await refreshAfterWrite(projectName, t);
      return normalizeAssetFields(value);
    },
    [projectName, assetType, name, t],
  );
  const unit = useEditUnit<AssetFields>({
    source,
    save,
    isEqual: assetFieldsEqual,
    leaveTitle: t("assets:edit_leave_title", { name }),
  });
  const { value, setValue } = unit;
  // 区块里的上传、删除在途时，离开先等它们落定
  useLeaveGuard({ dirty: false, saving: writes.writing || writing, save: unit.save });

  const saving = unit.status === "saving";
  // 改名会搬动落盘文件，与任何在途写请求交错都会留下旧名孤儿文件，所以把它们都算进占用态
  const busy = generating || occupied || saving || writes.writing || writing;

  const gallery = toGalleryAsset(assetType, name, asset);
  const sheetFp = useProjectsStore((s) => (gallery.sheetPath ? s.getAssetFingerprint(gallery.sheetPath) : null));
  const sheetUrl =
    gallery.sheetPath && sheetStatus?.status !== "missing"
      ? API.getFileUrl(projectName, gallery.sheetPath, sheetFp)
      : null;
  const imageUrl = sheetUrl && sheetUrl !== failedUrl ? sheetUrl : null;
  const Icon = ASSET_SHEET_TYPE_ICON[assetType];
  const imageAlt = t("assets:asset_image_alt", { name });

  const staleConfirm = useStaleRegenerateConfirm({
    projectName,
    assetType,
    name,
    status: sheetStatus,
    hasSheet: Boolean(gallery.sheetPath),
    onGenerate: () => onGenerate(name),
  });

  const generate = () => {
    if (busy || rejectIfAssetBusy(assetType, projectName, name, t, "assets:gallery_busy_hint")) return;
    // 资产图只由描述与原图生成：改了描述，保存后这张图就会过期，服务端此刻的判定还看不到
    const willBeStale = value.description !== unit.savedValue.description;
    void unit.saveAndGenerate(() => {
      if (!rejectIfAssetBusy(assetType, projectName, name, t, "assets:gallery_busy_hint")) return onGenerate(name);
    }, {
      confirm: async () => {
        if (!(await staleConfirm.confirm({ willBeStale }))) return false;
        return !rejectIfAssetBusy(assetType, projectName, name, t, "assets:gallery_busy_hint");
      },
    });
  };

  const handoffProductPrompt = () => {
    const lines = [
      `请为商品「${name}」生成适配 MiniMax H3 Image 的标准资产图提示词，并将完整提示词写入项目。`,
      `先调用 inspect_images，传入 {"resource_type":"product","ids":["${name}"],"image_source":"product_reference"}，逐张检查商品登记的全部原图，整合互补视角中的可确认信息。原图缺失、无法读取或工具报错时，继续调用 get_project_content（无参数），查看 products 中该商品的 description、brand、selling_points，并参考项目 brief、style、style_description 与相关设定。`,
      "描述必须尽可能完整，逐项核对主体轮廓、长宽厚比例、结构、部件数量与位置、连接关系、边缘、接口、按键、显示区域、图案、Logo、文字、颜色、材质、表面工艺和可读规格，不遗漏原图中清晰可见的细节。仅描述原图或项目资料能够确认的内容，不推测被遮挡或未展示的部位，不把卖点臆造成外观、品牌、文字或参数；模糊文字按其可见形态与排版描述，不猜字。资料不足时也要生成提示词，但只写已知外观。",
      "先综合各原图确认同一型号、配色和开合状态，再把正面、背面、左侧、右侧、顶面和底面可证实的细节分配给四格。说明每格能看到哪些面，明确各部件归属、数量、位置、朝向和相对尺寸，并交代跨面的接缝、图案和纹理如何衔接。参考图是细节和长宽厚比例的基准，四格只改变观察角度。扁平或对称商品也输出四视图。",
      "保留以下标题、顺序及固定文字，替换所有方括号占位内容。每格根据能够确认的资料详细描述。",
      "```text",
      `商品「${name}」的标准资产图。`,
      "",
      "主体产品：商品本体是画面唯一且最突出的主体，占据主要视觉面积并完整清晰呈现。【主体细节占位】",
      "背景环境：【背景环境细节占位】",
      "布光与材质：【布光与材质细节占位】",
      "构图与文字排版：2×2 四视图，统一比例与留白，各格完整入画，面板使用无标签版式。【写清商品原有文字和 Logo 的排版与位置。】",
      "左上正面平视：【写清正面轮廓、长宽比、主标识与各部件。】",
      "右上背面平视：【写清背面轮廓、背标、接缝与背面部件。】",
      "左下左前上方三分之四视图：【写清正面、左侧和顶面，展示厚度与跨面结构。】",
      "右下右后下方三分之四视图：【写清背面、右侧和底面，展示厚度与跨面结构。】",
      "",
      "商品保真优先于项目画风。以商品原图为细节和长宽厚比例的基准，完整保留原有 Logo、文字、配色、材质、轮廓、结构和部件位置。四格为同一商品的同一状态，只改变观察角度。各部件相对尺寸、数量、朝向和间距保持一致，跨面纹理和接缝准确对接。原图缺失时以已确认的商品资料为准，未知区域沿用已确认的基础轮廓与表面质感。画面仅呈现商品本体及指定背景，包装上印刷的人像图案原样保留。",
      "",
      "Visual requirements: 画面干净，只呈现正文要求的视觉元素；文字、字幕和标识仅在正文明确要求时出现，不叠加水印。",
      "```",
      `使用 patch_project，以 table="products"、entries 中商品名「${name}」为键，将上述完整提示词写入 image_prompt_override。写入成功后简短确认，不要改 description、商品名或其他商品字段。`,
    ];
    useAssistantStore.getState().requestAgentMessage(projectName, lines.join("\n"));
    useAppStore.getState().setAssistantPanelOpen(true);
  };

  const handoffAssetDescription = () => {
    const isCharacter = assetType === "character";
    const table = isCharacter ? "characters" : "props";
    const assetName = JSON.stringify(name);
    const lines = [
      `请补全当前项目 ${table} 表中 ${assetName} 的生成设定，并回填资产详情。`,
      `先调用 get_project_content 查看 ${table} 中这一个条目的原始设定，以及相关剧本和参考信息。可用时用 inspect_images 查看该资产已有的图，传入 ${JSON.stringify({ resource_type: assetType, ids: [name] })}。用户或剧本确认的信息和上传原图优先于已有生成图。`,
      "读取 generate-assets 技能的描述指南，保留已确认的设计和可辨识细节。沿用项目当前的生图宽高比。每格等比例缩放并完整取景，画布比例与物体长宽厚比例分别处理。",
      isCharacter
        ? "将 description 分为身份与体态、面部特写、发型与服装三段。明确性别与年龄，写清首格为平视正脸近景，从发顶取到上胸，保留自然相连的颈部、双肩和衣领，并逐项描述脸型、下颌、发际线、眉眼、瞳色、鼻唇、肤色和表情。正面、90° 正侧面和背面三个全身视图均从头到脚完整入画，采用同一头身比与服装配饰。把音高、音色、语速、停顿、吐字、气息、句尾与情绪写入独立的 voice_style，作为该角色的 TTS 声音设定。"
        : "先写清整体长宽厚比例、材质、部件尺寸与连接，再按六面列出结构。多面立体道具在 description 中单设 2×2 四视图段，逐格写清机位、可见面和只出现在该面的实际零件。左上正面平视，右上背面平视，左下左前上方看正面、左侧和顶面，右下右后下方看背面、右侧和底面。比例尺、尺寸关系、配色和开合状态四格一致。",
      `调用 patch_project，table=${table}，entries 只包含 ${assetName}。写回 ${isCharacter ? "description 和 voice_style" : "description"} 后核对字段。本次只补资产设定。`,
    ];
    useAssistantStore.getState().requestAgentMessage(projectName, lines.join("\n"));
    useAppStore.getState().setAssistantPanelOpen(true);
  };

  const setField = <K extends keyof AssetFields>(key: K, next: AssetFields[K]) =>
    setValue((prev) => ({ ...prev, [key]: next }));

  const generateLabel = unit.dirty
    ? t("common:save_and_generate")
    : gallery.sheetPath
      ? t("dashboard:regenerate_design")
      : t("dashboard:generate_design");
  const describable = hasUsableDescription(value.description);
  const character = assetType === "character" ? (asset as Character) : null;
  const product = assetType === "product" ? (asset as Product) : null;
  const aliases = "aliases" in asset ? (asset.aliases ?? []) : [];
  const originals = character
    ? character.reference_image
      ? [character.reference_image]
      : []
    : (product?.reference_images ?? []);

  return (
    <AssetWriteProvider value={writes.track}>
      <SheetHeader>
        <div className="flex min-w-0 items-center gap-2">
          <div className="min-w-0 flex-1">
            <EditableAssetName
              projectName={projectName}
              name={name}
              assetType={assetType}
              readOnly={readOnly || gallery.audioOnly}
              busy={busy}
              onRenamed={onRenamed}
              renderTitle={(hidden) => (
                <SheetTitle className={cn("min-w-0", hidden && "sr-only")}>
                  <TruncatedText text={name} />
                </SheetTitle>
              )}
            />
          </div>
          {navigation}
        </div>
      </SheetHeader>

      <SheetBody>
        <div className="flex flex-col gap-6">
          {!gallery.audioOnly && <section aria-label={t("assets:sheet_section")} className="flex flex-col gap-3">
            <div className="relative aspect-video overflow-hidden rounded-lg border border-border bg-muted/40">
              {imageUrl ? (
                <button
                  type="button"
                  onClick={() => setViewingSheet(true)}
                  aria-label={t("assets:view_image", { name: imageAlt })}
                  className="focus-ring block size-full"
                >
                  <CrossfadeImage
                    src={imageUrl}
                    alt={imageAlt}
                    className="object-contain"
                    onError={() => setFailedUrl(imageUrl)}
                    fallback={null}
                  />
                </button>
              ) : (
                <div className="flex size-full flex-col items-center justify-center gap-2 text-muted-foreground">
                  <Icon aria-hidden className="size-8" />
                  <span className="text-sm">{t("assets:no_sheet")}</span>
                </div>
              )}
              <GalleryStatusMarker
                marker={markerOf(gallery, sheetStatus, generating)}
                className="absolute top-2 left-2"
              />
            </div>
            {readOnly ? null : (
              <div className="flex flex-col gap-1.5">
                <GenerateButton
                  onClick={generate}
                  loading={generating}
                  disabled={!describable || busy}
                  label={generateLabel}
                  className="w-full"
                />
                {describable ? null : (
                  <p className="text-xs text-muted-foreground">{t("assets:sheet_description_required")}</p>
                )}
              </div>
            )}
          </section>}

          {gallery.audioOnly || (readOnly && originals.length === 0)
            ? null
            : (character || product) && (
                <EditorSection title={product ? t("dashboard:product_reference_images") : t("assets:original_section")}>
                  <AssetOriginalsField
                    projectName={projectName}
                    name={name}
                    assetType={product ? "product" : "character"}
                    paths={originals}
                    readOnly={readOnly}
                    busy={busy}
                  />
                </EditorSection>
              )}

          <EditorSection
            title={t("assets:field.description")}
            htmlFor={descriptionId}
            action={
              readOnly || gallery.audioOnly ? null : (
                <PromptPreviewButton
                  projectName={projectName}
                  title={t("assets:prompt_preview_title", { name })}
                  beforeOpen={unit.save}
                  saveFirst={unit.dirty}
                  // 保存在途时再「保存并预览」会并发第二次保存，先后落定可能让旧草稿盖住新草稿
                  disabled={saving}
                  load={(signal) => API.previewAssetPrompt(projectName, assetType, name, value.description, { signal })}
                  savePrompt={(text) => writes.track((async () => {
                    await updateAssetFields(projectName, assetType, name, { image_prompt_override: text });
                    await refreshAfterWrite(projectName, t);
                  })())}
                  onAgentGenerate={
                    product ? handoffProductPrompt : character || assetType === "prop" ? handoffAssetDescription : undefined
                  }
                />
              )
            }
          >
            <Textarea
              id={descriptionId}
              value={value.description}
              readOnly={readOnly}
              onChange={(e) => setField("description", e.target.value)}
              rows={3}
              placeholder={t(DESCRIPTION_PLACEHOLDER[assetType])}
            />
          </EditorSection>

          {product && (
            <>
              <EditorSection title={t("dashboard:product_brand_label")} htmlFor={brandId}>
                <Input
                  id={brandId}
                  value={value.brand}
                  readOnly={readOnly}
                  onChange={(e) => setField("brand", e.target.value)}
                  placeholder={t("dashboard:product_brand_placeholder")}
                />
              </EditorSection>
              <EditorSection title={t("dashboard:product_selling_points_label")} htmlFor={sellingPointsId}>
                <Textarea
                  id={sellingPointsId}
                  value={value.sellingPoints}
                  readOnly={readOnly}
                  onChange={(e) => setField("sellingPoints", e.target.value)}
                  rows={3}
                  placeholder={t("dashboard:product_selling_points_placeholder")}
                />
              </EditorSection>
            </>
          )}

          {character && (
            <EditorSection title={t("dashboard:voice_section")}>
              <CharacterVoiceField
                projectName={projectName}
                name={name}
                voiceStyle={value.voiceStyle}
                saveBeforeSample={unit.save}
                sampleNeedsSave={unit.dirty}
                onVoiceStyleChange={(next) => setField("voiceStyle", next)}
                referenceAudio={character.reference_audio}
                voiceBinding={gallery.audioOnly ? "reference_audio" : voiceBinding}
                readOnly={readOnly}
                busy={busy}
              />
            </EditorSection>
          )}

          {assetType !== "product" && !(readOnly && aliases.length === 0) && (
            <EditorSection title={t("assets:aliases_label")}>
              <AssetAliasesField
                projectName={projectName}
                name={name}
                assetType={assetType}
                aliases={aliases}
                readOnly={readOnly}
                busy={busy}
              />
            </EditorSection>
          )}

          {character && !gallery.audioOnly && !(readOnly && Object.keys(character.derivatives ?? {}).length === 0) && (
            <EditorSection title={t("assets:derivatives")}>
              <CharacterDerivativesField
                projectName={projectName}
                characterName={name}
                derivatives={character.derivatives ?? {}}
                ownerSheet={character.character_sheet}
                readOnly={readOnly}
                busy={busy}
              />
            </EditorSection>
          )}
        </div>
      </SheetBody>

      {readOnly ? null : <UnsavedChangesBar unit={unit} className="mx-5 mb-4 shrink-0" />}

      <AssetImageDialog
        src={viewingSheet ? imageUrl : null}
        title={name}
        alt={imageAlt}
        onClose={() => setViewingSheet(false)}
      />
      {staleConfirm.dialog}
    </AssetWriteProvider>
  );
}
