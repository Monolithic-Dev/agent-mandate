// A tenant's alerts: webhooks that tell the owner, in Slack or any HTTPS endpoint, that an
// agent's action is waiting, with a link to approve it. Admins only.

import { BellRing, CheckCircle2, ChevronDown, CircleX, Hash, Pause, Play, Plus, Send, ShieldCheck, Trash2, Webhook } from "../icons";
import { AnimatePresence, motion } from "motion/react";
import { type FormEvent, useState } from "react";
import { toast } from "sonner";

import { api, ApiError } from "../api";
import type { DeliveryInfo, WebhookInfo } from "../types";
import { useLoad } from "../useLoad";
import { ErrorNote, relativeTime, shortTime } from "./Bits";
import { EmptyState, Modal, SkeletonRows, Spinner, useConfirm } from "./ui";

const KINDS = {
  slack: {
    label: "Slack",
    icon: Hash,
    help: "In Slack, add an Incoming Webhook to the owner's channel and paste its URL. Each held action arrives as a message with a Review and approve button.",
    placeholder: "https://hooks.slack.com/services/…",
  },
  json: {
    label: "JSON (any HTTPS endpoint)",
    icon: Webhook,
    help: "Each held action is POSTed as JSON and signed: X-Mandate-Signature is HMAC-SHA256 over “timestamp.body” with the secret shown once after you add it.",
    placeholder: "https://example.com/mandate-hook",
  },
} as const;

function message(reason: unknown, fallback: string): string {
  return reason instanceof ApiError ? reason.message : fallback;
}

function AddWebhook({
  tid,
  open,
  onOpenChange,
  onAdded,
}: {
  tid: string;
  open: boolean;
  onOpenChange: (o: boolean) => void;
  onAdded: () => void;
}) {
  const [kind, setKind] = useState<"slack" | "json">("slack");
  const [name, setName] = useState("Owner's channel");
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [created, setCreated] = useState<WebhookInfo | null>(null);

  const close = (o: boolean) => {
    if (!o) {
      setUrl("");
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
      const hook = await api.createWebhook(tid, { name, url, kind });
      onAdded();
      if (hook.kind === "json") setCreated(hook);
      else {
        toast.success("Webhook added. Send a test to check it.");
        close(false);
      }
    } catch (reason) {
      setError(message(reason, "Could not add the webhook."));
    } finally {
      setBusy(false);
    }
  }

  const Kind = KINDS[kind];
  return (
    <Modal
      open={open}
      onOpenChange={close}
      title={created ? "Save the signing secret" : "Add an alert"}
      description={
        created
          ? "Your endpoint checks each request with this secret. It is shown only now."
          : "Tell the owner the moment an agent's action waits for them."
      }
      icon={created ? ShieldCheck : BellRing}
      wide
    >
      {created?.secret ? (
        <div className="form-grid">
          <div className="copy-field">
            <span className="small muted">Signing secret</span>
            <div className="copy-row">
              <code>{created.secret}</code>
            </div>
          </div>
          <pre className="code-sample">{`expected = "v1=" + hex(hmac_sha256(secret,
    request.headers["X-Mandate-Timestamp"] + "." + raw_body))
accept if constant_time_equals(expected,
    request.headers["X-Mandate-Signature"])`}</pre>
          <div className="dialog-actions">
            <button type="button" className="primary" onClick={() => close(false)}>
              Done
            </button>
          </div>
        </div>
      ) : (
        <form className="form-grid" onSubmit={(e) => void submit(e)}>
          <fieldset className="role-picker kind-picker">
            <legend>Where to</legend>
            {(Object.keys(KINDS) as (keyof typeof KINDS)[]).map((value) => {
              const Icon = KINDS[value].icon;
              return (
                <label key={value} className={`role-option${kind === value ? " selected" : ""}`}>
                  <input
                    type="radio"
                    name="kind"
                    value={value}
                    checked={kind === value}
                    onChange={() => setKind(value)}
                  />
                  <strong>
                    <Icon size={14} aria-hidden="true" /> {KINDS[value].label}
                  </strong>
                </label>
              );
            })}
          </fieldset>
          <p className="muted small" style={{ margin: 0 }}>
            {Kind.help}
          </p>
          <label className="field">
            <span>Name</span>
            <input value={name} onChange={(e) => setName(e.target.value)} required maxLength={80} />
          </label>
          <label className="field">
            <span>URL</span>
            <input
              type="url"
              className="mono"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder={Kind.placeholder}
              required
              autoComplete="off"
            />
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
            <button type="submit" className="primary" disabled={busy || !url.trim() || !name.trim()}>
              {busy ? <Spinner /> : <Plus size={15} aria-hidden="true" />} Add alert
            </button>
          </div>
        </form>
      )}
    </Modal>
  );
}

