import { useTranslation } from "react-i18next";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { LOBBY_FILTERS, type LobbyFilter } from "./lobby-projects";

interface LobbyToolbarProps {
  filter: LobbyFilter;
  onFilterChange: (filter: LobbyFilter) => void;
  counts: Record<LobbyFilter, number>;
}

/**
 * 吸顶在外壳主体顶端的工具栏：左边是带计数的筛选，右边说明排序方式。排序固定按最近活动，不提供切换。
 * 底色不透明，滚过的卡片不会透出来。
 */
export function LobbyToolbar({ filter, onFilterChange, counts }: LobbyToolbarProps) {
  const { t } = useTranslation("dashboard");
  return (
    <div className="sticky top-0 z-sticky flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1 border-y border-border bg-background py-2.5">
      <ToggleGroup
        aria-label={t("lobby_filter_label")}
        className="min-w-0 flex-wrap"
        size="sm"
        value={[filter]}
        onValueChange={(next: string[]) => {
          // 再次点击当前筛选不会取消选中。
          const picked = next.find((value): value is LobbyFilter => (LOBBY_FILTERS as readonly string[]).includes(value));
          if (picked) onFilterChange(picked);
        }}
      >
        {LOBBY_FILTERS.map((key) => (
          <ToggleGroupItem key={key} value={key} className="gap-2 rounded-md aria-pressed:bg-selection aria-pressed:text-primary">
            {t(`lobby_filter_${key}`)}
            <span className="text-xs tabular-nums">{counts[key]}</span>
          </ToggleGroupItem>
        ))}
      </ToggleGroup>
      <span className="ml-auto hidden shrink-0 text-xs text-muted-foreground sm:inline">{t("lobby_sort_recent")}</span>
    </div>
  );
}
