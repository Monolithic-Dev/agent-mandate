// Users: who can sign in to the console, with which role and which tenants.
// Admins with every tenant only (the API enforces it; the page explains it).

import * as Dropdown from "@radix-ui/react-dropdown-menu";
import { Check, Copy, KeyRound, MonitorSmartphone, MoreHorizontal, RefreshCw, Search, ShieldCheck, ShieldOff, SlidersHorizontal, UserCheck, UserPlus, Users as UsersIcon, UserX } from "../icons";
import { AnimatePresence, motion } from "motion/react";
import { type FormEvent, type ReactNode, useState } from "react";
import { toast } from "sonner";

import { api, ApiError } from "../api";
import { ROLE_HELP, ROLE_LABEL, useAuth } from "../auth";
import { ErrorNote, relativeTime, shortTime } from "../components/Bits";
import {
  Avatar,
  Card,
  EmptyState,
  generatePassword,
  Modal,
  PageHeader,
  SkeletonRows,
  Spinner,
  StatCard,
  useConfirm,
} from "../components/ui";
import type { ConsoleUser, Tenant, UserRole } from "../types";
import { useLoad } from "../useLoad";

const ROLES: UserRole[] = ["viewer", "operator", "admin"];
const WEEK_MS = 7 * 24 * 3600 * 1000;

function message(reason: unknown, fallback: string): string {
  return reason instanceof ApiError ? reason.message : fallback;
}

function CopyField({ label, value }: { label: string; value: string }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      toast.error("Copying is blocked here; select the text instead.");
    }
  };
  return (
    <div className="copy-field">
      <span className="small muted">{label}</span>
      <div className="copy-row">
        <code>{value}</code>
        <button type="button" className="icon-button unstyled" onClick={() => void copy()}>
          {copied ? <Check size={15} aria-hidden="true" /> : <Copy size={15} aria-hidden="true" />}
          <span className="sr-only">Copy {label.toLowerCase()}</span>
        </button>
      </div>
    </div>
  );
}

function RolePicker({ value, onChange }: { value: UserRole; onChange: (r: UserRole) => void }) {
  return (
    <fieldset className="role-picker">
      <legend>Role</legend>
      {ROLES.map((role) => (
        <label key={role} className={`role-option${value === role ? " selected" : ""}`}>
          <input
            type="radio"
            name="role"
            value={role}
            checked={value === role}
            onChange={() => onChange(role)}
          />
          <strong>{ROLE_LABEL[role]}</strong>
          <span className="small muted">{ROLE_HELP[role]}</span>
        </label>
      ))}
    </fieldset>
  );
}

function TenantPicker({
  value,
  onChange,
  tenants,
}: {
  value: string[] | null;
  onChange: (t: string[] | null) => void;
  tenants: Tenant[];
}) {
  const all = value === null;
  const chosen = new Set(value ?? []);
  const toggle = (id: string) => {
    const next = new Set(chosen);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    onChange([...next].sort());
  };
  return (
    <fieldset className="tenant-picker">
      <legend>Tenant access</legend>
      <label className="switch-row">
        <input type="checkbox" checked={all} onChange={() => onChange(all ? [] : null)} />
        <span>
          <strong>Every tenant</strong>
          <span className="small muted"> — including tenants created later</span>
        </span>
      </label>
      <AnimatePresence initial={false}>
        {!all && (
          <motion.div
            className="tenant-checks"
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
          >
            {tenants.length === 0 && <span className="small muted">No tenants yet.</span>}
            {tenants.map((t) => (
              <label
                key={t.tenant_id}
                className={`tenant-check${chosen.has(t.tenant_id) ? " on" : ""}`}
              >
                <input
                  type="checkbox"
                  checked={chosen.has(t.tenant_id)}
                  onChange={() => toggle(t.tenant_id)}
                />
                <span className="mono">{t.tenant_id}</span>
              </label>
            ))}
          </motion.div>
        )}
      </AnimatePresence>
    </fieldset>
  );
}

function Access({ tenants }: { tenants: string[] | null }) {
  if (tenants === null) return <span className="chip chip-soft">All tenants</span>;
  return (
    <span className="chips">
      {tenants.slice(0, 3).map((t) => (
        <span key={t} className="chip chip-soft mono">
          {t}
        </span>
      ))}
      {tenants.length > 3 && <span className="muted small">+{tenants.length - 3}</span>}
    </span>
  );
}

