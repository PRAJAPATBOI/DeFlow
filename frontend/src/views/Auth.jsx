import { useEffect, useState } from 'react';
import { api, getSession, setSession } from '../lib/api.js';
import { Button, Field } from '../components/ui.jsx';

const DEMO = [
  { role: 'Administrator', email: 'admin@dealflow360.in', hint: 'Everything, incl. policy & users' },
  { role: 'Sales Manager', email: 'manager@dealflow360.in', hint: 'Approvals, catalogue, fulfilment' },
  { role: 'Sales Rep', email: 'arjun@dealflow360.in', hint: 'Build quotes, negotiate' },
  { role: 'Finance', email: 'finance@dealflow360.in', hint: 'High-risk approvals, invoices' },
  { role: 'Customer', email: 'customer@aravalli.example', hint: 'Portal: review & accept quotes' },
];
const DEMO_PASSWORD = 'Demo@1234';

const landing = (user) => (user.role === 'customer' ? '/portal' : '/');

function Shell({ children }) {
  return (
    <div className="grid min-h-screen lg:grid-cols-[1.05fr_1fr]">
      <aside className="relative hidden overflow-hidden bg-ink p-12 text-white lg:flex lg:flex-col lg:justify-between">
        <div className="pointer-events-none absolute -left-24 -top-24 h-96 w-96 rounded-full bg-brand-600/40 blur-3xl" />
        <div className="pointer-events-none absolute -bottom-32 right-0 h-96 w-96 rounded-full bg-cyan-500/20 blur-3xl" />
        <div className="relative flex items-center gap-3">
          <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-brand-500 to-cyan-400">
            <svg width="22" height="22" viewBox="0 0 32 32" fill="none"><path d="M8 22l6-7 4 3 6-9" stroke="#fff" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" /></svg>
          </span>
          <span className="font-display text-xl font-extrabold">DealFlow<span className="text-cyan-300">360</span></span>
        </div>
        <div className="relative">
          <h1 className="max-w-md text-4xl font-extrabold leading-tight">Every deal, from first quote to final payment.</h1>
          <p className="mt-4 max-w-md text-slate-300">Configure and price quotes, route risky discounts for approval, negotiate with customers, split shipments across warehouses and bill subscriptions — in one flow.</p>
          <ul className="mt-8 grid max-w-md grid-cols-2 gap-3 text-sm">
            {['Risk-scored approvals', 'Customer portal & counter-offers', 'Multi-warehouse fulfilment', 'Pro-rated recurring billing'].map((f) => (
              <li key={f} className="flex items-center gap-2 rounded-lg bg-white/5 px-3 py-2.5 ring-1 ring-white/10">
                <span className="text-cyan-300">✓</span>{f}
              </li>
            ))}
          </ul>
        </div>
        <p className="relative text-xs text-slate-500">Built by Ramesh Prajapat · FastAPI · SQLAlchemy · Astro · React</p>
      </aside>
      <main className="flex items-center justify-center px-5 py-10">
        <div className="animate-fade-up w-full max-w-md">{children}</div>
      </main>
    </div>
  );
}

export function Login() {
  const [form, setForm] = useState({ email: '', password: '' });
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const expired = typeof window !== 'undefined' && window.location.search.includes('expired');

  useEffect(() => {
    const s = getSession();
    if (s?.token) window.location.replace(landing(s.user));
  }, []);

  async function signIn(credentials) {
    setBusy(true);
    setError('');
    try {
      const data = await api('/auth/login', { method: 'POST', body: credentials, auth: false });
      setSession(data);
      window.location.href = landing(data.user);
    } catch (e) {
      setError(e.message);
      setBusy(false);
    }
  }

  return (
    <Shell>
      <h2 className="text-2xl font-bold text-slate-900">Sign in</h2>
      <p className="mt-1 text-sm text-slate-500">Welcome back. Enter your work email to continue.</p>
      {expired && !error && <p className="mt-4 rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-800 ring-1 ring-amber-200">Your session expired. Please sign in again.</p>}
      {error && <p role="alert" className="mt-4 rounded-lg bg-rose-50 px-3 py-2 text-sm text-rose-700 ring-1 ring-rose-200">{error}</p>}
      <form className="mt-6 space-y-4" onSubmit={(e) => { e.preventDefault(); signIn(form); }}>
        <Field label="Email">
          <input className="input" type="email" required autoComplete="username" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} placeholder="you@company.com" />
        </Field>
        <Field label="Password">
          <input className="input" type="password" required autoComplete="current-password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} placeholder="••••••••" />
        </Field>
        <Button type="submit" size="lg" className="w-full" loading={busy}>Sign in</Button>
      </form>

      <div className="mt-8">
        <p className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-400">Demo accounts — one click</p>
        <div className="grid gap-2">
          {DEMO.map((d) => (
            <button key={d.email} type="button" disabled={busy} onClick={() => signIn({ email: d.email, password: DEMO_PASSWORD })}
              className="flex items-center justify-between rounded-lg border border-slate-200 bg-white px-3.5 py-2.5 text-left transition hover:border-brand-300 hover:bg-brand-50/50 disabled:opacity-50">
              <span>
                <span className="block text-sm font-semibold text-slate-800">{d.role}</span>
                <span className="block text-xs text-slate-500">{d.hint}</span>
              </span>
              <span className="text-xs text-slate-400">{d.email}</span>
            </button>
          ))}
        </div>
      </div>
      <p className="mt-6 text-center text-sm text-slate-500">Are you a customer? <a href="/register" className="font-semibold text-brand-600 hover:underline">Create a portal account</a></p>
    </Shell>
  );
}

export function Register() {
  const [form, setForm] = useState({ name: '', company: '', email: '', password: '' });
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const set = (key) => (e) => setForm({ ...form, [key]: e.target.value });

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setError('');
    try {
      const data = await api('/auth/register', { method: 'POST', body: form, auth: false });
      setSession(data);
      window.location.href = '/portal';
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  }

  return (
    <Shell>
      <h2 className="text-2xl font-bold text-slate-900">Create a customer account</h2>
      <p className="mt-1 text-sm text-slate-500">Track your quotations and invoices in one place. Internal staff accounts are created by an administrator.</p>
      {error && <p role="alert" className="mt-4 rounded-lg bg-rose-50 px-3 py-2 text-sm text-rose-700 ring-1 ring-rose-200">{error}</p>}
      <form className="mt-6 space-y-4" onSubmit={submit}>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Your name"><input className="input" required minLength={2} value={form.name} onChange={set('name')} /></Field>
          <Field label="Company"><input className="input" required minLength={2} value={form.company} onChange={set('company')} /></Field>
        </div>
        <Field label="Work email"><input className="input" type="email" required value={form.email} onChange={set('email')} /></Field>
        <Field label="Password" hint="At least 8 characters"><input className="input" type="password" required minLength={8} value={form.password} onChange={set('password')} /></Field>
        <Button type="submit" size="lg" className="w-full" loading={busy}>Create account</Button>
      </form>
      <p className="mt-6 text-center text-sm text-slate-500">Already registered? <a href="/login" className="font-semibold text-brand-600 hover:underline">Sign in</a></p>
    </Shell>
  );
}
