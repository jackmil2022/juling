import type { ReactNode } from "react";
import { ChevronLeft } from "lucide-react";

import { TruncatedText } from "@/components/shared/TruncatedText";
import { Button } from "@/components/ui/button";

interface PageHeaderProps {
  /** 「返回」按钮；返回到进入页面之前的位置时，用 `useReturnTo` 取得 `onClick`。 */
  back?: { label: string; onClick: () => void };
  title?: string;
  subtitle?: string;
  /** 标题组之后的自定义内容，如项目大厅的品牌与搜索。 */
  children?: ReactNode;
  /** 靠右的页面级动作。 */
  actions?: ReactNode;
}

/**
 * 页面外壳的顶栏，高 56px：「返回 | 标题 | 副标题」成组靠左，返回箭头与侧栏图标在同一条竖线上，
 * 页面级动作靠右。
 */
export function PageHeader({ back, title, subtitle, children, actions }: PageHeaderProps) {
  return (
    <header className="workspace-chrome flex min-h-14 shrink-0 flex-wrap items-center gap-2 border-b border-border px-3 py-1.5 sm:flex-nowrap md:gap-3 xl:px-6">
      <div className="flex min-w-0 flex-1 items-center gap-2 md:gap-3">
        {back && (
          <>
            <Button variant="ghost" onClick={back.onClick}>
              <ChevronLeft aria-hidden data-icon="inline-start" />
              {back.label}
            </Button>
            <span aria-hidden className="h-4 w-px shrink-0 bg-border" />
          </>
        )}
        {title && (
          <h1 className="min-w-0 text-base font-semibold">
            <TruncatedText text={title} />
          </h1>
        )}
        {subtitle && <TruncatedText text={subtitle} className="sr-only text-sm text-muted-foreground lg:not-sr-only" />}
        {children}
      </div>
      {actions && <div className="flex shrink-0 items-center gap-1 md:gap-2">{actions}</div>}
    </header>
  );
}
