// The signed-in person, at the foot of the sidebar: who, which role, and the account actions.

import * as Dropdown from "@radix-ui/react-dropdown-menu";
import { ChevronsUpDown, KeyRound, Laptop, LogOut, MonitorSmartphone, ServerCog, Smartphone } from "../icons";
import { type FormEvent, useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import { api, ApiError } from "../api";
import { ROLE_LABEL, useAuth } from "../auth";
import type { SessionInfo } from "../types";
import { relativeTime, shortTime } from "./Bits";
import { Avatar, Modal, SkeletonRows, Spinner, useConfirm } from "./ui";

/** "Edge on Windows" from a user agent string; good enough to recognise your own devices. */
export function deviceName(agent: string | null): { label: string; mobile: boolean } {
  if (!agent) return { label: "Unknown device", mobile: false };
  const browser = /Edg\//.test(agent)
    ? "Edge"
    : /Firefox\//.test(agent)
      ? "Firefox"
      : /Chrome\//.test(agent)
        ? "Chrome"
        : /Safari\//.test(agent)
          ? "Safari"
          : /curl|python|httpx/i.test(agent)
            ? "A script"
            : "A browser";
  const os = /iPhone|iPad/.test(agent)
    ? "iOS"
    : /Android/.test(agent)
      ? "Android"
      : /Windows/.test(agent)
        ? "Windows"
        : /Mac OS X|Macintosh/.test(agent)
          ? "macOS"
          : /Linux/.test(agent)
            ? "Linux"
            : null;
  return {
    label: os ? `${browser} on ${os}` : browser,
    mobile: /iPhone|Android|Mobile/.test(agent),
  };
}

function Sessions({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const { signOut } = useAuth();
  const [rows, setRows] = useState<SessionInfo[] | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    setError(null);
    api.mySessions().then(setRows, (reason: unknown) =>
      setError(reason instanceof ApiError ? reason.message : "Could not load your sessions."),
    );
  }, []);

  // Radix reports only the dialog's own closing; opening comes from the menu, so watch `open`.
  useEffect(() => {
    if (open) load();
    else setRows(null);
  }, [open, load]);

  const change = onOpenChange;

  async function end(session: SessionInfo) {
    setBusy(session.id);
    try {
      await api.endMySession(session.id);
      if (session.current) {
        await signOut();
        return;
      }
      toast.success(`Signed out ${deviceName(session.user_agent).label}.`);
      load();
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : "Could not end that session.");
    } finally {
      setBusy(null);
    }
  }

  return (
    <Modal
      open={open}
      onOpenChange={change}
      title="Where you're signed in"
      description="Sign out a browser you don't recognise. Sessions end after two idle hours."
      icon={MonitorSmartphone}
      wide
    >
      {error && (
        <p className="error-text" role="alert">
          {error}
        </p>
      )}
      {!rows && !error && <SkeletonRows rows={2} label="Loading your sessions" />}
      {rows && (
        <ul className="session-list">
          {rows.map((s) => {
            const device = deviceName(s.user_agent);
            const Icon = device.mobile ? Smartphone : Laptop;
            return (
              <li key={s.id} className="session-row">
                <span className="session-icon" aria-hidden="true">
                  <Icon size={18} />
                </span>
                <div className="session-text">
                  <strong>
                    {device.label}{" "}
                    {s.current && <span className="chip chip-soft">this browser</span>}
                  </strong>
                  <span className="muted small">
                    Active {relativeTime(s.last_seen_at)} · signed in{" "}
                    <span title={shortTime(s.created_at)}>{relativeTime(s.created_at)}</span>
                  </span>
                </div>
                <button
                  type="button"
                  className="sm"
                  onClick={() => void end(s)}
                  disabled={busy !== null}
                >
                  {busy === s.id ? <Spinner /> : null} Sign out
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </Modal>
  );
}

function ChangePassword({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const { setMe } = useAuth();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [again, setAgain] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const mismatch = again.length > 0 && again !== next;
  const tooShort = next.length > 0 && next.length < 12;

  const close = (o: boolean) => {
    if (!o) {
      setCurrent("");
      setNext("");
      setAgain("");
      setError(null);
    }
    onOpenChange(o);
  };

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      setMe(await api.changePassword(current, next));
      toast.success("Password changed. Your other sessions have been signed out.");
      close(false);
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : "Could not change the password.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      open={open}
      onOpenChange={close}
      title="Change your password"
      description="At least 12 characters. Every other browser signed in as you is signed out."
      icon={KeyRound}
    >
      <form className="form-grid" onSubmit={(e) => void submit(e)}>
        <label className="field">
          <span>Current password</span>
          <input
            type="password"
            autoComplete="current-password"
            value={current}
            onChange={(e) => setCurrent(e.target.value)}
            required
          />
        </label>
        <label className="field">
          <span>New password</span>
          <input
            type="password"
            autoComplete="new-password"
            value={next}
            onChange={(e) => setNext(e.target.value)}
            aria-invalid={tooShort}
            required
          />
          {tooShort && <span className="small warn-text">{12 - next.length} more characters.</span>}
        </label>
        <label className="field">
          <span>New password, again</span>
          <input
            type="password"
            autoComplete="new-password"
            value={again}
            onChange={(e) => setAgain(e.target.value)}
            aria-invalid={mismatch}
            required
          />
          {mismatch && <span className="small warn-text">The passwords differ.</span>}
        </label>
        {error && (
          <p className="error-text" role="alert">
            {error}
          </p>
        )}
        <div className="dialog-actions">
          <button type="button" onClick={() => close(false)}>
            Cancel
          </button>
          <button
            type="submit"
            className="primary"
            disabled={busy || !current || next.length < 12 || next !== again}
          >
            {busy && <Spinner />} Change password
          </button>
        </div>
      </form>
    </Modal>
  );
}

export function AccountMenu({ collapsed }: { collapsed: boolean }) {
  const { me, signOut } = useAuth();
  const [changing, setChanging] = useState(false);
  const [sessions, setSessions] = useState(false);
  const [ask, dialog] = useConfirm();
  if (!me) return null;
  const isUser = me.kind === "user";

  const everywhere = () =>
    ask({
      title: "Sign out everywhere?",
      description: "Every browser signed in as you, this one included, is signed out at once.",
      confirmLabel: "Sign out everywhere",
      tone: "danger",
      icon: MonitorSmartphone,
      run: async () => {
        try {
          await api.endMySessions();
        } finally {
          await signOut();
        }
      },
    });

  return (
    <>
      <Dropdown.Root>
        <Dropdown.Trigger asChild>
          <button type="button" className="account-trigger unstyled" aria-label="Account">
            <Avatar name={me.name} seed={me.id} size={28} />
            <span className="account-text nav-label">
              <span className="account-name">{me.name}</span>
              <span className="account-role">
                {ROLE_LABEL[me.role]}
                {me.tenants ? ` · ${me.tenants.length} tenant${me.tenants.length === 1 ? "" : "s"}` : ""}
              </span>
            </span>
            <ChevronsUpDown size={14} aria-hidden="true" className="nav-label muted" />
          </button>
        </Dropdown.Trigger>
        <Dropdown.Portal>
          <Dropdown.Content
            className="menu menu-wide"
            side={collapsed ? "right" : "top"}
            align="start"
            sideOffset={8}
          >
            <div className="menu-header">
              <strong>{me.name}</strong>
              <span className="muted small">
                {isUser ? me.email : "Signed in with the console key set on the server"}
              </span>
            </div>
            <Dropdown.Separator className="menu-separator" />
            {isUser ? (
              <>
                <Dropdown.Item className="menu-item" onSelect={() => setChanging(true)}>
                  <KeyRound size={15} aria-hidden="true" /> Change password
                </Dropdown.Item>
                <Dropdown.Item className="menu-item" onSelect={() => setSessions(true)}>
                  <Laptop size={15} aria-hidden="true" /> Where you're signed in
                </Dropdown.Item>
                <Dropdown.Item className="menu-item" onSelect={everywhere}>
                  <MonitorSmartphone size={15} aria-hidden="true" /> Sign out everywhere
                </Dropdown.Item>
                <Dropdown.Separator className="menu-separator" />
                <Dropdown.Item
                  className="menu-item"
                  onSelect={() => {
                    void signOut().then(() => toast("Signed out."));
                  }}
                >
                  <LogOut size={15} aria-hidden="true" /> Sign out
                </Dropdown.Item>
              </>
            ) : (
              <div className="menu-note small muted">
                <ServerCog size={15} aria-hidden="true" />
                <span>
                  To have people sign in instead, leave <code>MANDATE_UI_KEY</code> empty and add
                  users with <code>python -m mandate.users add</code>.
                </span>
              </div>
            )}
          </Dropdown.Content>
        </Dropdown.Portal>
      </Dropdown.Root>
      <ChangePassword open={changing} onOpenChange={setChanging} />
      <Sessions open={sessions} onOpenChange={setSessions} />
      {dialog}
    </>
  );
}
