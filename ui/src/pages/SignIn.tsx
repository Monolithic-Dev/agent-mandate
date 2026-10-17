// The sign-in screen: the product on the left, the form on the right (stacked on a phone).

import { BrandMark } from "../components/BrandMark";
import { AlertCircle, ArrowRight, Eye, EyeOff, GitBranch, Info, Lock, Mail, ShieldCheck, Undo2 } from "../icons";
import { motion, useAnimationControls } from "motion/react";
import { type FormEvent, type KeyboardEvent, useId, useState } from "react";
import { toast } from "sonner";

import { ApiError } from "../api";
import { useAuth } from "../auth";
import { Spinner } from "../components/ui";

// A small authority graph that draws itself: owner, rule, agent, action.
const NODES = [
  { x: 60, y: 70, r: 15, label: "Owner", tone: "good" },
  { x: 200, y: 40, r: 12, label: "Rule", tone: "accent" },
  { x: 205, y: 150, r: 12, label: "Rule", tone: "accent" },
  { x: 340, y: 95, r: 15, label: "Agent", tone: "info" },
  { x: 300, y: 205, r: 10, label: "Email", tone: "muted" },
  { x: 120, y: 200, r: 10, label: "Email", tone: "bad" },
];
const EDGES: [number, number][] = [
  [0, 1],
  [0, 2],
  [1, 3],
  [2, 3],
  [3, 4],
];

function AuthorityMotif() {
  return (
    <svg viewBox="0 0 400 250" className="signin-motif" aria-hidden="true">
      {EDGES.map(([a, b], index) => (
        <motion.line
          key={`${a}-${b}`}
          x1={NODES[a].x}
          y1={NODES[a].y}
          x2={NODES[b].x}
          y2={NODES[b].y}
          className="motif-edge"
          initial={{ pathLength: 0, opacity: 0 }}
          animate={{ pathLength: 1, opacity: 1 }}
          transition={{ duration: 0.7, delay: 0.3 + index * 0.18, ease: "easeOut" }}
        />
      ))}
      {/* Untrusted content: a dashed tie that never carries authority. */}
      <motion.line
        x1={NODES[5].x}
        y1={NODES[5].y}
        x2={NODES[3].x}
        y2={NODES[3].y}
        className="motif-edge motif-untrusted"
        initial={{ opacity: 0 }}
        animate={{ opacity: [0, 0.9, 0.35] }}
        transition={{ duration: 1.6, delay: 1.4 }}
      />
      {NODES.map((node, index) => (
        <motion.g
          key={`${node.label}-${index}`}
          initial={{ scale: 0, opacity: 0 }}
          animate={{ scale: 1, opacity: 1 }}
          transition={{ type: "spring", stiffness: 260, damping: 18, delay: 0.1 + index * 0.12 }}
          style={{ transformOrigin: `${node.x}px ${node.y}px` }}
        >
          <circle cx={node.x} cy={node.y} r={node.r + 7} className={`motif-halo t-${node.tone}`} />
          <circle cx={node.x} cy={node.y} r={node.r} className={`motif-node t-${node.tone}`} />
          <text x={node.x} y={node.y + node.r + 18} className="motif-label">
            {node.label}
          </text>
        </motion.g>
      ))}
      <motion.circle
        r={4}
        className="motif-pulse"
        initial={{ cx: NODES[0].x, cy: NODES[0].y, opacity: 0 }}
        animate={{
          cx: [NODES[0].x, NODES[1].x, NODES[3].x],
          cy: [NODES[0].y, NODES[1].y, NODES[3].y],
          opacity: [0, 1, 0],
        }}
        transition={{ duration: 2.4, delay: 2, repeat: Infinity, repeatDelay: 1.2 }}
      />
    </svg>
  );
}

const POINTS = [
  { icon: ShieldCheck, text: "Only the owner's own words grant authority, never content an agent reads." },
  { icon: GitBranch, text: "Every allow, hold and deny traces back to who said what, and when." },
  { icon: Undo2, text: "Find what a bad rule touched, replay without it, and switch it off." },
];

