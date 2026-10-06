"use client";

/**
 * Sidebar links for the teaching domain (student workspace, teacher
 * dashboard, course & case administration).  Mirrors the AdminLink
 * pattern: icon-only with a tooltip when the sidebar is collapsed.
 */

import Link from "next/link";
import { usePathname } from "next/navigation";
import { BookOpenCheck, ClipboardList, GraduationCap } from "lucide-react";
import { useTranslation } from "react-i18next";
import Tooltip from "@/shared/ui/Tooltip";

interface TeachingLinksProps {
  collapsed?: boolean;
}

const LINKS = [
  { href: "/learn", label: "Teaching — Student Training", Icon: GraduationCap },
  { href: "/teach", label: "Teaching — Teacher Dashboard", Icon: ClipboardList },
  { href: "/academic", label: "Teaching — Course & Cases", Icon: BookOpenCheck },
] as const;

export function TeachingLinks({ collapsed = false }: TeachingLinksProps) {
  const pathname = usePathname();
  const { t } = useTranslation();

  if (collapsed) {
    return (
      <div className="flex flex-col items-center gap-1">
        {LINKS.map(({ href, label, Icon }) => {
          const active = pathname === href || pathname.startsWith(`${href}/`);
          return (
            <Tooltip key={href} label={t(label)} side="right">
              <Link
                href={href}
                className={`rounded-lg p-2 transition-colors ${
                  active
                    ? "bg-teal-600/10 text-teal-700 dark:bg-teal-500/20 dark:text-teal-300"
                    : "text-gray-600 hover:bg-gray-100 dark:text-gray-300 dark:hover:bg-gray-800"
                }`}
              >
                <Icon className="h-5 w-5" />
              </Link>
            </Tooltip>
          );
        })}
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-0.5">
      {LINKS.map(({ href, label, Icon }) => {
        const active = pathname === href || pathname.startsWith(`${href}/`);
        return (
          <Link
            key={href}
            href={href}
            className={`flex items-center gap-2 rounded-lg px-3 py-2 text-sm transition-colors ${
              active
                ? "bg-teal-600/10 font-medium text-teal-700 dark:bg-teal-500/20 dark:text-teal-300"
                : "text-gray-700 hover:bg-gray-100 dark:text-gray-200 dark:hover:bg-gray-800"
            }`}
          >
            <Icon className="h-4 w-4 shrink-0" />
            {t(label)}
          </Link>
        );
      })}
    </div>
  );
}
