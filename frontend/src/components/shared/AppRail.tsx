import { Clapperboard, FolderKanban, Images, Settings } from "lucide-react";
import { Link, useLocation } from "wouter";
import { useTranslation } from "react-i18next";
import { ROUTE_APP_ASSETS, ROUTE_APP_PROJECTS, ROUTE_APP_SETTINGS } from "@/app-routes";
import { BRAND } from "@/branding";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { ONBOARDING_ANCHORS } from "@/onboarding/anchors";
import { useConfigStatusStore } from "@/stores/config-status-store";

interface AppRailProps {
  nested?: boolean;
}

const ITEMS = [
  { id: "projects", href: ROUTE_APP_PROJECTS, icon: FolderKanban, label: "dashboard:projects" },
  { id: "assets", href: ROUTE_APP_ASSETS, icon: Images, label: "assets:library_title" },
  { id: "settings", href: ROUTE_APP_SETTINGS, icon: Settings, label: "common:settings" },
] as const;

export function AppRail({ nested = false }: AppRailProps) {
  const { t } = useTranslation(["common", "dashboard", "assets"]);
  const [location] = useLocation();
  const configComplete = useConfigStatusStore((s) => s.isComplete);

  return (
    <nav aria-label={BRAND.name} className="workspace-rail flex shrink-0 items-center gap-3 border-b px-3 py-2 sm:h-full sm:w-[68px] sm:flex-col sm:border-r sm:border-b-0 sm:px-0 sm:py-4">
      <Link
        href={nested ? `~${ROUTE_APP_PROJECTS}` : ROUTE_APP_PROJECTS}
        aria-label={BRAND.name}
        className="grid size-10 shrink-0 place-items-center rounded-md border border-sidebar-border text-sidebar-primary outline-none hover:bg-sidebar-accent focus-visible:ring-2 focus-visible:ring-sidebar-ring focus-visible:ring-offset-2 focus-visible:ring-offset-sidebar"
      >
        <Clapperboard aria-hidden className="size-5" />
      </Link>
      <ul className="flex gap-1 sm:mt-3 sm:flex-col sm:gap-2">
        {ITEMS.map((item) => {
          const Icon = item.icon;
          const active = nested
            ? item.id === "projects"
            : location === item.href || location.startsWith(`${item.href}/`);
          const href = nested ? `~${item.href}` : item.href;
          const label = t(item.label);

          return (
            <li key={item.id}>
              <Tooltip>
                <TooltipTrigger
                  render={
                    <Link
                      href={href}
                      aria-label={label}
                      aria-current={active ? "page" : undefined}
                      data-active={active}
                      data-onboarding={location === ROUTE_APP_PROJECTS && !nested && item.id === "settings" ? ONBOARDING_ANCHORS.lobbySettings : undefined}
                      className="chrome-control relative grid size-10 place-items-center rounded-md outline-none transition-colors focus-visible:ring-2 focus-visible:ring-sidebar-ring"
                    />
                  }
                >
                  <Icon aria-hidden className="size-[18px]" />
                  {item.id === "settings" && !configComplete && (
                    <span role="img" aria-label={t("common:config_incomplete")} className="absolute top-1 right-1 size-2 rounded-full bg-warn" />
                  )}
                </TooltipTrigger>
                <TooltipContent side="right">{label}</TooltipContent>
              </Tooltip>
            </li>
          );
        })}
      </ul>

    </nav>
  );
}
