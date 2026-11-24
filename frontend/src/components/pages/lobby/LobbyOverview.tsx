import { useTranslation } from "react-i18next";

interface LobbyOverviewProps {
  projectCount: number;
  inProgressCount: number;
  episodesCompleted: number;
  episodesInProduction: number;
}

/**
 * 项目清单概览：项目及分集状态使用列表已有的统计，不额外读取项目详情。
 */
export function LobbyOverview({
  projectCount,
  inProgressCount,
  episodesCompleted,
  episodesInProduction,
}: LobbyOverviewProps) {
  const { t } = useTranslation("dashboard");
  const stats = [
    { label: t("lobby_stat_projects"), value: projectCount },
    { label: t("lobby_stat_active_projects"), value: inProgressCount },
    { label: t("lobby_stat_episodes_completed"), value: episodesCompleted },
    { label: t("lobby_stat_episodes_active"), value: episodesInProduction },
  ];

  return (
    <section className="mb-5">
      <h1 className="mb-4 text-2xl font-semibold">{t("lobby_projects_label")}</h1>
      <dl className="grid grid-cols-2 gap-px bg-border ring-1 ring-border md:grid-cols-4">
        {stats.map(({ label, value }) => (
          <div key={label} className="flex min-w-0 flex-wrap items-baseline gap-x-3 gap-y-0.5 bg-card px-3 py-2.5">
            <dd className="order-1 font-mono text-xl leading-tight font-medium tabular-nums">{value}</dd>
            <dt className="order-2 text-xs break-words text-muted-foreground">{label}</dt>
          </div>
        ))}
      </dl>
    </section>
  );
}