function Deliveries({ tid, hook }: { tid: string; hook: WebhookInfo }) {
  const log = useLoad(() => api.deliveries(tid, hook.id), [tid, hook.id, hook.last_delivery_at]);
  if (log.loading && !log.data) return <SkeletonRows rows={2} label="Loading deliveries" />;
  if (log.data?.length === 0) return <p className="muted small hook-empty-log">Nothing sent yet.</p>;
  return (
    <div className="table-wrap">
      <table className="delivery-table">
        <thead>
          <tr>
            <th scope="col">When</th>
            <th scope="col">What</th>
            <th scope="col">Result</th>
            <th scope="col">Tries</th>
            <th scope="col">Time</th>
          </tr>
        </thead>
        <tbody>
          {(log.data ?? []).map((d: DeliveryInfo) => (
            <tr key={d.id}>
              <td className="muted small" title={shortTime(d.at)}>
                {relativeTime(d.at)}
              </td>
              <td className="small">
                {d.event === "webhook.test" ? "Test ping" : "Approval requested"}
                {d.subject && <span className="mono muted"> {d.subject}</span>}
              </td>
              <td>
                <span className={`delivery-result ${d.ok ? "ok" : "bad"}`}>
                  {d.ok ? <CheckCircle2 size={13} aria-hidden="true" /> : <CircleX size={13} aria-hidden="true" />}
                  {d.ok ? `Delivered (${d.status})` : (d.error ?? "Failed")}
                </span>
              </td>
              <td className="small">{d.attempts}</td>
              <td className="small muted">{Math.round(d.duration_ms)} ms</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function HookCard({ tid, hook, onChange }: { tid: string; hook: WebhookInfo; onChange: () => void }) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [ask, dialog] = useConfirm();
  const Icon = KINDS[hook.kind].icon;
  const health =
    hook.last_ok === null ? "new" : hook.last_ok ? "ok" : hook.failures > 1 ? "bad" : "warn";

  async function run(label: string, task: () => Promise<unknown>) {
    setBusy(label);
    try {
      await task();
      onChange();
    } catch (reason) {
      toast.error(message(reason, "That did not work."));
    } finally {
      setBusy(null);
    }
  }

  const test = () =>
    run("test", async () => {
      const sent = await api.testWebhook(tid, hook.id);
      if (sent.ok) toast.success(`Test delivered to ${hook.name} in ${Math.round(sent.duration_ms)} ms.`);
      else toast.error(`Test failed: ${sent.error ?? "no answer"}.`);
      setOpen(true);
    });

  return (
    <motion.li layout className={`hook-card health-${hook.enabled ? health : "off"}`}>
      <div className="hook-main">
        <span className="hook-icon" aria-hidden="true">
          <Icon size={18} />
        </span>
        <div className="hook-text">
          <strong>{hook.name}</strong>
          <span className="mono small muted">{hook.url}</span>
          <span className="small muted">
            {!hook.enabled
              ? "Paused"
              : hook.last_delivery_at
                ? `${hook.last_ok ? "Last delivered" : "Last attempt failed"} ${relativeTime(hook.last_delivery_at)}${
                    hook.failures > 1 ? ` · ${hook.failures} failures in a row` : ""
                  }`
                : "Waiting for the first held action"}
          </span>
        </div>
        <div className="hook-actions">
          <button type="button" className="sm" onClick={() => void test()} disabled={busy !== null}>
            {busy === "test" ? <Spinner /> : <Send size={14} aria-hidden="true" />} Send test
          </button>
          <button
            type="button"
            className="sm"
            onClick={() =>
              void run("toggle", () => api.updateWebhook(tid, hook.id, { enabled: !hook.enabled }))
            }
            disabled={busy !== null}
          >
            {hook.enabled ? <Pause size={14} aria-hidden="true" /> : <Play size={14} aria-hidden="true" />}
            {hook.enabled ? "Pause" : "Resume"}
          </button>
          <button
            type="button"
            className="sm danger"
            aria-label={`Remove ${hook.name}`}
            disabled={busy !== null}
            onClick={() =>
              ask({
                title: `Remove ${hook.name}?`,
                description: "It stops sending at once, and its delivery log is deleted.",
                confirmLabel: "Remove alert",
                tone: "danger",
                icon: Trash2,
                run: () => run("delete", () => api.deleteWebhook(tid, hook.id)),
              })
            }
          >
            <Trash2 size={14} aria-hidden="true" />
          </button>
          <button
            type="button"
            className="icon-button unstyled"
            aria-expanded={open}
            aria-label="Delivery log"
            onClick={() => setOpen((o) => !o)}
          >
            <ChevronDown size={16} className={`chev${open ? " open" : ""}`} />
          </button>
        </div>
      </div>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            className="hook-log"
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
          >
            <Deliveries tid={tid} hook={hook} />
          </motion.div>
        )}
      </AnimatePresence>
      {dialog}
    </motion.li>
  );
}

export function WebhooksPanel({ tid }: { tid: string }) {
  const hooks = useLoad(() => api.webhooks(tid), [tid]);
  const [adding, setAdding] = useState(false);
  return (
    <div className="hooks">
      <div className="hooks-head">
        <p className="muted small" style={{ margin: 0 }}>
          When an agent's action is held for approval, each alert below gets a message with a
          one-time link the owner can approve from, on any device.
        </p>
        <button type="button" className="primary" onClick={() => setAdding(true)}>
          <Plus size={15} aria-hidden="true" /> Add alert
        </button>
      </div>
      <ErrorNote error={hooks.error} />
      {hooks.loading && !hooks.data && <SkeletonRows rows={2} label="Loading alerts" />}
      {hooks.data?.length === 0 && (
        <EmptyState icon={BellRing} title="No alerts yet">
          Add Slack or a webhook so the owner hears about held actions without watching the
          console.
        </EmptyState>
      )}
      <ul className="hook-list">
        <AnimatePresence initial={false}>
          {(hooks.data ?? []).map((hook) => (
            <HookCard key={hook.id} tid={tid} hook={hook} onChange={hooks.reload} />
          ))}
        </AnimatePresence>
      </ul>
      <AddWebhook tid={tid} open={adding} onOpenChange={setAdding} onAdded={hooks.reload} />
    </div>
  );
}
