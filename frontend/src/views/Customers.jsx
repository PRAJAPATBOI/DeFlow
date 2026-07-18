import { useMemo, useState } from 'react';
import AppShell from '../components/AppShell.jsx';
import { Badge, Button, Card, ErrorBox, Field, Loading, Modal, PageHeader, StatusBadge, Table, act, useAsync } from '../components/ui.jsx';
import { api, can } from '../lib/api.js';
import { fmtDate, inr, inrShort } from '../lib/format.js';

const TIER_TONE = { standard: 'slate', silver: 'sky', gold: 'amber', platinum: 'violet' };
const BLANK = { name: '', industry: '', contact_name: '', email: '', phone: '', city: '', region: 'West', gstin: '', tier: 'standard', credit_limit: 500000, payment_terms_days: 30 };

function CustomerForm({ initial, user, onClose, onSaved }) {
  const [form, setForm] = useState({ ...BLANK, ...initial });
  const [busy, setBusy] = useState(false);
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });
  const locked = user.role === 'sales_rep' && !!initial?.id;
  async function save(e) {
    e.preventDefault();
    setBusy(true);
    const body = { ...form, email: form.email || null, credit_limit: Number(form.credit_limit), payment_terms_days: Number(form.payment_terms_days) };
    BLANK_KEYS.forEach((k) => { if (body[k] === '') body[k] = null; });
    const saved = await act(initial?.id ? api(`/customers/${initial.id}`, { method: 'PATCH', body }) : api('/customers', { method: 'POST', body }), 'Customer saved');
    setBusy(false);
    if (saved) onSaved(saved);
  }
  return (
    <Modal open wide title={initial?.id ? `Edit ${initial.name}` : 'New customer'} onClose={onClose}
      footer={<><Button variant="ghost" onClick={onClose}>Cancel</Button><Button form="customer-form" type="submit" loading={busy}>Save customer</Button></>}>
      <form id="customer-form" onSubmit={save} className="grid gap-4 sm:grid-cols-2">
        <Field label="Company name" className="sm:col-span-2"><input className="input" required minLength={2} value={form.name} onChange={set('name')} /></Field>
        <Field label="Industry"><input className="input" value={form.industry || ''} onChange={set('industry')} /></Field>
        <Field label="GSTIN"><input className="input" value={form.gstin || ''} onChange={set('gstin')} maxLength={20} /></Field>
        <Field label="Contact person"><input className="input" value={form.contact_name || ''} onChange={set('contact_name')} /></Field>
        <Field label="Email"><input className="input" type="email" value={form.email || ''} onChange={set('email')} /></Field>
        <Field label="Phone"><input className="input" value={form.phone || ''} onChange={set('phone')} /></Field>
        <Field label="City"><input className="input" value={form.city || ''} onChange={set('city')} /></Field>
        <Field label="Region" hint="Drives warehouse selection and freight"><select className="input" value={form.region} onChange={set('region')}>{['North', 'South', 'East', 'West'].map((r) => <option key={r}>{r}</option>)}</select></Field>
        <Field label="Tier"><select className="input capitalize" disabled={locked} value={form.tier} onChange={set('tier')}>{Object.keys(TIER_TONE).map((t) => <option key={t}>{t}</option>)}</select></Field>
        <Field label="Credit limit (₹)" hint={locked ? 'Only managers can change commercial terms' : 'Deals above 50% of this add credit risk'}><input className="input" type="number" min="0" step="10000" disabled={locked} value={form.credit_limit} onChange={set('credit_limit')} /></Field>
        <Field label="Payment terms (days)"><input className="input" type="number" min="0" max="180" disabled={locked} value={form.payment_terms_days} onChange={set('payment_terms_days')} /></Field>
      </form>
    </Modal>
  );
}
const BLANK_KEYS = ['industry', 'contact_name', 'phone', 'city', 'gstin'];

