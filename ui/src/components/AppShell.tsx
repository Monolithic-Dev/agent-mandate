// The frame around every console page: a collapsible sidebar, a top bar with breadcrumbs,
// the command palette and the theme menu, and an animated page transition. On a narrow
// screen the sidebar gives way to a menu button that opens the same contents in a drawer.

import { BrandMark } from "./BrandMark";
import * as Dialog from "@radix-ui/react-dialog";
import * as Dropdown from "@radix-ui/react-dropdown-menu";
import { BarChart3, Building2, Check, ChevronRight, FileClock, Menu, Monitor, Moon, PanelLeftClose, PanelLeftOpen, PlayCircle, Search, Sun, Users, X } from "../icons";
import { AnimatePresence, motion } from "motion/react";
import { type ReactNode, useEffect, useState } from "react";
import { Link, NavLink, useLocation } from "react-router-dom";

import { useAuth } from "../auth";
import { type ThemeChoice, useTheme } from "../theme";
import { AccountMenu } from "./AccountMenu";
import { CommandPalette } from "./CommandPalette";
import { ease, Kbd, Tip } from "./ui";

const NAV = [
  { to: "/", label: "Demo", icon: PlayCircle, end: true },
  { to: "/tenants", label: "Tenants", icon: Building2, end: false },
  { to: "/eval", label: "Evaluation", icon: BarChart3, end: false },
];

const COLLAPSE_KEY = "mandate.sidebar";

function readCollapsed(): boolean {
  try {
    return window.localStorage.getItem(COLLAPSE_KEY) === "collapsed";
  } catch {
    return false;
  }
}

/** Breadcrumbs from the path: Tenants / acme / Decision. */
function crumbsFor(path: string): { label: string; to?: string }[] {
  const parts = path.split("/").filter(Boolean).map(decodeURIComponent);
  if (parts.length === 0) return [{ label: "Demo" }];
  if (parts[0] === "eval") return [{ label: "Evaluation" }];
  if (parts[0] === "admin" && parts[1] === "users") return [{ label: "Users" }];
  if (parts[0] === "admin" && parts[1] === "audit") return [{ label: "Audit log" }];
  if (parts[0] !== "tenants") return [{ label: "Not found" }];
  const crumbs: { label: string; to?: string }[] = [{ label: "Tenants", to: "/tenants" }];
  if (parts[1]) crumbs.push({ label: parts[1], to: `/tenants/${parts[1]}` });
  if (parts[2] === "decisions") crumbs.push({ label: "Decision" });
  if (parts[2] === "instructions") crumbs.push({ label: "Rule" });
  if (parts[2] === "studio") crumbs.push({ label: "Rule studio" });
  delete crumbs[crumbs.length - 1].to;
  return crumbs;
}

const THEMES: { value: ThemeChoice; label: string; icon: typeof Sun }[] = [
  { value: "light", label: "Light", icon: Sun },
  { value: "dark", label: "Dark", icon: Moon },
  { value: "system", label: "System", icon: Monitor },
];

function ThemeMenu({
  choice,
  setChoice,
  collapsed,
}: {
  choice: ThemeChoice;
  setChoice: (c: ThemeChoice) => void;
  collapsed: boolean;
}) {
  const Current = THEMES.find((t) => t.value === choice)?.icon ?? Monitor;
  return (
    <Dropdown.Root>
      <Dropdown.Trigger asChild>
        <button type="button" className="nav-link unstyled" aria-label="Theme">
          <Current size={17} aria-hidden="true" />
          <span className="nav-label">Theme</span>
        </button>
      </Dropdown.Trigger>
      <Dropdown.Portal>
        <Dropdown.Content
          className="menu"
          side={collapsed ? "right" : "top"}
          align="start"
          sideOffset={6}
        >
          {THEMES.map(({ value, label, icon: Icon }) => (
            <Dropdown.Item key={value} className="menu-item" onSelect={() => setChoice(value)}>
              <Icon size={15} aria-hidden="true" /> {label}
              {choice === value && <Check size={14} className="check" aria-label="selected" />}
            </Dropdown.Item>
          ))}
        </Dropdown.Content>
      </Dropdown.Portal>
    </Dropdown.Root>
  );
}

function NavItem({
  to,
  label,
  icon: Icon,
  end,
  collapsed,
  inDrawer = false,
}: {
  to: string;
  label: string;
  icon: typeof Sun;
  end?: boolean;
  collapsed: boolean;
  inDrawer?: boolean;
}) {
  return (
    <Tip content={collapsed ? label : null}>
      <NavLink to={to} end={end} className="nav-link">
        {({ isActive }) => (
          <>
            {isActive &&
              (inDrawer ? (
                <span className="nav-active" />
              ) : (
                <motion.span
                  layoutId="nav-active"
                  className="nav-active"
                  transition={{ type: "spring", stiffness: 500, damping: 40 }}
                />
              ))}
            <Icon size={17} aria-hidden="true" />
            <span className="nav-label">{label}</span>
          </>
        )}
      </NavLink>
    </Tip>
  );
}

