import { useEffect, useRef, type ReactNode } from "react";
import { Link } from "wouter";
import { Bot, ChevronDown, FileArchive, Loader2, MoreHorizontal, Plus, Search, Trash2 } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useLocation } from "wouter";
import { cn } from "cn";
import { settingsSectionPath } from "@/app-routes";
import { PageHeader } from "@/components/shared/page-shell/PageHeader";
import { Button, buttonVariants } from "@/components/ui/button";
import { ButtonGroup } from "@/components/ui/button-group";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { InputGroup, InputGroupAddon, InputGroupInput } from "@/components/ui/input-group";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { ONBOARDING_ANCHORS } from "@/onboarding/anchors";

interface LobbyHeaderProps {
  query: string;
  onQueryChange: (query: string) => void;
  onCreate: () => void;
  onImport: () => void;
  importing: boolean;
  onOpenDeleted: () => void;
}

/** 项目工具栏：搜索、外部 Agent、回收站与项目新建和导入。 */
export function LobbyHeader({ query, onQueryChange, onCreate, onImport, importing, onOpenDeleted }: LobbyHeaderProps) {
  const { t } = useTranslation("dashboard");
  const [, navigate] = useLocation();
  const searchRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const focusSearch = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        searchRef.current?.focus();
      }
    };
    window.addEventListener("keydown", focusSearch);
    return () => window.removeEventListener("keydown", focusSearch);
  }, []);

  return (
    <PageHeader
      actions={
        <>
          <div className="hidden items-center gap-1 sm:flex">
            <IconLink href={settingsSectionPath("external-agent")} label={t("dashboard:settings_external_agent")}>
              <Bot aria-hidden />
            </IconLink>
            <Tooltip>
              <TooltipTrigger
                render={
                  <Button
                    variant="ghost"
                    size="icon"
                    aria-label={t("dashboard:lobby_deleted_projects")}
                    onClick={onOpenDeleted}
                  />
                }
              >
                <Trash2 aria-hidden />
              </TooltipTrigger>
              <TooltipContent>{t("dashboard:lobby_deleted_projects")}</TooltipContent>
            </Tooltip>
            <span aria-hidden className="mx-1 h-5 w-px bg-border" />
          </div>
          <DropdownMenu>
            <DropdownMenuTrigger
              render={<Button variant="ghost" size="icon" aria-label={t("dashboard:lobby_more_actions")} className="sm:hidden" />}
            >
              <MoreHorizontal aria-hidden />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="sm:hidden">
              <DropdownMenuItem onClick={() => navigate(settingsSectionPath("external-agent"))}>
                <Bot aria-hidden />
                {t("dashboard:settings_external_agent")}
              </DropdownMenuItem>
              <DropdownMenuItem onClick={onOpenDeleted}>
                <Trash2 aria-hidden />
                {t("dashboard:lobby_deleted_projects")}
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
          <ButtonGroup>
            <Button
              onClick={onCreate}
              aria-label={t("dashboard:lobby_new_project")}
              data-onboarding={ONBOARDING_ANCHORS.lobbyCreateProject}
              className="px-2.5 sm:px-3"
            >
              <Plus aria-hidden data-icon="inline-start" />
              <span className="hidden sm:inline">{t("dashboard:lobby_new_project")}</span>
            </Button>
            <DropdownMenu>
              <DropdownMenuTrigger
                render={
                  <Button size="icon" aria-label={t("dashboard:lobby_more_create_options")} aria-busy={importing} />
                }
              >
                {importing ? <Loader2 aria-hidden className="animate-spin" /> : <ChevronDown aria-hidden />}
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem disabled={importing} onClick={onImport}>
                  <FileArchive aria-hidden />
                  {t("dashboard:lobby_import_zip_ellipsis")}
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </ButtonGroup>
        </>
      }
    >
      <InputGroup className="max-w-80 bg-background dark:bg-background">
        <InputGroupAddon>
          <Search aria-hidden />
        </InputGroupAddon>
        <InputGroupInput
          ref={searchRef}
          type="search"
          value={query}
          onChange={(event) => onQueryChange(event.target.value)}
          aria-label={t("dashboard:lobby_search_label")}
          aria-keyshortcuts="Meta+K Control+K"
          placeholder={t("dashboard:lobby_search_placeholder")}
          autoComplete="off"
          spellCheck={false}
        />
      </InputGroup>
    </PageHeader>
  );
}

function IconLink({
  href,
  label,
  children,
}: {
  href: string;
  label: string;
  children: ReactNode;
}) {
  return (
    <Tooltip>
      <TooltipTrigger
        render={
          <Link
            href={href}
            aria-label={label}
            // eslint-disable-next-line shadcn/require-static-classes -- 链接借用 buttonVariants 的 ghost/icon 外观；Button 渲染为链接会被 Base UI 加上 role="button"，故不能换成 render={<Button />}，TooltipTrigger 自身不带样式（见 eslint.config.js 的 UNSTYLED_PRIMITIVES）
            className={cn(buttonVariants({ variant: "ghost", size: "icon" }), "relative")}
          />
        }
      >
        {children}
      </TooltipTrigger>
      <TooltipContent>{label}</TooltipContent>
    </Tooltip>
  );
}
