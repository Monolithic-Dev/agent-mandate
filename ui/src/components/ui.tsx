// The console's building blocks: page header, cards, stat tiles, empty states, skeletons,
// tooltips, tabs with a sliding indicator, and a confirmation dialog. Built on Radix
// primitives (focus, keyboard and ARIA handled) and animated with Motion; every animation
// respects the system's reduced-motion setting through <MotionConfig reducedMotion="user">.

import * as AlertDialog from "@radix-ui/react-alert-dialog";
import * as Dialog from "@radix-ui/react-dialog";
import * as TabsPrimitive from "@radix-ui/react-tabs";
import * as Tooltip from "@radix-ui/react-tooltip";
import type { Icon } from "../icons";
import { AlertTriangle, Loader2, ShieldCheck, X } from "../icons";
import { AnimatePresence, motion } from "motion/react";
import { type ReactNode, useId, useState } from "react";

export const ease = [0.2, 0.8, 0.2, 1] as const;

/** Fade and rise in; used for page sections and cards. */
export const rise = {
  initial: { opacity: 0, y: 8 },
  animate: { opacity: 1, y: 0 },
  transition: { duration: 0.32, ease },
};

export function PageHeader({
  eyebrow,
  title,
  description,
  actions,
  badge,
}: {
  eyebrow?: ReactNode;
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  badge?: ReactNode;
}) {
  return (
    <motion.header className="page-header" {...rise}>
      <div className="titles">
        {eyebrow && <div className="eyebrow">{eyebrow}</div>}
        <h1>
          {title} {badge}
        </h1>
        {description && <p className="lead">{description}</p>}
      </div>
      {actions && <div className="actions">{actions}</div>}
    </motion.header>
  );
}

export function Card({
  children,
  className = "",
  delay = 0,
  as = "section",
  ...rest
}: {
  children: ReactNode;
  className?: string;
  delay?: number;
  as?: "section" | "div" | "article";
  "aria-label"?: string;
}) {
  const Tag = motion[as];
  return (
    <Tag
      className={`card ${className}`}
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, ease, delay }}
      {...rest}
    >
      {children}
    </Tag>
  );
}

export function CardHead({
  icon: Icon,
  title,
  hint,
  right,
}: {
  icon?: Icon;
  title: ReactNode;
  hint?: ReactNode;
  right?: ReactNode;
}) {
  return (
    <div className="card-head">
      {Icon && <Icon size={16} aria-hidden="true" className="muted" />}
      <h2>{title}</h2>
      {hint && <span className="muted small">{hint}</span>}
      <span className="spacer" />
      {right}
    </div>
  );
}

/** A number that pops when it changes; the text is always the exact value. */
export function Pop({ value, className }: { value: ReactNode; className?: string }) {
  return (
    <motion.span
      key={String(value)}
      className={className}
      initial={{ scale: 1.25, opacity: 0.4 }}
      animate={{ scale: 1, opacity: 1 }}
      transition={{ type: "spring", stiffness: 420, damping: 22 }}
      style={{ display: "inline-block" }}
    >
      {value}
    </motion.span>
  );
}

export function StatCard({
  icon: Icon,
  label,
  value,
  sub,
  tone = "neutral",
  delay = 0,
}: {
  icon: Icon;
  label: string;
  value: ReactNode;
  sub?: ReactNode;
  tone?: "neutral" | "good" | "warn" | "bad" | "accent";
  delay?: number;
}) {
  return (
    <Card as="div" className={`stat tone-${tone}`} delay={delay}>
      <div className="stat-label">
        <span className="stat-icon" aria-hidden="true">
          <Icon size={15} />
        </span>
        {label}
      </div>
      <div className="stat-value">
        <Pop value={value} />
      </div>
      {sub && <div className="stat-sub">{sub}</div>}
    </Card>
  );
}

export function EmptyState({
  icon: Icon = ShieldCheck,
  title,
  children,
}: {
  icon?: Icon;
  title: string;
  children?: ReactNode;
}) {
  return (
    <motion.div className="empty" {...rise}>
      <span className="empty-icon" aria-hidden="true">
        <Icon size={20} />
      </span>
      <strong>{title}</strong>
      {children && <span className="small">{children}</span>}
    </motion.div>
  );
}

