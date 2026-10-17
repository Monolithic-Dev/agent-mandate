// ⌘K / Ctrl+K: jump to any page or tenant, reset the demo, or switch the theme.

import { Command } from "cmdk";
import { BarChart3, Building2, FileClock, LogOut, Moon, PlayCircle, RotateCcw, Sun, SunMoon, Users, Wand2 } from "../icons";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";

import { api } from "../api";
import { useAuth } from "../auth";
import type { ThemeChoice } from "../theme";
import type { Tenant } from "../types";
import { Kbd } from "./ui";

export function CommandPalette({
  open,
  onOpenChange,
  setTheme,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  setTheme: (choice: ThemeChoice) => void;
}) {
  const navigate = useNavigate();
  const { me, can, canManageUsers, signOut } = useAuth();
  const [tenants, setTenants] = useState<Tenant[]>([]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        onOpenChange(!open);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onOpenChange]);

  useEffect(() => {
    if (!open) return;
    api
      .tenants()
      .then(setTenants)
      .catch(() => setTenants([]));
  }, [open]);

  const go = (path: string) => {
    onOpenChange(false);
    navigate(path);
  };

  const resetDemo = () => {
    onOpenChange(false);
    toast.promise(api.resetDemo(), {
      loading: "Re-seeding the demo tenant…",
      success: (seeded) => ({
        message: `Demo tenant re-seeded with ${seeded.decision_ids.length} decisions`,
        action: { label: "Open", onClick: () => navigate(`/tenants/${seeded.tenant_id}`) },
      }),
      error: (reason: unknown) => (reason instanceof Error ? reason.message : "Reset failed"),
    });
  };

  return (
    <Command.Dialog
      open={open}
      onOpenChange={onOpenChange}
      label="Command menu"
      overlayClassName="overlay"
      contentClassName="cmd"
    >
      <Command.Input placeholder="Search pages, tenants and actions…" />
      <Command.List>
        <Command.Empty>Nothing matches.</Command.Empty>
        <Command.Group heading="Go to">
          <Command.Item onSelect={() => go("/")}>
            <PlayCircle size={16} aria-hidden="true" /> Demo
          </Command.Item>
          <Command.Item onSelect={() => go("/tenants")}>
            <Building2 size={16} aria-hidden="true" /> Tenants
          </Command.Item>
          <Command.Item onSelect={() => go("/eval")}>
            <BarChart3 size={16} aria-hidden="true" /> Evaluation
          </Command.Item>
          {canManageUsers && (
            <Command.Item onSelect={() => go("/admin/users")}>
              <Users size={16} aria-hidden="true" /> Users
            </Command.Item>
          )}
          {can("admin") && (
            <Command.Item onSelect={() => go("/admin/audit")}>
              <FileClock size={16} aria-hidden="true" /> Audit log
            </Command.Item>
          )}
        </Command.Group>
        {tenants.length > 0 && (
          <Command.Group heading="Tenants">
            {tenants.slice(0, 30).map((t) => (
              <Command.Item
                key={t.tenant_id}
                value={`tenant ${t.tenant_id} ${t.name}`}
                onSelect={() => go(`/tenants/${t.tenant_id}`)}
              >
                <Building2 size={16} aria-hidden="true" /> {t.tenant_id}
                <span className="muted small">{t.name}</span>
              </Command.Item>
            ))}
            {tenants.slice(0, 30).map((t) => (
              <Command.Item
                key={`studio-${t.tenant_id}`}
                value={`rule studio ${t.tenant_id}`}
                onSelect={() => go(`/tenants/${t.tenant_id}/studio`)}
              >
                <Wand2 size={16} aria-hidden="true" /> Rule studio: {t.tenant_id}
              </Command.Item>
            ))}
          </Command.Group>
        )}
        <Command.Group heading="Actions">
          {can("admin") && (
            <Command.Item onSelect={resetDemo}>
              <RotateCcw size={16} aria-hidden="true" /> Reset the demo tenant
            </Command.Item>
          )}
          <Command.Item onSelect={() => (setTheme("light"), onOpenChange(false))}>
            <Sun size={16} aria-hidden="true" /> Light theme
          </Command.Item>
          <Command.Item onSelect={() => (setTheme("dark"), onOpenChange(false))}>
            <Moon size={16} aria-hidden="true" /> Dark theme
          </Command.Item>
          <Command.Item onSelect={() => (setTheme("system"), onOpenChange(false))}>
            <SunMoon size={16} aria-hidden="true" /> Follow the system theme
          </Command.Item>
          {me?.kind === "user" && (
            <Command.Item onSelect={() => (onOpenChange(false), void signOut())}>
              <LogOut size={16} aria-hidden="true" /> Sign out
            </Command.Item>
          )}
        </Command.Group>
      </Command.List>
      <div className="cmd-foot" aria-hidden="true">
        <span>
          <Kbd>↑</Kbd> <Kbd>↓</Kbd> move
        </span>
        <span>
          <Kbd>↵</Kbd> open
        </span>
        <span>
          <Kbd>esc</Kbd> close
        </span>
      </div>
    </Command.Dialog>
  );
}
