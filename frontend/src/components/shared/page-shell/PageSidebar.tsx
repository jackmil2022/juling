import { useId, type ReactNode } from "react";
import type { LucideIcon } from "lucide-react";
import { Link } from "wouter";
import { cn } from "cn";

export interface PageSidebarItem {
  id: string;
  label: string;
  icon: LucideIcon;
  /** 选中这一项的地址。选中项记在地址里，切换经路由，离开拦截因此覆盖切换。 */
  href: string;
  /** 标签右侧的标记，如配置问题的警告点、「N 项覆盖」。需要读屏播报时自带可访问名称。 */
  badge?: ReactNode;
  /** 新手引导锚点（`ONBOARDING_ANCHORS` 中的值）。 */
  onboardingAnchor?: string;
}

export interface PageSidebarGroup {
  id: string;
  /** 分组标题；单独成项的条目不设标题。 */
  label?: string;
  items: PageSidebarItem[];
}

interface PageSidebarProps {
  /** 导航区的可访问名称。 */
  label: string;
  groups: PageSidebarGroup[];
  activeId: string;
  /** 切换时替换当前历史记录，浏览器「后退」直接回到进入页面之前的位置。 */
  replace?: boolean;
}

/** 页面分区导航：宽窗口独立纵向滚动，窄窗口横向滚动。 */
export function PageSidebar({ label, groups, activeId, replace }: PageSidebarProps) {
  return (
    <nav
      aria-label={label}
      className="workspace-subnav relative flex shrink-0 gap-4 overflow-x-auto border-b border-border px-2.5 py-2 lg:w-48 lg:flex-col lg:gap-5 lg:overflow-x-hidden lg:overflow-y-auto lg:border-r lg:border-b-0 lg:py-4 xl:w-56"
    >
      {groups.map((group) => (
        <SidebarGroup key={group.id} group={group} activeId={activeId} replace={replace} />
      ))}
    </nav>
  );
}

function SidebarGroup({
  group,
  activeId,
  replace,
}: {
  group: PageSidebarGroup;
  activeId: string;
  replace?: boolean;
}) {
  const labelId = useId();
  return (
    <div className="flex shrink-0 flex-col gap-1">
      {group.label && (
        <p id={labelId} className="px-2 text-[10px] font-semibold tracking-[0.12em] text-muted-foreground uppercase">
          {group.label}
        </p>
      )}
      <ul aria-labelledby={group.label ? labelId : undefined} className="flex gap-0.5 lg:flex-col">
        {group.items.map((item) => {
          const active = item.id === activeId;
          const Icon = item.icon;
          return (
            <li key={item.id}>
              <Link
                href={item.href}
                replace={replace}
                aria-current={active ? "page" : undefined}
                data-onboarding={item.onboardingAnchor}
                className={cn(
                  "flex min-h-9 items-center gap-2 border-b-2 border-transparent px-2 py-1.5 text-sm whitespace-nowrap transition-colors outline-none focus-visible:ring-2 focus-visible:ring-sidebar-ring/50 lg:border-b-0 lg:border-l-2 lg:whitespace-normal",
                  active
                    ? "border-b-sidebar-primary bg-selection text-sidebar-primary lg:border-l-sidebar-primary"
                    : "text-muted-foreground hover:bg-sidebar-accent hover:text-sidebar-foreground",
                )}
              >
                <Icon aria-hidden className="size-4 shrink-0" />
                <span className="min-w-0 flex-1">{item.label}</span>
                {item.badge}
              </Link>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