export function SkeletonRows({ rows = 4, label }: { rows?: number; label: string }) {
  return (
    <div className="card-body" aria-busy="true">
      <span className="sr-only">{label}…</span>
      {Array.from({ length: rows }, (_, i) => (
        <div
          key={i}
          className="skeleton skeleton-line"
          style={{ width: `${92 - ((i * 17) % 40)}%` }}
        />
      ))}
    </div>
  );
}

export function Spinner({ size = 14 }: { size?: number }) {
  return <Loader2 size={size} className="spin" aria-hidden="true" />;
}

export function Kbd({ children }: { children: ReactNode }) {
  return <kbd className="kbd">{children}</kbd>;
}

export function Tip({ content, children }: { content: ReactNode; children: ReactNode }) {
  if (!content) return <>{children}</>;
  // Its own provider, so a tooltip works anywhere (including isolated component tests).
  return (
    <Tooltip.Provider delayDuration={250}>
      <Tooltip.Root>
        <Tooltip.Trigger asChild>{children}</Tooltip.Trigger>
        <Tooltip.Portal>
          <Tooltip.Content className="tooltip" sideOffset={6}>
            {content}
          </Tooltip.Content>
        </Tooltip.Portal>
      </Tooltip.Root>
    </Tooltip.Provider>
  );
}

export interface TabItem {
  value: string;
  label: string;
  icon?: Icon;
  count?: number;
  hot?: boolean;
  content: ReactNode;
}

/** Radix tabs (roving focus, arrow keys) with an indicator that slides between triggers. */
export function Tabs({
  items,
  value,
  onChange,
  label,
}: {
  items: TabItem[];
  value: string;
  onChange: (value: string) => void;
  label: string;
}) {
  const group = useId();
  return (
    <TabsPrimitive.Root value={value} onValueChange={onChange}>
      <TabsPrimitive.List className="tabs-list" aria-label={label}>
        {items.map((item) => (
          <TabsPrimitive.Trigger key={item.value} value={item.value} className="tab-trigger">
            {item.icon && <item.icon size={15} aria-hidden="true" />}
            {item.label}
            {item.count !== undefined && (
              <span className={`count${item.hot && item.count > 0 ? " hot" : ""}`}>
                <Pop value={item.count} />
              </span>
            )}
            {value === item.value && (
              <motion.span
                layoutId={`tab-${group}`}
                className="tab-indicator"
                transition={{ type: "spring", stiffness: 500, damping: 38 }}
              />
            )}
          </TabsPrimitive.Trigger>
        ))}
      </TabsPrimitive.List>
      {items.map((item) => (
        <TabsPrimitive.Content key={item.value} value={item.value}>
          <motion.div
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.25, ease }}
          >
            {item.content}
          </motion.div>
        </TabsPrimitive.Content>
      ))}
    </TabsPrimitive.Root>
  );
}

export interface ConfirmRequest {
  title: string;
  description: ReactNode;
  detail?: string;
  confirmLabel: string;
  tone?: "default" | "danger";
  icon?: Icon;
  run: () => void | Promise<void>;
}

