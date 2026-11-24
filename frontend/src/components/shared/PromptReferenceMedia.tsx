import { useTranslation } from "react-i18next";
import { X } from "lucide-react";
import { API } from "@/api";
import { Button } from "@/components/ui/button";
import { useProjectsStore } from "@/stores/projects-store";
import type { PromptReference } from "@/types/script";

function ReferenceFile({ projectName, reference, label }: {
  projectName: string;
  reference: PromptReference;
  label: string;
}) {
  const fingerprint = useProjectsStore((s) => s.getAssetFingerprint(reference.path));
  const src = API.getFileUrl(
    projectName, reference.path, fingerprint, reference.kind === "image" ? { width: 160 } : undefined,
  );
  if (reference.kind === "video") {
    const continuity = reference.role === "previous_video" || reference.role === "next_video" ? reference.role : null;
    const videoSrc = continuity ? `${src}${src.includes("?") ? "&" : "?"}continuity=${continuity}` : src;
    return <video src={videoSrc} controls playsInline preload="metadata" aria-label={label} className="max-h-44 w-full rounded-md" />;
  }
  if (reference.kind === "audio") {
    return <audio src={src} controls preload="none" aria-label={label} className="w-full" />;
  }
  return <img src={src} alt={label} loading="lazy" className="h-24 w-auto max-w-full rounded-md object-contain" />;
}

export function PromptReferenceMedia({ projectName, references, onRemove, disabled }: {
  projectName: string;
  references: PromptReference[];
  onRemove?: (id: string) => void;
  disabled?: boolean;
}) {
  const { t } = useTranslation("dashboard");
  const indexByKind = { image: 0, video: 0, audio: 0 };
  return (
    <section className="space-y-2" aria-label={t("prompt_reference_media")}>
      <h3 className="text-xs font-medium text-muted-foreground">{t("prompt_reference_media")}</h3>
      <ol className="grid grid-cols-2 gap-2">
        {references.map((reference) => {
          const index = reference.role ? 0 : ++indexByKind[reference.kind];
          const key = reference.role === "first_frame" ? "prompt_reference_first_frame"
            : reference.role === "last_frame" ? "prompt_reference_last_frame"
            : reference.role === "previous_video" ? "prompt_reference_previous_video"
            : reference.role === "next_video" ? "prompt_reference_next_video"
            : reference.kind === "video" ? "prompt_reference_video"
            : reference.kind === "audio" ? "prompt_reference_audio" : "reference_prompt_preview_image";
          const label = reference.time_range ?? t(key, { index, name: reference.name });
          const id = reference.reference_id;
          const removeLabel = t("prompt_reference_remove_image", { name: reference.name });
          return (
            <li key={`${reference.kind}-${reference.role ?? index}-${reference.path}`} className={`min-w-0 space-y-1 rounded-md border border-border/60 p-2 ${reference.kind === "image" ? "" : "col-span-2"}`}>
              <div className="flex items-start justify-between gap-1">
                <p className="flex min-w-0 flex-wrap items-baseline gap-x-2 break-words text-xs text-subtle-foreground">
                  {reference.slot ? <code className="font-mono text-foreground">{reference.slot}</code> : null}
                  <span className="min-w-0">{label}</span>
                </p>
                {reference.kind === "image" && id && onRemove ? (
                  <Button variant="ghost" size="icon-xs" className="shrink-0" title={removeLabel} aria-label={removeLabel}
                          disabled={disabled} onClick={() => onRemove(id)}>
                    <X aria-hidden />
                  </Button>
                ) : null}
              </div>
              <ReferenceFile projectName={projectName} reference={reference} label={label} />
            </li>
          );
        })}
      </ol>
    </section>
  );
}