function MainNav({ collapsed, inDrawer = false }: { collapsed: boolean; inDrawer?: boolean }) {
  const { can, canManageUsers } = useAuth();
  const item = { collapsed, inDrawer };
  return (
    <nav aria-label="Main" style={{ display: "contents" }}>
      <div className="nav-section">Console</div>
      {NAV.map((entry) => (
        <NavItem key={entry.to} {...entry} {...item} />
      ))}
      <div className="nav-section">Shortcuts</div>
      <NavItem to="/tenants/demo" label="Demo tenant" icon={Building2} {...item} />
      {can("admin") && (
        <>
          <div className="nav-section">Administration</div>
          {canManageUsers && <NavItem to="/admin/users" label="Users" icon={Users} {...item} />}
          <NavItem to="/admin/audit" label="Audit log" icon={FileClock} {...item} />
        </>
      )}
    </nav>
  );
}

/** The sidebar's contents in a drawer, for screens too narrow for a sidebar. */
function MenuDrawer({
  open,
  onOpenChange,
  theme,
  setTheme,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  theme: ThemeChoice;
  setTheme: (c: ThemeChoice) => void;
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
            <Dialog.Content asChild forceMount aria-describedby={undefined}>
              <motion.div
                className="drawer"
                initial={{ x: "-100%" }}
                animate={{ x: 0 }}
                exit={{ x: "-100%" }}
                transition={{ duration: 0.22, ease }}
              >
                <div className="drawer-head">
                  <Link to="/" className="brand" aria-label="Agent Mandate home">
                    <BrandMark />
                    <span className="brand-name">Agent Mandate</span>
                  </Link>
                  <Dialog.Title className="sr-only">Menu</Dialog.Title>
                  <Dialog.Close asChild>
                    <button type="button" className="ghost icon" aria-label="Close the menu">
                      <X size={18} aria-hidden="true" />
                    </button>
                  </Dialog.Close>
                </div>
                <MainNav collapsed={false} inDrawer />
                <div className="sidebar-foot">
                  <AccountMenu collapsed={false} />
                  <ThemeMenu choice={theme} setChoice={setTheme} collapsed={false} />
                </div>
              </motion.div>
            </Dialog.Content>
          </Dialog.Portal>
        )}
      </AnimatePresence>
    </Dialog.Root>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  const location = useLocation();
  const [theme, setTheme] = useTheme();
  const [palette, setPalette] = useState(false);
  const [menu, setMenu] = useState(false);
  const [collapsed, setCollapsed] = useState(readCollapsed);
  const crumbs = crumbsFor(location.pathname);
  const mac = typeof navigator !== "undefined" && /Mac/i.test(navigator.platform);

  // Following a link from the drawer closes it.
  useEffect(() => setMenu(false), [location.pathname]);

  const toggle = () => {
    setCollapsed((was) => {
      try {
        window.localStorage.setItem(COLLAPSE_KEY, was ? "open" : "collapsed");
      } catch {
        // Storage unavailable: the choice lasts this visit.
      }
      return !was;
    });
  };

  return (
    <div className={`shell${collapsed ? " collapsed" : ""}`}>
      <a className="skip" href="#main">
        Skip to content
      </a>
      <aside className="sidebar">
        <Link to="/" className="brand" aria-label="Agent Mandate home">
          <BrandMark />
          <span className="brand-name">Agent Mandate</span>
        </Link>
        <MainNav collapsed={collapsed} />
        <div className="sidebar-foot">
          <AccountMenu collapsed={collapsed} />
          <ThemeMenu choice={theme} setChoice={setTheme} collapsed={collapsed} />
          <button
            type="button"
            className="nav-link unstyled collapse-toggle"
            onClick={toggle}
            aria-label={collapsed ? "Expand the sidebar" : "Collapse the sidebar"}
            aria-expanded={!collapsed}
          >
            {collapsed ? (
              <PanelLeftOpen size={17} aria-hidden="true" />
            ) : (
              <PanelLeftClose size={17} aria-hidden="true" />
            )}
            <span className="nav-label sidebar-foot-text">Collapse</span>
          </button>
        </div>
      </aside>

      <div className="main">
        <header className="topbar">
          <button
            type="button"
            className="ghost icon menu-trigger"
            aria-label="Open the menu"
            aria-expanded={menu}
            onClick={() => setMenu(true)}
          >
            <Menu size={19} aria-hidden="true" />
          </button>
          <nav aria-label="Breadcrumb" className="crumbs">
            {crumbs.map((crumb, index) => (
              <span key={`${crumb.label}-${index}`} className="crumbs">
                {index > 0 && <ChevronRight size={14} aria-hidden="true" />}
                {crumb.to ? (
                  <Link to={crumb.to}>{crumb.label}</Link>
                ) : (
                  <span className="here" aria-current="page">
                    {crumb.label}
                  </span>
                )}
              </span>
            ))}
          </nav>
          <span className="spacer" />
          <button type="button" className="search-trigger" onClick={() => setPalette(true)}>
            <Search size={15} aria-hidden="true" />
            <span className="search-text">Search or jump to…</span>
            <Kbd>{mac ? "⌘" : "Ctrl"} K</Kbd>
          </button>
        </header>
        <main id="main" className="content">
          <AnimatePresence mode="wait" initial={false}>
            <motion.div
              key={location.pathname}
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -4 }}
              transition={{ duration: 0.2, ease }}
            >
              {children}
            </motion.div>
          </AnimatePresence>
        </main>
      </div>
      <MenuDrawer open={menu} onOpenChange={setMenu} theme={theme} setTheme={setTheme} />
      <CommandPalette open={palette} onOpenChange={setPalette} setTheme={setTheme} />
    </div>
  );
}
