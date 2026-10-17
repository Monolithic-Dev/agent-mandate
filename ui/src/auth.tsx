// Who the console is signed in as, and what they may do.
//
// On load the console asks /v1/auth/me. When a console key is injected server-side (local
// use), that answers at once and there is nothing to sign in to. Otherwise the person signs
// in; the session lives in an HttpOnly cookie this code never sees. Any 401 from the API
// afterwards (expired, signed out elsewhere, disabled) brings the sign-in screen back.

import {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";

import { api, ApiError, SIGNED_OUT_EVENT } from "./api";
import type { Me, UserRole } from "./types";

const RANK: Record<UserRole, number> = { viewer: 1, operator: 2, admin: 3 };

export type AuthStatus = "loading" | "signed-in" | "signed-out" | "unreachable";

export interface Auth {
  status: AuthStatus;
  me: Me | null;
  /** Why the person is looking at the sign-in screen, when it is not the first visit. */
  notice: string | null;
  signIn: (email: string, password: string) => Promise<Me>;
  signOut: () => Promise<void>;
  retry: () => void;
  setMe: (me: Me) => void;
  /** True if the signed-in role is at least ``role``. */
  can: (role: UserRole) => boolean;
  /** Managing users needs an admin with every tenant. */
  canManageUsers: boolean;
}

const AuthContext = createContext<Auth | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<AuthStatus>("loading");
  const [me, setMeState] = useState<Me | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let live = true;
    api
      .me()
      .then((who) => {
        if (!live) return;
        setMeState(who);
        setStatus("signed-in");
      })
      .catch((reason: unknown) => {
        if (!live) return;
        const unauthorised = reason instanceof ApiError && reason.status === 401;
        setStatus(unauthorised ? "signed-out" : "unreachable");
      });
    return () => {
      live = false;
    };
  }, [attempt]);

  useEffect(() => {
    const ended = () => {
      setStatus((current) => {
        if (current === "signed-in") setNotice("Your session ended. Sign in again to continue.");
        return current === "loading" ? current : "signed-out";
      });
      setMeState(null);
    };
    window.addEventListener(SIGNED_OUT_EVENT, ended);
    return () => window.removeEventListener(SIGNED_OUT_EVENT, ended);
  }, []);

  const signIn = useCallback(async (email: string, password: string) => {
    const who = await api.login(email, password);
    setMeState(who);
    setNotice(null);
    setStatus("signed-in");
    return who;
  }, []);

  const signOut = useCallback(async () => {
    try {
      await api.logout();
    } finally {
      setMeState(null);
      setNotice("You signed out.");
      setStatus("signed-out");
    }
  }, []);

  const value = useMemo<Auth>(() => {
    const can = (role: UserRole) => !!me && RANK[me.role] >= RANK[role];
    return {
      status,
      me,
      notice,
      signIn,
      signOut,
      retry: () => {
        setStatus("loading");
        setAttempt((n) => n + 1);
      },
      setMe: setMeState,
      can,
      canManageUsers: can("admin") && me?.tenants === null,
    };
  }, [status, me, notice, signIn, signOut]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): Auth {
  const auth = useContext(AuthContext);
  if (!auth) throw new Error("useAuth needs an <AuthProvider>");
  return auth;
}

/** For component tests and pages rendered outside the provider: an admin console key. */
export function TestAuth({ me, children }: { me?: Partial<Me>; children: ReactNode }) {
  const who: Me = {
    kind: "key",
    id: "admin",
    name: "API key admin",
    email: null,
    role: "admin",
    tenants: null,
    ...me,
  };
  const value: Auth = {
    status: "signed-in",
    me: who,
    notice: null,
    signIn: async () => who,
    signOut: async () => undefined,
    retry: () => undefined,
    setMe: () => undefined,
    can: (role) => RANK[who.role] >= RANK[role],
    canManageUsers: who.role === "admin" && who.tenants === null,
  };
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export const ROLE_LABEL: Record<UserRole, string> = {
  viewer: "Viewer",
  operator: "Operator",
  admin: "Admin",
};

export const ROLE_HELP: Record<UserRole, string> = {
  viewer: "Sees everything in their tenants; changes nothing.",
  operator: "A viewer who can also run agents' tool calls and checks.",
  admin: "Says and confirms rules, approves actions, manages tenants.",
};
