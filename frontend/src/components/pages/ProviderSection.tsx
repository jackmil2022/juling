import { useEffect, useMemo, useCallback } from "react";
import { useLocation, useSearch } from "wouter";
import { Loader2, Plus } from "lucide-react";
import { useTranslation } from "react-i18next";
import { providerSettingsPath } from "@/app-routes";
import { useProviderCatalog } from "@/hooks/useProviderCatalog";
import type { CatalogRefreshResult } from "@/hooks/useProviderCatalog";
import { useAppStore } from "@/stores/app-store";
import { useEndpointCatalogStore } from "@/stores/endpoint-catalog-store";
import { DetailPane } from "@/components/shared/master-detail/DetailPane";
import { SecondaryRail, type SecondaryRailGroup } from "@/components/shared/master-detail/SecondaryRail";
import { Button } from "@/components/ui/button";
import { CustomProviderDetail } from "./settings/CustomProviderDetail";
import { CustomProviderForm } from "./settings/CustomProviderForm";

type Selection =
  | { kind: "custom"; id: number }
  | { kind: "new-custom" }
  | null;

/** 二级栏条目的 id：预置与自定义供应商的 id 可能撞值，加上分组前缀。 */
function railId(selection: Selection): string | null {
  if (!selection) return null;
  if (selection.kind === "custom") return `custom:${selection.id}`;
  return "custom:new";
}

/** 自定义供应商不按名称猜品牌图标：中转站与协议无关，统一用名称首字。 */
function CustomProviderGlyph({ name }: { name: string }) {
  return (
    <span className="inline-flex size-4 items-center justify-center rounded-sm border border-border bg-muted text-xs leading-none text-subtle-foreground">
      {Array.from(name)[0] ?? "?"}
    </span>
  );
}

export function ProviderSection() {
  const { t, i18n } = useTranslation(["dashboard", "common"]);
  const { customProviders, loading, error: loadError, reload, refresh } = useProviderCatalog(i18n.language);
  const endpointToMediaType = useEndpointCatalogStore((s) => s.endpointToMediaType);
  const fetchEndpoints = useEndpointCatalogStore((s) => s.fetch);
  useEffect(() => { void fetchEndpoints(); }, [fetchEndpoints]);
  const [, navigate] = useLocation();
  const search = useSearch();

  const selection: Selection = useMemo(() => {
    const params = new URLSearchParams(search);
    const custom = params.get("custom");
    if (custom === "new") return { kind: "new-custom" };
    if (custom) {
      const id = parseInt(custom, 10);
      if (!isNaN(id)) return { kind: "custom", id };
    }
    return null;
  }, [search]);
  const modelId = new URLSearchParams(search).get("model") ?? undefined;

  // 保存本身已成功，只是目录重取失败：与「保存失败」区分开，否则用户看到表单无错、列表无新项，
  // 分不清是哪一步没成。被后续请求作废（aborted）是正常并发路径，接管方会写下更新的目录。
  const pushToast = useAppStore((s) => s.pushToast);
  const notifyRefreshFailure = useCallback(
    (result: CatalogRefreshResult) => {
      if (result.status === "failed") pushToast(t("provider_saved_refresh_failed"), "warning");
    },
    [pushToast, t],
  );
  const refreshAfterSave = useCallback(() => {
    void refresh().then(notifyRefreshFailure);
  }, [refresh, notifyRefreshFailure]);

  const selectFirstProvider = useCallback(() => {
    const first = customProviders.find((p) => p.discovery_format === "comfyui");
    navigate(providerSettingsPath(first ? { custom: first.id } : { newCustom: {} }), { replace: true });
  }, [customProviders, navigate]);

  // 从「调用端点」小节的「新建供应商并使用此端点」接线过来的预填。
  const prefill = useMemo(() => {
    const params = new URLSearchParams(search);
    return {
      baseUrl: params.get("base_url") ?? undefined,
      endpoint: params.get("endpoint") ?? undefined,
    };
  }, [search]);

  // 拉取完成后默认选中 ComfyUI 供应商。
  useEffect(() => {
    if (loading || selection) return;
    selectFirstProvider();
  }, [loading, selection, selectFirstProvider]);

  const railGroups = useMemo<SecondaryRailGroup[]>(
    () => [
      {
        id: "custom",
        label: t("provider_rail_custom"),
        items: customProviders.filter((p) => p.discovery_format === "comfyui" || p.models.some((m) => endpointToMediaType[m.endpoint] === "text")).map((p) => ({
          id: `custom:${p.id}`,
          label: p.display_name,
          description: t("custom_provider_model_count", { count: p.models.length }),
          icon: <CustomProviderGlyph name={p.display_name} />,
          href: providerSettingsPath({ custom: p.id }),
        })),
        action: {
          id: "custom:new",
          label: t("add_custom_provider"),
          icon: <Plus className="size-4" />,
          href: providerSettingsPath({ newCustom: {} }),
        },
        emptyText: t("custom_providers_empty"),
      },
    ],
    [t, customProviders, endpointToMediaType],
  );

  if (loadError) {
    return (
      <div role="alert" className="flex flex-col items-start gap-3 p-6">
        <p className="text-sm font-medium text-warn">{t("common:load_failed")}</p>
        <p className="text-sm text-subtle-foreground">{loadError}</p>
        <Button variant="outline" size="sm" onClick={reload}>
          {t("common:retry")}
        </Button>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="flex items-center gap-2 p-6 text-sm text-muted-foreground">
        <Loader2 aria-hidden className="size-4 animate-spin text-primary" />
        {t("loading_providers")}
      </div>
    );
  }

  return (
    // 全出血档：二级栏与详情栏各自滚动
    <div className="flex min-h-0 min-w-0 flex-1">
      <SecondaryRail label={t("provider_list")} groups={railGroups} activeId={railId(selection)} replace />

      {selection?.kind === "custom" && (
        // 深链换了要打开的模型时同样重建
        <CustomProviderDetail
          key={`${selection.id}:${modelId ?? ""}`}
          providerId={selection.id}
          initialModelId={modelId}
          onDeleted={() => {
            void refresh();
            selectFirstProvider();
          }}
          onSaved={refreshAfterSave}
        />
      )}
      {selection?.kind === "new-custom" && (
        <CustomProviderForm
          // 预填参数变了（从另一个端点接线过来）就是另一张新建表单
          key={`new:${prefill.endpoint ?? ""}:${prefill.baseUrl ?? ""}`}
          initialBaseUrl={prefill.baseUrl}
          initialEndpoint={prefill.endpoint}
          onSaved={(created) => {
            // 选中用新建响应带回的 id，不等目录重取的结局：重取被后续请求接管时，
            // 用户会留在填满的新建表单上，再保存一次就多出一个重复供应商。
            if (created) navigate(providerSettingsPath({ custom: created.id }), { replace: true });
            refreshAfterSave();
          }}
        />
      )}
      {!selection && (
        <DetailPane>
          <p className="p-6 text-sm text-muted-foreground">{t("select_provider")}</p>
        </DetailPane>
      )}
    </div>
  );
}
