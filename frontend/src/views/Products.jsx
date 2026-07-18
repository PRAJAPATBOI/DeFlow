import { useMemo, useState } from 'react';
import AppShell from '../components/AppShell.jsx';
import { Badge, Button, Card, ErrorBox, Field, Loading, Modal, PageHeader, Table, act, useAsync } from '../components/ui.jsx';
import { api, can } from '../lib/api.js';
import { PERIOD, inr, pct } from '../lib/format.js';

const BLANK = { sku: '', name: '', category: 'Servers', description: '', price: '', cost: '', unit: 'each', tax_rate: 18, is_subscription: false, billing_period: 'monthly', is_stocked: true, is_active: true };

function ProductForm({ initial, categories, onClose, onSaved }) {
  const [form, setForm] = useState({ ...BLANK, ...initial });
  const [busy, setBusy] = useState(false);
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.type === 'checkbox' ? e.target.checked : e.target.value });
  const margin = form.price > 0 ? ((form.price - (form.cost || 0)) / form.price) * 100 : 0;
  async function save(e) {
    e.preventDefault();
    setBusy(true);
    const body = { ...form, price: Number(form.price), cost: Number(form.cost) || 0, tax_rate: Number(form.tax_rate), billing_period: form.is_subscription ? form.billing_period || 'monthly' : null, is_stocked: form.is_stocked && !form.is_subscription };
    const saved = await act(initial?.id ? api(`/products/${initial.id}`, { method: 'PATCH', body }) : api('/products', { method: 'POST', body }), 'Product saved');
    setBusy(false);
    if (saved) onSaved();
  }
  return (
    <Modal open wide title={initial?.id ? `Edit ${initial.sku}` : 'New product'} onClose={onClose}
      footer={<><Button variant="ghost" onClick={onClose}>Cancel</Button><Button form="product-form" type="submit" loading={busy}>Save product</Button></>}>
      <form id="product-form" onSubmit={save} className="grid gap-4 sm:grid-cols-2">
        <Field label="SKU"><input className="input uppercase" required minLength={2} maxLength={40} value={form.sku} onChange={set('sku')} /></Field>
        <Field label="Category"><input className="input" required list="categories" value={form.category} onChange={set('category')} /><datalist id="categories">{categories.map((c) => <option key={c} value={c} />)}</datalist></Field>
        <Field label="Name" className="sm:col-span-2"><input className="input" required minLength={2} value={form.name} onChange={set('name')} /></Field>
        <Field label="Description" className="sm:col-span-2"><textarea className="input" rows={2} value={form.description || ''} onChange={set('description')} /></Field>
        <Field label="List price (₹)"><input className="input" type="number" required min="1" step="0.01" value={form.price} onChange={set('price')} /></Field>
        <Field label="Unit cost (₹)" hint={`Margin at list price: ${pct(margin)}`}><input className="input" type="number" min="0" step="0.01" value={form.cost} onChange={set('cost')} /></Field>
        <Field label="Unit"><input className="input" value={form.unit} onChange={set('unit')} /></Field>
        <Field label="GST %"><input className="input" type="number" min="0" max="50" step="0.5" value={form.tax_rate} onChange={set('tax_rate')} /></Field>
        <label className="flex items-center gap-2 text-sm text-slate-700"><input type="checkbox" className="h-4 w-4 rounded border-slate-300 text-brand-600" checked={form.is_subscription} onChange={set('is_subscription')} /> Recurring subscription</label>
        {form.is_subscription ? (
          <Field label="Billing period"><select className="input" value={form.billing_period || 'monthly'} onChange={set('billing_period')}><option value="monthly">Monthly</option><option value="quarterly">Quarterly</option><option value="annual">Annual</option></select></Field>
        ) : <span />}
        <label className="flex items-center gap-2 text-sm text-slate-700"><input type="checkbox" className="h-4 w-4 rounded border-slate-300 text-brand-600" disabled={form.is_subscription} checked={form.is_stocked && !form.is_subscription} onChange={set('is_stocked')} /> Stocked physical item (ships from a warehouse)</label>
        <label className="flex items-center gap-2 text-sm text-slate-700"><input type="checkbox" className="h-4 w-4 rounded border-slate-300 text-brand-600" checked={form.is_active} onChange={set('is_active')} /> Active (available for quoting)</label>
      </form>
    </Modal>
  );
}

function Content({ user }) {
  const { data, loading, error, reload } = useAsync(() => api('/products?include_inactive=true'));
  const [search, setSearch] = useState('');
  const [category, setCategory] = useState('');
  const [editing, setEditing] = useState(null);
  const categories = useMemo(() => [...new Set((data || []).map((p) => p.category))].sort(), [data]);
  const rows = useMemo(() => (data || []).filter((p) => (!category || p.category === category) && `${p.name} ${p.sku}`.toLowerCase().includes(search.toLowerCase())), [data, search, category]);
  if (loading) return <Loading />;
  if (error) return <ErrorBox error={error} onRetry={reload} />;
  const editable = can.manage(user);
  return (
    <>
      <PageHeader title="Product catalogue" subtitle={`${data.length} products across ${categories.length} categories`}>
        <input className="input w-52" placeholder="Search name or SKU…" value={search} onChange={(e) => setSearch(e.target.value)} aria-label="Search products" />
        <select className="input w-auto" value={category} onChange={(e) => setCategory(e.target.value)} aria-label="Category"><option value="">All categories</option>{categories.map((c) => <option key={c}>{c}</option>)}</select>
        {editable && <Button onClick={() => setEditing({})}>+ New product</Button>}
      </PageHeader>
      <Card padded={false}>
        <Table rows={rows} onRowClick={editable ? (p) => setEditing(p) : undefined} empty="No products match" columns={[
          { key: 'name', label: 'Product', render: (p) => <><p className={`font-semibold ${p.is_active ? 'text-slate-900' : 'text-slate-400 line-through'}`}>{p.name}</p><p className="text-xs text-slate-500">{p.sku}</p></> },
          { key: 'category', label: 'Category', render: (p) => <Badge>{p.category}</Badge> },
          { key: 'type', label: 'Type', render: (p) => (p.is_subscription ? <Badge tone="indigo">Subscription · {p.billing_period}</Badge> : <Badge tone="slate">{p.is_stocked ? 'Hardware' : 'Service'}</Badge>) },
          { key: 'price', label: 'List price', right: true, render: (p) => <>{inr(p.price)}<span className="text-xs text-slate-400"> /{p.is_subscription ? PERIOD[p.billing_period] : p.unit}</span></> },
          { key: 'cost', label: 'Cost', right: true, render: (p) => inr(p.cost) },
          { key: 'margin_percent', label: 'Margin', right: true, render: (p) => <span className={p.margin_percent < 20 ? 'font-semibold text-amber-600' : ''}>{pct(p.margin_percent)}</span> },
          { key: 'stock', label: 'Stock', right: true, render: (p) => (p.stock_available == null ? <span className="text-slate-300">—</span> : <span className={p.stock_available < 5 ? 'font-semibold text-rose-600' : ''}>{p.stock_available}</span>) },
        ]} />
      </Card>
      {editing && <ProductForm initial={editing} categories={categories} onClose={() => setEditing(null)} onSaved={() => { setEditing(null); reload(true); }} />}
    </>
  );
}

export default function Products() {
  return <AppShell page="products">{(user) => <Content user={user} />}</AppShell>;
}
