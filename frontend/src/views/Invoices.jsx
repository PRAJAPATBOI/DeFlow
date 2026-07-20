import { useState } from 'react';
import AppShell from '../components/AppShell.jsx';
import { Badge, Button, Card, ErrorBox, Field, Loading, Modal, PageHeader, Stat, StatusBadge, Table, Tabs, act, useAsync } from '../components/ui.jsx';
import { api, can } from '../lib/api.js';
import { fmtDate, fmtDateTime, inr, inr2, inrShort } from '../lib/format.js';

export function InvoiceDocument({ inv }) {
  return (
    <div>
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="text-xs uppercase tracking-wide text-slate-500">Billed to</p>
          <p className="text-sm font-semibold text-slate-900">{inv.customer_name}</p>
          <p className="text-xs text-slate-500">{inv.quotation_number ? `Against ${inv.quotation_number}` : ''}{inv.period_start ? ` · Service period ${fmtDate(inv.period_start)} – ${fmtDate(inv.period_end)}` : ''}</p>
        </div>
        <dl className="text-right text-xs text-slate-600">
          <div><dt className="inline">Issued </dt><dd className="inline font-semibold text-slate-900">{fmtDate(inv.issue_date)}</dd></div>
          <div><dt className="inline">Due </dt><dd className="inline font-semibold text-slate-900">{fmtDate(inv.due_date)}</dd></div>
          {inv.days_overdue > 0 && <div className="font-semibold text-rose-600">{inv.days_overdue} days overdue</div>}
        </dl>
      </div>
      <table className="mt-4 min-w-full divide-y divide-slate-100 text-sm">
        <thead><tr><th className="th pl-0">Description</th><th className="th text-right">Qty</th><th className="th text-right">Rate</th><th className="th text-right">GST</th><th className="th pr-0 text-right">Amount</th></tr></thead>
        <tbody className="divide-y divide-slate-100">
          {inv.lines.map((l, i) => (
            <tr key={i}><td className="td pl-0">{l.description}</td><td className="td num text-right">{l.quantity}</td><td className="td num text-right">{inr2(l.unit_price)}</td><td className="td num text-right">{l.tax_rate}%</td><td className="td num pr-0 text-right font-medium text-slate-900">{inr2(l.amount)}</td></tr>
          ))}
        </tbody>
      </table>
      <dl className="ml-auto mt-3 w-64 space-y-1.5 text-sm">
        <div className="flex justify-between text-slate-600"><dt>Subtotal</dt><dd className="num">{inr2(inv.subtotal)}</dd></div>
        <div className="flex justify-between text-slate-600"><dt>GST</dt><dd className="num">{inr2(inv.tax_total)}</dd></div>
        <div className="flex justify-between border-t border-slate-200 pt-2 font-bold text-slate-900"><dt>Total</dt><dd className="num">{inr2(inv.total)}</dd></div>
        <div className="flex justify-between text-emerald-700"><dt>Paid</dt><dd className="num">− {inr2(inv.amount_paid)}</dd></div>
        <div className="flex justify-between rounded-lg bg-slate-900 px-3 py-2 font-bold text-white"><dt>Balance due</dt><dd className="num">{inr2(inv.balance)}</dd></div>
      </dl>
      {inv.payments.length > 0 && (
        <div className="mt-5">
          <p className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-slate-500">Payments received</p>
          <ul className="divide-y divide-slate-100 rounded-lg border border-slate-200 text-sm">
            {inv.payments.map((p) => <li key={p.id} className="flex justify-between px-3 py-2"><span className="text-slate-600">{fmtDateTime(p.paid_at)} · {p.method.replace('_', ' ')}{p.reference ? ` · ${p.reference}` : ''}</span><b className="num text-slate-900">{inr2(p.amount)}</b></li>)}
          </ul>
        </div>
      )}
    </div>
  );
}

