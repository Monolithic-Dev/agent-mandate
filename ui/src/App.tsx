import * as Tooltip from "@radix-ui/react-tooltip";
import { MotionConfig } from "motion/react";
import { lazy, Suspense } from "react";
import { Route, Routes, useLocation } from "react-router-dom";
import { Toaster } from "sonner";

import { AuthProvider, useAuth } from "./auth";
import { AppShell } from "./components/AppShell";
import { SkeletonRows, Spinner } from "./components/ui";
import { Approve } from "./pages/Approve";
import { Demo } from "./pages/Demo";
import { Eval } from "./pages/Eval";
import { NotFound } from "./pages/NotFound";
import { SignIn } from "./pages/SignIn";
import { Tenants } from "./pages/Tenants";

// Pages that draw the graph load Cytoscape on demand, so the demo page opens fast.
const Tenant = lazy(() => import("./pages/Tenant").then((m) => ({ default: m.Tenant })));
const DecisionPage = lazy(() =>
  import("./pages/Decision").then((m) => ({ default: m.DecisionPage })),
);
const InstructionPage = lazy(() =>
  import("./pages/Instruction").then((m) => ({ default: m.InstructionPage })),
);
const Studio = lazy(() => import("./pages/Studio").then((m) => ({ default: m.Studio })));
const Users = lazy(() => import("./pages/Users").then((m) => ({ default: m.Users })));
const Audit = lazy(() => import("./pages/Audit").then((m) => ({ default: m.Audit })));

function Console() {
  const location = useLocation();
  return (
    <AppShell>
      <Suspense
        fallback={
          <div className="page">
            <SkeletonRows rows={6} label="Loading the page" />
          </div>
        }
      >
        {/* The location is passed so a page leaving the screen keeps its own content. */}
        <Routes location={location}>
          <Route path="/" element={<Demo />} />
          <Route path="/tenants" element={<Tenants />} />
          <Route path="/tenants/:tid" element={<Tenant />} />
          <Route path="/tenants/:tid/decisions/:did" element={<DecisionPage />} />
          <Route path="/tenants/:tid/instructions/:iid" element={<InstructionPage />} />
          <Route path="/tenants/:tid/studio" element={<Studio />} />
          <Route path="/eval" element={<Eval />} />
          <Route path="/admin/users" element={<Users />} />
          <Route path="/admin/audit" element={<Audit />} />
          <Route path="*" element={<NotFound />} />
        </Routes>
      </Suspense>
    </AppShell>
  );
}

/** The console needs someone signed in (or a console key on the server). */
function Gate() {
  const { status, retry } = useAuth();
  if (status === "loading") {
    return (
      <div className="boot" aria-busy="true">
        <Spinner size={22} />
        <span className="sr-only">Starting the console…</span>
      </div>
    );
  }
  if (status === "unreachable") {
    return (
      <div className="boot">
        <div className="boot-card">
          <h1>The console cannot reach the API</h1>
          <p className="muted">Check that the API is running, then try again.</p>
          <button type="button" className="primary" onClick={retry}>
            Try again
          </button>
        </div>
      </div>
    );
  }
  if (status === "signed-out") return <SignIn />;
  return <Console />;
}

export function App() {
  return (
    <MotionConfig reducedMotion="user">
      <Tooltip.Provider>
        <Routes>
          {/* An approval link is for the owner, not the operator: no console around it. */}
          <Route path="/approve" element={<Approve />} />
          <Route
            path="*"
            element={
              <AuthProvider>
                <Gate />
              </AuthProvider>
            }
          />
        </Routes>
        <Toaster position="bottom-right" closeButton richColors theme="system" />
      </Tooltip.Provider>
    </MotionConfig>
  );
}