export function SignIn() {
  const { signIn, notice } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [show, setShow] = useState(false);
  const [caps, setCaps] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const shake = useAnimationControls();
  const errorId = useId();
  const passwordId = useId();

  const onKey = (event: KeyboardEvent<HTMLInputElement>) =>
    setCaps(event.getModifierState?.("CapsLock") ?? false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const me = await signIn(email.trim(), password);
      toast.success(`Welcome back, ${me.name.split(" ")[0]}.`);
    } catch (reason) {
      const message =
        reason instanceof ApiError
          ? reason.status === 429
            ? "Too many attempts. Wait a minute, then try again."
            : reason.status === 401
              ? "That email and password do not match an active account."
              : reason.message
          : "The console cannot reach the API. Check that it is running.";
      setError(message);
      setPassword("");
      void shake.start({ x: [0, -10, 9, -6, 4, 0], transition: { duration: 0.42 } });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="signin">
      <aside className="signin-brand">
        <div className="signin-brand-inner">
          <div className="brand signin-logo">
            <BrandMark />
            <span className="brand-name">Agent Mandate</span>
          </div>
          <motion.h2
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5 }}
          >
            Authority for AI agents, kept in a graph.
          </motion.h2>
          <AuthorityMotif />
          <ul className="signin-points">
            {POINTS.map(({ icon: Icon, text }, index) => (
              <motion.li
                key={text}
                initial={{ opacity: 0, x: -8 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ delay: 0.6 + index * 0.12 }}
              >
                <Icon size={16} aria-hidden="true" />
                <span>{text}</span>
              </motion.li>
            ))}
          </ul>
        </div>
      </aside>

      <main className="signin-main">
        <motion.div
          className="signin-card"
          initial={{ opacity: 0, y: 14 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4 }}
        >
          <motion.div animate={shake}>
            <h1>Sign in to the console</h1>
            <p className="muted">Use the account your administrator created for you.</p>

            {notice && !error && (
              <div className="callout callout-info" role="status">
                <Info size={16} aria-hidden="true" />
                <span>{notice}</span>
              </div>
            )}
            {error && (
              <div className="callout callout-bad" role="alert" id={errorId}>
                <AlertCircle size={16} aria-hidden="true" />
                <span>{error}</span>
              </div>
            )}

            <form onSubmit={(e) => void submit(e)} className="signin-form" noValidate>
              <label className="field">
                <span>Email</span>
                <span className="input-icon">
                  <Mail size={15} aria-hidden="true" />
                  <input
                    type="email"
                    autoComplete="username"
                    required
                    autoFocus
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    aria-describedby={error ? errorId : undefined}
                    placeholder="you@company.com"
                  />
                </span>
              </label>
              {/* Not a wrapping <label>: the show button must not become part of its name. */}
              <div className="field">
                <label htmlFor={passwordId}>Password</label>
                <span className="input-icon">
                  <Lock size={15} aria-hidden="true" />
                  <input
                    id={passwordId}
                    type={show ? "text" : "password"}
                    autoComplete="current-password"
                    required
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    onKeyUp={onKey}
                    onKeyDown={onKey}
                    aria-describedby={error ? errorId : undefined}
                  />
                  <button
                    type="button"
                    className="input-action unstyled"
                    onClick={() => setShow((s) => !s)}
                    aria-label={show ? "Hide the password" : "Show the password"}
                    aria-pressed={show}
                  >
                    {show ? <EyeOff size={15} /> : <Eye size={15} />}
                  </button>
                </span>
                {caps && (
                  <span className="small warn-text" role="status">
                    Caps Lock is on.
                  </span>
                )}
              </div>
              <button
                type="submit"
                className="primary signin-submit"
                disabled={busy || !email.trim() || !password}
              >
                {busy ? <Spinner /> : null}
                {busy ? "Signing in…" : "Sign in"}
                {!busy && <ArrowRight size={15} aria-hidden="true" />}
              </button>
            </form>
            <p className="small muted signin-foot">
              Forgot your password? An administrator can reset it from Users, or on the server
              with <code>python -m mandate.users reset-password</code>.
            </p>
          </motion.div>
        </motion.div>
      </main>
    </div>
  );
}