function Customer360({ id, user, onClose, onEdit }) {
  const { data: c, loading, error } = useAsync(() => api(`/customers/${id}`), [id]);
  return (
    <Modal open wide title={c?.name || 'Customer'} subtitle={c ? `${c.industry || 'Customer'} · ${c.city || c.region} · owned by ${c.owner_name || '—'}` : ''} onClose={onClose}
      footer={<>{can.sell(user) && c && <Button variant="secondary" onClick={() => onEdit(c)}>Edit</Button>}<Button onClick={() => { window.location.href = '/quotation'; }}>New quotation</Button></>}>
      {loading ? <Loading /> : error ? <ErrorBox error={error} /> : (
        <div className="space-y-5">
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            {[['Tier', <span className="capitalize">{c.tier}</span>], ['Credit limit', inrShort(c.credit_limit)], ['Outstanding', inrShort(c.outstanding)], ['Credit used', `${c.credit_used_percent}%`]].map(([k, v]) => (
              <div key={k} className="rounded-lg bg-slate-50 px-3 py-2.5"><p className="text-[11px] uppercase tracking-wide text-slate-500">{k}</p><p className="num mt-0.5 font-bold text-slate-900">{v}</p></div>
            ))}
          </div>
          <div className="h-2 overflow-hidden rounded-full bg-slate-100"><div className={`h-full rounded-full ${c.credit_used_percent > 80 ? 'bg-rose-500' : c.credit_used_percent > 50 ? 'bg-amber-500' : 'bg-emerald-500'}`} style={{ width: `${Math.min(100, c.credit_used_percent)}%` }} /></div>
          <p className="text-sm text-slate-600">{c.contact_name} · {c.email || 'no email'} · {c.phone || 'no phone'} · GSTIN {c.gstin || '—'} · Net {c.payment_terms_days}</p>
          <div>
            <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">Quotations ({c.quotations.length})</h4>
            <div className="rounded-lg border border-slate-200"><Table rows={c.quotations.slice(0, 8)} empty="No quotations yet" onRowClick={(q) => { window.location.href = `/quotation?id=${q.id}`; }} columns={[
              { key: 'number', label: 'Quote', render: (q) => <><p className="font-medium text-slate-900">{q.title}</p><p className="text-xs text-slate-500">{q.number}</p></> },
              { key: 'status', label: 'Status', render: (q) => <StatusBadge status={q.status} /> },
              { key: 'total', label: 'Total', right: true, render: (q) => inr(q.total) },
            ]} /></div>
          </div>
          <div>
            <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">Invoices ({c.invoices.length})</h4>
            <div className="rounded-lg border border-slate-200"><Table rows={c.invoices.slice(0, 8)} empty="No invoices yet" columns={[
              { key: 'number', label: 'Invoice', render: (i) => <span className="font-medium text-slate-900">{i.number}</span> },
              { key: 'due_date', label: 'Due', render: (i) => fmtDate(i.due_date) },
              { key: 'status', label: 'Status', render: (i) => <StatusBadge status={i.status} /> },
              { key: 'balance', label: 'Balance', right: true, render: (i) => inr(i.balance) },
            ]} /></div>
          </div>
        </div>
      )}
    </Modal>
  );
}

function Content({ user }) {
  const { data, loading, error, reload } = useAsync(() => api('/customers'));
  const [search, setSearch] = useState('');
  const [editing, setEditing] = useState(null);
  const [viewing, setViewing] = useState(null);
  const rows = useMemo(() => (data || []).filter((c) => `${c.name} ${c.city} ${c.industry}`.toLowerCase().includes(search.toLowerCase())), [data, search]);
  if (loading) return <Loading />;
  if (error) return <ErrorBox error={error} onRetry={reload} />;
  return (
    <>
      <PageHeader title="Customers" subtitle={`${data.length} accounts`}>
        <input className="input w-56" placeholder="Search customers…" value={search} onChange={(e) => setSearch(e.target.value)} aria-label="Search customers" />
        {can.sell(user) && <Button onClick={() => setEditing({})}>+ New customer</Button>}
      </PageHeader>
      <Card padded={false}>
        <Table rows={rows} onRowClick={(c) => setViewing(c.id)} empty="No customers match" columns={[
          { key: 'name', label: 'Company', render: (c) => <><p className="font-semibold text-slate-900">{c.name}</p><p className="text-xs text-slate-500">{c.industry} · {c.city}</p></> },
          { key: 'contact_name', label: 'Contact' },
          { key: 'tier', label: 'Tier', render: (c) => <Badge tone={TIER_TONE[c.tier]}><span className="capitalize">{c.tier}</span></Badge> },
          { key: 'region', label: 'Region' },
          { key: 'owner_name', label: 'Owner' },
          { key: 'open_quotes', label: 'Open quotes', right: true },
          { key: 'won_value', label: 'Won value', right: true, render: (c) => inrShort(c.won_value) },
          { key: 'credit_limit', label: 'Credit limit', right: true, render: (c) => inrShort(c.credit_limit) },
        ]} />
      </Card>
      {viewing && !editing && <Customer360 id={viewing} user={user} onClose={() => setViewing(null)} onEdit={(c) => setEditing(c)} />}
      {editing && <CustomerForm initial={editing} user={user} onClose={() => setEditing(null)} onSaved={() => { setEditing(null); setViewing(null); reload(true); }} />}
    </>
  );
}

export default function Customers() {
  return <AppShell page="customers">{(user) => <Content user={user} />}</AppShell>;
}
