import { useEffect, useState } from 'react';
import { ROLE_LABEL, api, getSession, logout } from '../lib/api.js';
import { Loading, Toaster } from './ui.jsx';

const icon = (d) => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    {d.split('|').map((p) => <path key={p} d={p} />)}
  </svg>
);

const ALL = ['admin', 'sales_manager', 'sales_rep', 'finance'];
const NAV = [
  { group: 'Sell', items: [
    { id: 'dashboard', label: 'Dashboard', href: '/', roles: ALL, icon: 'M3 12l9-8 9 8|M5 10v10h14V10' },
    { id: 'quotations', label: 'Quotations', href: '/quotations', roles: ALL, icon: 'M7 3h8l4 4v14H7z|M14 3v5h5|M10 13h6|M10 17h6' },
    { id: 'approvals', label: 'Approvals', href: '/approvals', roles: ALL, icon: 'M9 12l2 2 4-4|M12 3l8 3v6c0 5-3.5 8-8 9-4.500-1-8-4-8-9V6z', badge: 'approvals' },
    { id: 'deal-health', label: 'Deal Health', href: '/deal-health', roles: ALL, icon: 'M3 12h4l2-6 4 12 2-6h6' },
    { id: 'customers', label: 'Customers', href: '/customers', roles: ALL, icon: 'M16 19v-1a4 4 0 0 0-8 0v1|M12 11a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7|M20 19v-1a3 3 0 0 0-2.500-2.950|M4 19v-1a3 3 0 0 1 2.500-2.950' },
  ] },
  { group: 'Deliver', items: [
    { id: 'products', label: 'Products', href: '/products', roles: ALL, icon: 'M4 8l8-4 8 4-8 4z|M4 8v8l8 4 8-4V8|M12 12v8' },
    { id: 'inventory', label: 'Inventory', href: '/inventory', roles: ALL, icon: 'M3 21V9l9-5 9 5v12|M8 21v-7h8v7' },
    { id: 'fulfillment', label: 'Fulfilment', href: '/fulfillment', roles: ALL, icon: 'M2 7h11v9H2z|M13 10h4l3 3v3h-7|M6.500 19a1.500 1.500 0 1 0 0-3|M17 19a1.500 1.500 0 1 0 0-3' },
  ] },
  { group: 'Collect', items: [
    { id: 'invoices', label: 'Invoices', href: '/invoices', roles: ALL, icon: 'M6 3h12v18l-3-2-3 2-3-2-3 2z|M9 8h6|M9 12h6' },
    { id: 'subscriptions', label: 'Subscriptions', href: '/subscriptions', roles: ALL, icon: 'M20 12a8 8 0 1 1-2.300-5.600|M20 4v4h-4' },
    { id: 'reports', label: 'Reports', href: '/reports', roles: ALL, icon: 'M4 20V10|M10 20V4|M16 20v-7|M22 20H2' },
  ] },
  { group: 'Admin', items: [
    { id: 'settings', label: 'Governance', href: '/settings', roles: ALL, icon: 'M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6|M19 12a7 7 0 0 0-.100-1.200l2-1.500-2-3.400-2.300.900a7 7 0 0 0-2-1.200L14.200 3h-4l-.400 2.500a7 7 0 0 0-2 1.200l-2.300-.900-2 3.400 2 1.500a7 7 0 0 0 0 2.400l-2 1.500 2 3.400 2.300-.900a7 7 0 0 0 2 1.200l.400 2.500h4l.400-2.500a7 7 0 0 0 2-1.200l2.300.900 2-3.400-2-1.500c.100-.400.100-.800.100-1.200z' },
  ] },
];

function Logo() {
  return (
    <a href="/" className="flex items-center gap-2.5">
      <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-gradient-to-br from-brand-500 to-cyan-400 shadow-lg shadow-brand-900/40">
        <svg width="20" height="20" viewBox="0 0 32 32" fill="none"><path d="M8 22l6-7 4 3 6-9" stroke="#fff" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" /></svg>
      </span>
      <span className="font-display text-lg font-extrabold tracking-tight text-white">DealFlow<span className="text-cyan-300">360</span></span>
    </a>
  );
}