function InviteUser({
  open,
  onOpenChange,
  tenants,
  onDone,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  tenants: Tenant[];
  onDone: () => void;
}) {
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<UserRole>("viewer");
  const [access, setAccess] = useState<string[] | null>(null);
  const [password, setPassword] = useState(generatePassword);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [created, setCreated] = useState<ConsoleUser | null>(null);

  const close = (o: boolean) => {
    if (!o) {
      setName("");
      setEmail("");
      setRole("viewer");
      setAccess(null);
      setPassword(generatePassword());
      setError(null);
      setCreated(null);
    }
    onOpenChange(o);
  };

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const user = await api.createUser({ name, email, role, tenants: access, password });
      setCreated(user);
      onDone();
    } catch (reason) {
      setError(message(reason, "Could not create the user."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      open={open}
      onOpenChange={close}
      title={created ? "User created" : "Invite a user"}
      description={
        created
          ? "Send these sign-in details to them privately. The password is shown only now."
          : "They sign in with this email and the password below, then change it."
      }
      icon={created ? UserCheck : UserPlus}
      wide
    >
      {created ? (
        <div className="form-grid">
          <CopyField label="Email" value={created.email} />
          <CopyField label="Temporary password" value={password} />
          <div className="dialog-actions">
            <button type="button" className="primary" onClick={() => close(false)}>
              Done
            </button>
          </div>
        </div>
      ) : (
        <form className="form-grid" onSubmit={(e) => void submit(e)}>
          <div className="form-row">
            <label className="field">
              <span>Name</span>
              <input
                value={name}
                onChange={(e) => setName(e.target.value)}
                required
                maxLength={80}
              />
            </label>
            <label className="field">
              <span>Email</span>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                autoComplete="off"
              />
            </label>
          </div>
          <RolePicker value={role} onChange={setRole} />
          <TenantPicker value={access} onChange={setAccess} tenants={tenants} />
          <div className="field">
            <span>Temporary password</span>
            <div className="copy-row">
              <code>{password}</code>
              <button
                type="button"
                className="icon-button unstyled"
                onClick={() => setPassword(generatePassword())}
                aria-label="Make another password"
              >
                <RefreshCw size={15} />
              </button>
            </div>
          </div>
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
              disabled={
                busy || !name.trim() || !email.trim() || (access !== null && access.length === 0)
              }
            >
              {busy ? <Spinner /> : <UserPlus size={15} aria-hidden="true" />} Create user
            </button>
          </div>
        </form>
      )}
    </Modal>
  );
}

function EditAccess({
  user,
  onClose,
  tenants,
  onDone,
}: {
  user: ConsoleUser | null;
  onClose: () => void;
  tenants: Tenant[];
  onDone: (u: ConsoleUser) => void;
}) {
  const [role, setRole] = useState<UserRole>(user?.role ?? "viewer");
  const [access, setAccess] = useState<string[] | null>(user?.tenants ?? null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!user) return;
    setBusy(true);
    setError(null);
    try {
      const updated = await api.updateUser(user.id, { role, tenants: access });
      toast.success(`${updated.name} is now ${ROLE_LABEL[updated.role].toLowerCase()}.`);
      onDone(updated);
      onClose();
    } catch (reason) {
      setError(message(reason, "Could not save the change."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      open={user !== null}
      onOpenChange={(o) => !o && onClose()}
      title={`Role and access for ${user?.name ?? ""}`}
      description="The change applies to their next request; they do not need to sign in again."
      icon={SlidersHorizontal}
      wide
    >
      <form className="form-grid" onSubmit={(e) => void submit(e)}>
        <RolePicker value={role} onChange={setRole} />
        <TenantPicker value={access} onChange={setAccess} tenants={tenants} />
        {error && (
          <p className="error-text" role="alert">
            {error}
          </p>
        )}
        <div className="dialog-actions">
          <button type="button" onClick={onClose}>
            Cancel
          </button>
          <button
            type="submit"
            className="primary"
            disabled={busy || (access !== null && access.length === 0)}
          >
            {busy && <Spinner />} Save
          </button>
        </div>
      </form>
    </Modal>
  );
}

function ResetPassword({ user, onClose }: { user: ConsoleUser | null; onClose: () => void }) {
  const [password, setPassword] = useState(generatePassword);
  const [done, setDone] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const close = () => {
    setPassword(generatePassword());
    setDone(false);
    setError(null);
    onClose();
  };

  async function reset() {
    if (!user) return;
    setBusy(true);
    setError(null);
    try {
      await api.resetPassword(user.id, password);
      setDone(true);
    } catch (reason) {
      setError(message(reason, "Could not reset the password."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      open={user !== null}
      onOpenChange={(o) => !o && close()}
      title={done ? "Password reset" : `Reset the password for ${user?.name ?? ""}?`}
      description={
        done
          ? "Every session they had has ended. Send them the new password privately."
          : "Their current password stops working and every browser they are signed in on is signed out."
      }
      icon={KeyRound}
    >
      <div className="form-grid">
        <CopyField label="New password" value={password} />
        {error && (
          <p className="error-text" role="alert">
            {error}
          </p>
        )}
        <div className="dialog-actions">
          {done ? (
            <button type="button" className="primary" onClick={close}>
              Done
            </button>
          ) : (
            <>
              <button type="button" onClick={close}>
                Cancel
              </button>
              <button
                type="button"
                className="danger-solid"
                onClick={() => void reset()}
                disabled={busy}
              >
                {busy && <Spinner />} Reset password
              </button>
            </>
          )}
        </div>
      </div>
    </Modal>
  );
}

function RowMenu({ children }: { children: ReactNode }) {
  return (
    <Dropdown.Root>
      <Dropdown.Trigger asChild>
        <button type="button" className="icon-button unstyled" aria-label="More actions">
          <MoreHorizontal size={16} />
        </button>
      </Dropdown.Trigger>
      <Dropdown.Portal>
        <Dropdown.Content className="menu" align="end" sideOffset={4}>
          {children}
        </Dropdown.Content>
      </Dropdown.Portal>
    </Dropdown.Root>
  );
}

export function Users() {
  const { me, canManageUsers } = useAuth();
  const users = useLoad(
    () => (canManageUsers ? api.users() : Promise.resolve([])),
    [canManageUsers],
  );
  const tenants = useLoad(() => api.tenants(), []);
  const [query, setQuery] = useState("");
  const [inviting, setInviting] = useState(false);
  const [editing, setEditing] = useState<ConsoleUser | null>(null);
  const [resetting, setResetting] = useState<ConsoleUser | null>(null);
  const [ask, dialog] = useConfirm();

  if (!canManageUsers) {
    return (
      <div className="page">
        <PageHeader title="Users" />
        <EmptyState icon={ShieldOff} title="Managing users needs an admin with every tenant.">
          Ask an administrator to change your role or access.
        </EmptyState>
      </div>
    );
  }

  const list = users.data ?? [];
  const now = Date.now();
  const shown = list.filter((u) =>
    `${u.name} ${u.email} ${u.role}`.toLowerCase().includes(query.trim().toLowerCase()),
  );

  const setDisabled = (user: ConsoleUser, disabled: boolean) =>
    ask({
      title: disabled ? `Disable ${user.name}?` : `Enable ${user.name}?`,
      description: disabled
        ? "They are signed out at once and cannot sign in until enabled again. Their history stays in the audit trail."
        : "They can sign in again with their current password.",
      confirmLabel: disabled ? "Disable user" : "Enable user",
      tone: disabled ? "danger" : "default",
      icon: disabled ? UserX : UserCheck,
      run: async () => {
        try {
          await api.updateUser(user.id, { disabled });
          toast.success(disabled ? `${user.name} is disabled.` : `${user.name} is enabled.`);
          users.reload();
        } catch (reason) {
          toast.error(message(reason, "Could not change the user."));
        }
      },
    });

  const endSessions = (user: ConsoleUser) =>
    ask({
      title: `Sign ${user.name} out everywhere?`,
      description: "Every browser signed in as them is signed out. They can sign in again.",
      confirmLabel: "Sign out everywhere",
      tone: "danger",
      icon: MonitorSmartphone,
      run: async () => {
        try {
          await api.endSessions(user.id);
          toast.success(`${user.name} has been signed out everywhere.`);
        } catch (reason) {
          toast.error(message(reason, "Could not end their sessions."));
        }
      },
    });

  return (
    <div className="page">
      <PageHeader
        eyebrow={
          <>
            <ShieldCheck size={14} aria-hidden="true" /> Administration
          </>
        }
        title="Users"
        description="People who sign in to this console, their role, and the tenants they can see. Users are disabled, never deleted, so the audit trail always names someone."
        actions={
          <>
            <label className="field search-field">
              <span className="sr-only">Filter users</span>
              <span className="input-icon">
                <Search size={15} aria-hidden="true" />
                <input
                  type="search"
                  placeholder="Filter users…"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                />
              </span>
            </label>
            <button type="button" className="primary" onClick={() => setInviting(true)}>
              <UserPlus size={15} aria-hidden="true" /> Invite user
            </button>
          </>
        }
      />

      <div className="stats" style={{ marginBottom: 22 }}>
        <StatCard
          icon={UsersIcon}
          label="Users"
          value={users.data ? list.length : "–"}
          tone="accent"
        />
        <StatCard
          icon={ShieldCheck}
          label="Admins"
          value={users.data ? list.filter((u) => u.role === "admin" && !u.disabled).length : "–"}
          delay={0.04}
        />
        <StatCard
          icon={UserCheck}
          label="Signed in this week"
          value={
            users.data
              ? list.filter((u) => u.last_login_at && now - u.last_login_at < WEEK_MS).length
              : "–"
          }
          tone="good"
          delay={0.08}
        />
        <StatCard
          icon={UserX}
          label="Disabled"
          value={users.data ? list.filter((u) => u.disabled).length : "–"}
          tone={list.some((u) => u.disabled) ? "warn" : "neutral"}
          delay={0.12}
        />
      </div>

      <Card className="card-flush">
        <ErrorNote error={users.error} />
        {users.loading && !users.data && <SkeletonRows rows={4} label="Loading users" />}
        {users.data && list.length === 0 && (
          <EmptyState icon={UserPlus} title="No users yet">
            Invite the first person. Until then the console is reached with the server's key.
          </EmptyState>
        )}
        {users.data && list.length > 0 && shown.length === 0 && (
          <EmptyState icon={Search} title="No user matches that filter" />
        )}
        {shown.length > 0 && (
          <div className="table-wrap">
            <table className="stack">
              <thead>
                <tr>
                  <th scope="col">User</th>
                  <th scope="col">Role</th>
                  <th scope="col">Access</th>
                  <th scope="col">Status</th>
                  <th scope="col">Last sign-in</th>
                  <th scope="col">
                    <span className="sr-only">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                <AnimatePresence initial={false}>
                  {shown.map((user, index) => {
                    const self = me?.kind === "user" && me.id === user.id;
                    return (
                      <motion.tr
                        key={user.id}
                        layout
                        initial={{ opacity: 0, y: 6 }}
                        animate={{ opacity: 1, y: 0 }}
                        transition={{ delay: Math.min(index, 10) * 0.03 }}
                        className={user.disabled ? "row-muted" : undefined}
                      >
                        <td data-label="User">
                          <div className="user-cell">
                            <Avatar name={user.name} seed={user.id} size={32} />
                            <div>
                              <div className="user-name">
                                {user.name} {self && <span className="chip chip-soft">you</span>}
                              </div>
                              <div className="muted small">{user.email}</div>
                            </div>
                          </div>
                        </td>
                        <td data-label="Role">
                          <span className={`role-badge role-${user.role}`}>
                            {ROLE_LABEL[user.role]}
                          </span>
                        </td>
                        <td data-label="Access">
                          <Access tenants={user.tenants} />
                        </td>
                        <td data-label="Status">
                          <span className={`status-dot ${user.disabled ? "off" : "on"}`}>
                            {user.disabled ? "Disabled" : "Active"}
                          </span>
                        </td>
                        <td
                          data-label="Last sign-in"
                          className="muted small"
                          title={user.last_login_at ? shortTime(user.last_login_at) : undefined}
                        >
                          {user.last_login_at ? relativeTime(user.last_login_at) : "never"}
                        </td>
                        <td className="cell-actions">
                          <RowMenu>
                            <Dropdown.Item
                              className="menu-item"
                              disabled={self}
                              onSelect={() => setEditing(user)}
                            >
                              <SlidersHorizontal size={15} aria-hidden="true" /> Role and access
                            </Dropdown.Item>
                            <Dropdown.Item
                              className="menu-item"
                              onSelect={() => setResetting(user)}
                            >
                              <KeyRound size={15} aria-hidden="true" /> Reset password
                            </Dropdown.Item>
                            <Dropdown.Item className="menu-item" onSelect={() => endSessions(user)}>
                              <MonitorSmartphone size={15} aria-hidden="true" /> Sign out everywhere
                            </Dropdown.Item>
                            <Dropdown.Separator className="menu-separator" />
                            <Dropdown.Item
                              className="menu-item danger-item"
                              disabled={self}
                              onSelect={() => setDisabled(user, !user.disabled)}
                            >
                              {user.disabled ? (
                                <UserCheck size={15} aria-hidden="true" />
                              ) : (
                                <UserX size={15} aria-hidden="true" />
                              )}
                              {user.disabled ? "Enable" : "Disable"}
                            </Dropdown.Item>
                          </RowMenu>
                        </td>
                      </motion.tr>
                    );
                  })}
                </AnimatePresence>
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <InviteUser
        open={inviting}
        onOpenChange={setInviting}
        tenants={tenants.data ?? []}
        onDone={users.reload}
      />
      {editing && (
        <EditAccess
          key={editing.id}
          user={editing}
          onClose={() => setEditing(null)}
          tenants={tenants.data ?? []}
          onDone={() => users.reload()}
        />
      )}
      <ResetPassword user={resetting} onClose={() => setResetting(null)} />
      {dialog}
    </div>
  );
}