function InvoiceModal({ id, user, onClose, onChanged }) {
  const { data: inv, loading, error, reload } = useAsync(() => api(`/invoices/${id}`), [id]);
  const [pay, setPay] = useState(null);
  const [busy, setBusy] = useState('');
  const open = inv && inv.balance > 0 && inv.status !== 'void';
  async function record(e) {
    e.preventDefault();
    setBusy('pay');
    const ok = await act(api(`/invoices/${id}/payments`, { method: 'POST', body: { amount: Number(pay.amount), method: pay.method, reference: pay.reference || null } }), 'Payment recorded');
    setBusy('');
    if (ok) { setPay(null); reload(true); onChanged(); }
  }
  async function voidIt() {
    if (!window.confirm(`Void ${inv.number}? This cannot be undone.`)) return;
    setBusy('void');
    const ok = await act(api(`/invoices/${id}/void`, { method: 'POST' }), 'Invoice voided');
    setBusy('');
    if (ok) { reload(true); onChanged(); }
  }
  return (
    <Modal open wide title={inv ? `Invoice ${inv.number}` : 'Invoice'} subtitle={inv && <StatusBadge status={inv.status} />} onClose={onClose}
      footer={inv && <>
        <Button variant="ghost" onClick={() => window.print()}>Print</Button>
        {can.finance(user) && open && inv.amount_paid === 0 && <Button variant="secondary" loading={busy === 'void'} onClick={voidIt}>Void</Button>}
        {can.finance(user) && open && !pay && <Button onClick={() => setPay({ amount: inv.balance, method: 'bank_transfer', reference: '' })}>Record payment</Button>}
      </>}>
      {loading ? <Loading /> : error ? <ErrorBox error={error} /> : (
        <>
          <InvoiceDocument inv={inv} />
          {pay && (
            <form onSubmit={record} className="mt-5 grid gap-3 rounded-xl border border-brand-200 bg-brand-50/50 p-4 sm:grid-cols-4">
              <Field label="Amount (₹)"><input className="input" type="number" required min="0.01" max={inv.balance} step="0.01" autoFocus value={pay.amount} onChange={(e) => setPay({ ...pay, amount: e.target.value })} /></Field>
              <Field label="Method"><select className="input" value={pay.method} onChange={(e) => setPay({ ...pay, method: e.target.value })}>{['bank_transfer', 'upi', 'card', 'cheque', 'cash'].map((m) => <option key={m} value={m}>{m.replace('_', ' ')}</option>)}</select></Field>
              <Field label="Reference / UTR"><input className="input" value={pay.reference} onChange={(e) => setPay({ ...pay, reference: e.target.value })} /></Field>
              <div className="flex items-end gap-2"><Button type="submit" loading={busy === 'pay'}>Save</Button><Button type="button" variant="ghost" onClick={() => setPay(null)}>Cancel</Button></div>
            </form>
          )}
        </>
      )}
    </Modal>
  );
}

function Content({ user }) {
  const { data, loading, error, reload } = useAsync(() => api('/invoices'));
  const [tab, setTab] = useState('all');
  const [viewing, setViewing] = useState(null);
  if (loading) return <Loading />;
  if (error) return <ErrorBox error={error} onRetry={reload} />;
  const { summary: s, invoices } = data;
  const filters = { all: () => true, open: (i) => ['issued', 'partially_paid'].includes(i.status), overdue: (i) => i.status === 'overdue', paid: (i) => i.status === 'paid' };
  const rows = invoices.filter(filters[tab]);
  const rate = s.billed ? Math.round((s.collected / s.billed) * 100) : 0;
  return (
    <>
      <PageHeader title="Invoices" subtitle="Raised automatically when a deal is won and on every subscription billing run." />
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Stat label="Billed" value={inrShort(s.billed)} hint={`${invoices.length} invoices`} />
        <Stat label="Collected" value={inrShort(s.collected)} hint={`${rate}% collection rate`} />
        <Stat label="Outstanding" value={inrShort(s.outstanding)} hint="Awaiting payment" />
        <Stat label="Overdue" value={inrShort(s.overdue)} hint={s.overdue > 0 ? 'Past due date' : 'All current'} />
      </div>
      <div className="mt-6"><Tabs value={tab} onChange={setTab} tabs={Object.keys(filters).map((k) => ({ id: k, label: k[0].toUpperCase() + k.slice(1), count: invoices.filter(filters[k]).length }))} /></div>
      <Card padded={false} className="mt-4">
        <Table rows={rows} onRowClick={(i) => setViewing(i.id)} empty="No invoices in this view" columns={[
          { key: 'number', label: 'Invoice', render: (i) => <><p className="font-semibold text-slate-900">{i.number}</p><p className="text-xs text-slate-500">{i.quotation_number}</p></> },
          { key: 'customer_name', label: 'Customer' },
          { key: 'kind', label: 'Type', render: (i) => <Badge tone={i.kind === 'recurring' ? 'indigo' : 'slate'}>{i.kind === 'recurring' ? 'Recurring' : 'One-time'}</Badge> },
          { key: 'issue_date', label: 'Issued', render: (i) => fmtDate(i.issue_date) },
          { key: 'due_date', label: 'Due', render: (i) => <span className={i.status === 'overdue' ? 'font-semibold text-rose-600' : ''}>{fmtDate(i.due_date)}</span> },
          { key: 'status', label: 'Status', render: (i) => <StatusBadge status={i.status} /> },
          { key: 'total', label: 'Total', right: true, render: (i) => inr(i.total) },
          { key: 'balance', label: 'Balance', right: true, render: (i) => <b className={i.balance > 0 ? 'text-slate-900' : 'text-slate-300'}>{inr(i.balance)}</b> },
        ]} />
      </Card>
      {viewing && <InvoiceModal id={viewing} user={user} onClose={() => setViewing(null)} onChanged={() => reload(true)} />}
    </>
  );
}

export default function Invoices() {
  return <AppShell page="invoices">{(user) => <Content user={user} />}</AppShell>;
}