export default function AppShell({ page, roles = ALL, children }) {
  const [session, setSession] = useState(null);
  const [open, setOpen] = useState(false);
  const [pending, setPending] = useState(0);

  useEffect(() => {
    const s = getSession();
    if (!s?.token) { window.location.replace('/login'); return; }
    if (s.user.role === 'customer') { window.location.replace('/portal'); return; }
    if (!roles.includes(s.user.role)) { window.location.replace('/'); return; }
    setSession(s);
    api('/approvals/queue').then((q) => setPending(q.filter((x) => x.can_act).length)).catch(() => {});
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  if (!session) return <Loading />;
  const { user } = session;
  const initials = user.name.split(' ').map((p) => p[0]).slice(0, 2).join('').toUpperCase();

  return (
    <div className="min-h-screen lg:pl-64">
      {open && <div className="no-print fixed inset-0 z-30 bg-slate-900/50 lg:hidden" onClick={() => setOpen(false)} />}
      <aside className={`no-print fixed inset-y-0 left-0 z-40 flex w-64 flex-col bg-ink transition-transform lg:translate-x-0 ${open ? 'translate-x-0' : '-translate-x-full'}`}>
        <div className="px-5 py-5"><Logo /></div>
        <nav className="scroll-thin flex-1 space-y-5 overflow-y-auto px-3 pb-4" aria-label="Main">
          {NAV.map((group) => {
            const items = group.items.filter((i) => i.roles.includes(user.role));
            if (!items.length) return null;
            return (
              <div key={group.group}>
                <p className="px-3 pb-1.5 text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">{group.group}</p>
                {items.map((item) => (
                  <a key={item.id} href={item.href} aria-current={page === item.id ? 'page' : undefined}
                    className={`group mb-0.5 flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition ${page === item.id ? 'bg-white/10 text-white' : 'text-slate-400 hover:bg-white/5 hover:text-slate-100'}`}>
                    <span className={page === item.id ? 'text-cyan-300' : 'text-slate-500 group-hover:text-slate-300'}>{icon(item.icon)}</span>
                    {item.label}
                    {item.badge === 'approvals' && pending > 0 && <span className="ml-auto rounded-full bg-amber-400 px-1.5 text-[11px] font-bold text-amber-950">{pending}</span>}
                  </a>
                ))}
              </div>
            );
          })}
        </nav>
        <div className="border-t border-white/10 p-3">
          <div className="flex items-center gap-3 rounded-lg px-2 py-2">
            <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-brand-500/90 text-xs font-bold text-white">{initials}</span>
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-semibold text-white">{user.name}</p>
              <p className="truncate text-xs text-slate-400">{ROLE_LABEL[user.role]}</p>
            </div>
            <button onClick={logout} title="Sign out" aria-label="Sign out" className="rounded-md p-1.5 text-slate-400 hover:bg-white/10 hover:text-white">
              {icon('M15 4h4v16h-4|M10 8l-4 4 4 4|M6 12h10')}
            </button>
          </div>
        </div>
      </aside>

      <header className="no-print sticky top-0 z-20 flex items-center gap-3 border-b border-slate-200 bg-white/85 px-4 py-3 backdrop-blur lg:hidden">
        <button onClick={() => setOpen(true)} aria-label="Open menu" className="rounded-md p-1.5 text-slate-600 hover:bg-slate-100">{icon('M4 7h16|M4 12h16|M4 17h16')}</button>
        <span className="font-display font-extrabold text-slate-900">DealFlow<span className="text-brand-600">360</span></span>
      </header>

      <main className="animate-fade-up mx-auto max-w-[1400px] px-4 py-6 sm:px-6 lg:px-8 lg:py-8">
        {typeof children === 'function' ? children(user) : children}
      </main>
      <Toaster />
    </div>
  );
}
