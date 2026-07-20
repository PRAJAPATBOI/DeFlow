import { useState } from 'react';
import AppShell from '../components/AppShell.jsx';
import { Badge, Button, Card, Empty, ErrorBox, Loading, PageHeader, Stat, StatusBadge, Tabs, act, toast, useAsync } from '../components/ui.jsx';
import { api, can } from '../lib/api.js';
import { fmtDate, inr } from '../lib/format.js';

const NEXT = { planned: 'Start picking', picking: 'Mark shipped', shipped: 'Mark delivered' };
const STEPS = ['planned', 'picking', 'shipped', 'delivered'];

function Progress({ status }) {
  const at = STEPS.indexOf(status);
  return (
    <div className="flex items-center gap-1" aria-label={`Status: ${status}`}>
      {STEPS.map((s, i) => <span key={s} title={s} className={`h-1.5 flex-1 rounded-full ${i <= at ? 'bg-brand-500' : 'bg-slate-200'}`} />)}
    </div>
  );
}

function Content({ user }) {
  const { data, loading, error, reload } = useAsync(() => api('/fulfillment/orders'));
  const [tab, setTab] = useState('active');
  const [busy, setBusy] = useState(null);
  if (loading) return <Loading />;
  if (error) return <ErrorBox error={error} onRetry={reload} />;

  const groups = {
    active: data.filter((o) => ['planned', 'picking', 'shipped'].includes(o.status)),
    backorder: data.filter((o) => o.status === 'backorder'),
    delivered: data.filter((o) => o.status === 'delivered'),
  };
  async function advance(o) {
    setBusy(o.id);
    await act(api(`/fulfillment/orders/${o.id}/advance`, { method: 'POST' }), `${o.number} updated`);
    setBusy(null);
    reload(true);
  }
  async function allocate(o) {
    setBusy(o.id);
    const r = await act(api(`/fulfillment/orders/${o.id}/allocate`, { method: 'POST' }));
    setBusy(null);
    if (r) toast(r.created.length ? `Released ${r.created.length} shipment(s)${r.remaining_backorder ? ' — some units still on backorder' : ''}` : 'Still no stock available for this backorder', r.created.length ? 'success' : 'error');
    reload(true);
  }

  return (
    <>
      <PageHeader title="Fulfilment" subtitle="Won deals are split across warehouses automatically: fewest shipments first, then cheapest freight." />
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Stat label="To pick" value={data.filter((o) => o.status === 'planned').length} hint="Planned, stock reserved" />
        <Stat label="In progress" value={data.filter((o) => ['picking', 'shipped'].includes(o.status)).length} hint="Picking or in transit" />
        <Stat label="Backorders" value={groups.backorder.length} hint="Waiting for stock" />
        <Stat label="Freight committed" value={inr(groups.active.reduce((a, o) => a + o.shipping_cost, 0))} hint="Open shipments" />
      </div>
      <div className="mt-6"><Tabs value={tab} onChange={setTab} tabs={[{ id: 'active', label: 'Active', count: groups.active.length }, { id: 'backorder', label: 'Backorders', count: groups.backorder.length }, { id: 'delivered', label: 'Delivered', count: groups.delivered.length }]} /></div>

      {groups[tab].length === 0 ? <Card className="mt-4"><Empty title={tab === 'backorder' ? 'No backorders' : 'No orders here'} hint={tab === 'active' ? 'Orders appear when a customer accepts a quotation with physical items.' : undefined} /></Card> : (
        <div className="mt-4 grid gap-4 lg:grid-cols-2">
          {groups[tab].map((o) => (
            <Card key={o.id} padded={false}>
              <div className="p-5">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className="text-sm font-semibold text-slate-900">{o.number} <span className="font-normal text-slate-400">·</span> {o.customer_name}</p>
                    <a href={`/quotation?id=${o.quotation_id}`} className="text-xs text-brand-600 hover:underline">{o.quotation_number}</a>
                  </div>
                  <StatusBadge status={o.status} />
                </div>
                {o.status !== 'backorder' && <div className="mt-3"><Progress status={o.status} /></div>}
                <ul className="mt-3 divide-y divide-slate-100 rounded-lg border border-slate-100 text-sm">
                  {o.lines.map((l) => <li key={l.product_id} className="flex justify-between px-3 py-2"><span className="text-slate-700">{l.product}</span><b className="num">× {l.quantity}</b></li>)}
                </ul>
              </div>
              <div className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-100 bg-slate-50/60 px-5 py-3 text-xs text-slate-600">
                {o.status === 'backorder'
                  ? <span>{o.units} units waiting for stock</span>
                  : <span><Badge>{o.warehouse_code}</Badge> <span className="ml-1">{o.warehouse} · freight {inr(o.shipping_cost)} · {o.status === 'delivered' ? `delivered ${fmtDate(o.delivered_at)}` : `ETA ${fmtDate(o.eta)}`}</span></span>}
                {can.manage(user) && NEXT[o.status] && <Button size="sm" loading={busy === o.id} onClick={() => advance(o)}>{NEXT[o.status]}</Button>}
                {can.manage(user) && o.status === 'backorder' && <Button size="sm" variant="secondary" loading={busy === o.id} onClick={() => allocate(o)}>Retry allocation</Button>}
              </div>
            </Card>
          ))}
        </div>
      )}
    </>
  );
}

export default function Fulfillment() {
  return <AppShell page="fulfillment">{(user) => <Content user={user} />}</AppShell>;
}