/** An accessible confirmation dialog: ask(request) opens it; it closes on confirm or cancel. */
export function useConfirm(): [(request: ConfirmRequest) => void, ReactNode] {
  const [request, setRequest] = useState<ConfirmRequest | null>(null);
  const Icon = request?.icon ?? AlertTriangle;
  const node = (
    <AlertDialog.Root open={request !== null} onOpenChange={(open) => !open && setRequest(null)}>
      <AnimatePresence>
        {request && (
          <AlertDialog.Portal forceMount>
            <AlertDialog.Overlay asChild forceMount>
              <motion.div
                className="overlay"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.15 }}
              />
            </AlertDialog.Overlay>
            <AlertDialog.Content asChild forceMount>
              <motion.div
                className="dialog"
                initial={{ opacity: 0, scale: 0.96 }}
                animate={{ opacity: 1, scale: 1 }}
                exit={{ opacity: 0, scale: 0.97 }}
                transition={{ duration: 0.18, ease }}
              >
                <span
                  className={`dialog-icon${request.tone === "danger" ? " danger" : ""}`}
                  aria-hidden="true"
                >
                  <Icon size={20} />
                </span>
                <AlertDialog.Title asChild>
                  <h2>{request.title}</h2>
                </AlertDialog.Title>
                <AlertDialog.Description asChild>
                  <p className="dialog-desc">{request.description}</p>
                </AlertDialog.Description>
                {request.detail && <div className="dialog-call">{request.detail}</div>}
                <div className="dialog-actions">
                  <AlertDialog.Cancel asChild>
                    <button type="button">Cancel</button>
                  </AlertDialog.Cancel>
                  <AlertDialog.Action asChild>
                    <button
                      type="button"
                      className={request.tone === "danger" ? "danger-solid" : "primary"}
                      onClick={() => void request.run()}
                    >
                      {request.confirmLabel}
                    </button>
                  </AlertDialog.Action>
                </div>
              </motion.div>
            </AlertDialog.Content>
          </AlertDialog.Portal>
        )}
      </AnimatePresence>
    </AlertDialog.Root>
  );
  return [setRequest, node];
}

/** A modal for forms (invite a user, change a password): closes on Escape or outside click. */
export function Modal({
  open,
  onOpenChange,
  title,
  description,
  icon: Icon,
  children,
  wide = false,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description?: ReactNode;
  icon?: Icon;
  children: ReactNode;
  wide?: boolean;
}) {
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <AnimatePresence>
        {open && (
          <Dialog.Portal forceMount>
            <Dialog.Overlay asChild forceMount>
              <motion.div
                className="overlay"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.15 }}
              />
            </Dialog.Overlay>
            <Dialog.Content asChild forceMount>
              <motion.div
                className={`dialog${wide ? " dialog-wide" : ""}`}
                initial={{ opacity: 0, scale: 0.96, y: 8 }}
                animate={{ opacity: 1, scale: 1, y: 0 }}
                exit={{ opacity: 0, scale: 0.97 }}
                transition={{ duration: 0.2, ease }}
              >
                <div className="dialog-head">
                  {Icon && (
                    <span className="dialog-icon" aria-hidden="true">
                      <Icon size={20} />
                    </span>
                  )}
                  <div>
                    <Dialog.Title asChild>
                      <h2>{title}</h2>
                    </Dialog.Title>
                    {description ? (
                      <Dialog.Description asChild>
                        <p className="dialog-desc">{description}</p>
                      </Dialog.Description>
                    ) : (
                      <Dialog.Description className="sr-only">{title}</Dialog.Description>
                    )}
                  </div>
                  <Dialog.Close asChild>
                    <button type="button" className="icon-button unstyled" aria-label="Close">
                      <X size={16} />
                    </button>
                  </Dialog.Close>
                </div>
                {children}
              </motion.div>
            </Dialog.Content>
          </Dialog.Portal>
        )}
      </AnimatePresence>
    </Dialog.Root>
  );
}

/** Initials in a coloured circle; the colour is stable for a given seed. */
export function Avatar({ name, seed, size = 30 }: { name: string; seed: string; size?: number }) {
  let sum = 0;
  for (const char of seed) sum = (sum * 31 + char.charCodeAt(0)) % 997;
  const hue = [238, 262, 199, 160, 330, 24, 280][sum % 7];
  const initials =
    name
      .split(/[\s@._-]+/)
      .filter(Boolean)
      .slice(0, 2)
      .map((part) => part[0]?.toUpperCase())
      .join("") || "?";
  return (
    <span
      className="avatar"
      aria-hidden="true"
      style={{
        width: size,
        height: size,
        fontSize: size * 0.38,
        background: `linear-gradient(135deg, hsl(${hue} 70% 58%), hsl(${hue + 30} 70% 46%))`,
      }}
    >
      {initials}
    </span>
  );
}

/** A strong random password for an invite or a reset (shown once, to be passed on). */
export function generatePassword(length = 20): string {
  const alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789-_";
  const bytes = new Uint8Array(length);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (b) => alphabet[b % alphabet.length]).join("");
}
