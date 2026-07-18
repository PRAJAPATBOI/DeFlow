import { useMemo, useState } from 'react';
import AppShell from '../components/AppShell.jsx';
import { Badge, Button, Card, ErrorBox, Field, Loading, Modal, PageHeader, Table, act, toast, useAsync } from '../components/ui.jsx';
import { api, can } from '../lib/api.js';
import { inr } from '../lib/format.js';

function AdjustModal({ row, warehouses, onClose, onDone }) {
  const [delta, setDelta] = useState(10);
  const [reason, setReason] = useState('Purchase order received');
  const [busy, setBusy] = useState(false);
  const wh = warehouses.find((w) => w.id === row.warehouse_id);
  async function save() {
    if (!Number(delta)) return toast('Enter a non-zero quantity', 'error');
    setBusy(true);
    const ok = await act(api('/inventory/adjust', { method: 'POST', body: { warehouse_id: row.warehouse_id, product_id: row.product_id, delta: Number(delta), reason } }), 'Stock updated');
    setBusy(false);
    if (ok) onDone();
  }
  return (
    <Modal open title="Adjust stock" subtitle={`${row.product} · ${wh?.name}`} onClose={onClose}
      footer={<><Button variant="ghost" onClick={onClose}>Cancel</Button><Button loading={busy} onClick={save}>Apply adjustment</Button></>}>
      <div className="mb-4 grid grid-cols-3 gap-3 text-center">
        {[['On hand', row.quantity], ['Reserved', row.reserved], ['After change', row.quantity + (Number(delta) || 0)]].map(([k, v]) => (
          <div key={k} className="rounded-lg bg-slate-50 px-3 py-2.5"><p className="text-[11px] uppercase tracking-wide text-slate-500">{k}</p><p className="num mt-0.5 text-lg font-bold text-slate-900">{v}</p></div>
        ))}
      </div>
      <div className="grid gap-4">
        <Field label="Change in units" hint="Positive to receive stock, negative to write off. Cannot go below reserved."><input className="input" type="number" autoFocus value={delta} onChange={(e) => setDelta(e.target.value)} /></Field>
        <Field label="Reason"><input className="input" value={reason} maxLength={120} onChange={(e) => setReason(e.target.value)} /></Field>
      </div>
    </Modal>
  );
}

function Content({ user }) {
  const warehouses = useAsync(() => api('/warehouses'));
  const stock = useAsync(() => api('/inventory'));
  const [wh, setWh] = useState('');
  const [lowOnly, setLowOnly] = useState(false);
  const [search, setSearch] = useState('');
  const [adjusting, setAdjusting] = useState(null);
  const rows = useMemo(() => (stock.data || []).filter((r) => (!wh || r.warehouse_id === Number(wh)) && (!lowOnly || r.low) && `${r.product} ${r.sku}`.toLowerCase().includes(search.toLowerCase())), [stock.data, wh, lowOnly, search]);
  if (warehouses.loading || stock.loading) return <Loading />;
  if (warehouses.error || stock.error) return <ErrorBox error={warehouses.error || stock.error} onRetry={() => { warehouses.reload(); stock.reload(); }} />;
  const refresh = () => { warehouses.reload(true); stock.reload(true); };

  return (
    <>
      <PageHeader title="Inventory" subtitle="Stock on hand and reserved against open fulfilment orders, by warehouse." />
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {warehouses.data.map((w) => (
          <button key={w.id} onClick={() => setWh(wh === String(w.id) ? '' : String(w.id))}
            className={`rounded-xl border bg-white p-4 text-left shadow-card transition hover:border-brand-300 ${wh === String(w.id) ? 'border-brand-500 ring-2 ring-brand-500/20' : 'border-slate-200'}`}>
            <div className="flex items-center justify-between"><p className="text-sm font-semibold text-slate-900">{w.name}</p><Badge>{w.code}</Badge></div>
            <p className="mt-0.5 text-xs text-slate-500">{w.city} · {w.region} · {w.lead_days}d lead · {inr(w.base_shipping_fee)} + {inr(w.per_unit_shipping)}/unit</p>
            <div className="mt-3 flex items-end justify-between">
              <div><p className="num font-display text-2xl font-bold text-slate-900">{w.units_on_hand.toLocaleString('en-IN')}</p><p className="text-xs text-slate-500">units · {w.units_reserved} reserved</p></div>
              {w.low_stock > 0 && <Badge tone="rose">{w.low_stock} low</Badge>}
            </div>
          </button>
        ))}
      </div>

      <div className="mb-3 mt-6 flex flex-wrap items-center gap-3">
        <input className="input max-w-xs" placeholder="Search product or SKU…" value={search} onChange={(e) => setSearch(e.target.value)} aria-label="Search stock" />
        <label className="flex items-center gap-2 text-sm text-slate-700"><input type="checkbox" className="h-4 w-4 rounded border-slate-300 text-brand-600" checked={lowOnly} onChange={(e) => setLowOnly(e.target.checked)} /> Low stock only</label>
        {wh && <Button variant="ghost" size="sm" onClick={() => setWh('')}>Clear warehouse filter ✕</Button>}
        <span className="ml-auto text-xs text-slate-500">{rows.length} stock positions</span>
      </div>
      <Card padded={false}>
        <Table rows={rows} empty="No stock positions match" columns={[
          { key: 'product', label: 'Product', render: (r) => <><p className="font-medium text-slate-900">{r.product}</p><p className="text-xs text-slate-500">{r.sku} · {r.category}</p></> },
          { key: 'warehouse', label: 'Warehouse', render: (r) => <Badge>{r.warehouse}</Badge> },
          { key: 'quantity', label: 'On hand', right: true },
          { key: 'reserved', label: 'Reserved', right: true, render: (r) => (r.reserved ? r.reserved : <span className="text-slate-300">0</span>) },
          { key: 'available', label: 'Available', right: true, render: (r) => <b className={r.low ? 'text-rose-600' : 'text-slate-900'}>{r.available}</b> },
          { key: 'reorder_level', label: 'Reorder at', right: true },
          { key: 'state', label: '', render: (r) => (r.low ? <Badge tone="rose" dot>Low</Badge> : <Badge tone="emerald" dot>OK</Badge>) },
          ...(can.manage(user) ? [{ key: 'act', label: '', right: true, render: (r) => <Button size="sm" variant="secondary" onClick={() => setAdjusting(r)}>Adjust</Button> }] : []),
        ]} />
      </Card>
      {adjusting && <AdjustModal row={adjusting} warehouses={warehouses.data} onClose={() => setAdjusting(null)} onDone={() => { setAdjusting(null); refresh(); }} />}
    </>
  );
}

export default function Inventory() {
  return <AppShell page="inventory">{(user) => <Content user={user} />}</AppShell>;
}
