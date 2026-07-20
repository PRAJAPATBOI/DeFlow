import { useState } from 'react';
import AppShell from '../components/AppShell.jsx';
import { Button, Card, ErrorBox, Field, Loading, Modal, PageHeader, Stat, StatusBadge, Table, act, toast, useAsync } from '../components/ui.jsx';
import { api, can } from '../lib/api.js';
import { PERIOD, fmtDate, inr, inrShort } from '../lib/format.js';

function Content({ user }) {
  const { data, loading, error, reload } = useAsync(() => api('/subscriptions'));
  const [run, setRun] = useState(null);
  const [busy, setBusy] = useState('');
  if (loading) return <Loading />;
  if (error) return <ErrorBox error={error} onRetry={reload} />;
  const { summary: s, subscriptions } = data;
  const finance = can.finance(user);

  async function change(sub, action) {
    if (action === 'cancel' && !window.confirm(`Cancel ${sub.product} for ${sub.customer_name}? Billing stops immediately.`)) return;
    setBusy(`${sub.id}:${action}`);
    await act(api(`/subscriptions/${sub.id}/${action}`, { method: 'POST' }), `Subscription ${action}${action === 'cancel' ? 'led' : 'd'}`);
    setBusy('');
    reload(true);
  }
  async function runBilling() {
    setBusy('run');
    const result = await act(api('/subscriptions/run-billing', { method: 'POST', body: { as_of: run.as_of || null } }));
    setBusy('');
    if (result) {
      toast(result.invoices_created ? `${result.invoices_created} invoice(s) raised · ${inr(result.total_billed)}` : 'Nothing was due — no invoices raised');
      setRun(null);
      reload(true);
    }
  }

  return (
    <>
      <PageHeader title="Subscriptions" subtitle="Recurring lines from won deals. Billing is anchored to the 1st; the first period is pro-rated by day.">
        {finance && <Button onClick={() => setRun({ as_of: new Date().toISOString().slice(0, 10) })}>Run billing cycle</Button>}
      </PageHeader>
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Stat label="MRR" value={inrShort(s.mrr)} hint="Monthly recurring revenue" />
        <Stat label="ARR" value={inrShort(s.arr)} hint="Annualised run-rate" />
        <Stat label="Active" value={s.active} hint={`${s.paused} paused · ${s.cancelled} cancelled`} />
        <Stat label="Due for billing" value={s.due_now} hint={s.due_now ? 'Run the billing cycle' : 'Up to date'} />
      </div>
      <Card padded={false} className="mt-6">
        <Table rows={subscriptions} empty="No subscriptions yet" columns={[
          { key: 'product', label: 'Subscription', render: (r) => <><p className="font-semibold text-slate-900">{r.product}</p><p className="text-xs text-slate-500">{r.sku} · {r.quotation_number}</p></> },
          { key: 'customer_name', label: 'Customer' },
          { key: 'status', label: 'Status', render: (r) => <StatusBadge status={r.status} /> },
          { key: 'quantity', label: 'Qty', right: true },
          { key: 'period_amount', label: 'Billing', right: true, render: (r) => <>{inr(r.period_amount)}<span className="text-xs text-slate-400"> /{PERIOD[r.billing_period]}</span></> },
          { key: 'mrr', label: 'MRR', right: true, render: (r) => (r.mrr ? inr(r.mrr) : <span className="text-slate-300">—</span>) },
          { key: 'start_date', label: 'Started', render: (r) => fmtDate(r.start_date) },
          { key: 'next_billing_date', label: 'Next bill', render: (r) => fmtDate(r.next_billing_date) },
          ...(finance ? [{ key: 'actions', label: '', right: true, render: (r) => (
            <span className="inline-flex gap-1.5">
              {r.status === 'active' && <Button size="sm" variant="secondary" loading={busy === `${r.id}:pause`} onClick={() => change(r, 'pause')}>Pause</Button>}
              {r.status === 'paused' && <Button size="sm" variant="secondary" loading={busy === `${r.id}:resume`} onClick={() => change(r, 'resume')}>Resume</Button>}
              {r.status !== 'cancelled' && <Button size="sm" variant="ghost" loading={busy === `${r.id}:cancel`} onClick={() => change(r, 'cancel')}>Cancel</Button>}
            </span>
          ) }] : []),
        ]} />
      </Card>
      {run && (
        <Modal open title="Run billing cycle" subtitle="Raises an invoice for every active subscription whose next billing date has arrived." onClose={() => setRun(null)}
          footer={<><Button variant="ghost" onClick={() => setRun(null)}>Cancel</Button><Button loading={busy === 'run'} onClick={runBilling}>Raise invoices</Button></>}>
          <Field label="Bill everything due on or before" hint="Pick a future date to simulate upcoming cycles. Running twice never double-bills.">
            <input className="input" type="date" value={run.as_of} onChange={(e) => setRun({ as_of: e.target.value })} />
          </Field>
        </Modal>
      )}
    </>
  );
}

export default function Subscriptions() {
  return <AppShell page="subscriptions">{(user) => <Content user={user} />}</AppShell>;
}
