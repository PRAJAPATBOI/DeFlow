import { useEffect, useState } from 'react';
import { Badge, Button, Card, Empty, ErrorBox, Field, Loading, Modal, StatusBadge, Table, Toaster, act, toast, useAsync } from '../components/ui.jsx';
import { api, getSession, logout } from '../lib/api.js';
import { PERIOD, fmtDate, fmtDateTime, inr, inr2, queryParam } from '../lib/format.js';
import { InvoiceDocument } from './Invoices.jsx';

function Frame({ session, children }) {
  return (
    <div className="min-h-screen">
      <header className="no-print border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-5xl items-center justify-between px-5 py-3.5">
          <a href="/portal" className="flex items-center gap-2.5">
            <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-to-br from-brand-500 to-cyan-400"><svg width="18" height="18" viewBox="0 0 32 32" fill="none"><path d="M8 22l6-7 4 3 6-9" stroke="#fff" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" /></svg></span>
            <span className="font-display font-extrabold text-slate-900">DealFlow<span className="text-brand-600">360</span> <span className="ml-1 text-xs font-medium text-slate-400">Customer portal</span></span>
          </a>
          {session ? <div className="flex items-center gap-3 text-sm"><span className="hidden text-slate-500 sm:inline">{session.user.name}</span><Button size="sm" variant="secondary" onClick={logout}>Sign out</Button></div>
            : <a href="/login" className="text-sm font-semibold text-brand-600 hover:underline">Sign in</a>}
        </div>
      </header>
      <main className="animate-fade-up mx-auto max-w-5xl px-5 py-8">{children}</main>
      <Toaster />
    </div>
  );
}

function QuoteView({ token, session }) {
  const { data: q, loading, error, reload } = useAsync(() => api(`/portal/quotes/${token}`, { auth: false }), [token]);
  const [quote, setQuote] = useState(null);
  const [dialog, setDialog] = useState(null);
  const [form, setForm] = useState({ name: session?.user.name || '', reason: '', message: '', proposed_discount: '' });
  const [busy, setBusy] = useState(false);
  useEffect(() => { if (q) { setQuote(q); setForm((f) => ({ ...f, name: f.name || q.customer?.contact_name || '' })); } }, [q]);

  if (loading && !quote) return <Loading />;
  if (error) return <Card><Empty title="This quotation isn’t available" hint={error.message} action={<Button variant="secondary" onClick={() => { window.location.href = '/portal'; }}>Go to portal home</Button>} /></Card>;
  if (!quote) return <Loading />;

  async function submit() {
    const name = form.name.trim() || 'Customer';
    let call;
    if (dialog === 'accept') call = api(`/portal/quotes/${token}/accept`, { method: 'POST', auth: false, body: { name } });
    if (dialog === 'decline') call = api(`/portal/quotes/${token}/decline`, { method: 'POST', auth: false, body: { name, reason: form.reason.trim() || null } });
    if (dialog === 'counter') {
      const d = Number(form.proposed_discount);
      if (!(d > 0 && d <= 90)) return toast('Enter the discount % you are asking for (1–90)', 'error');
      call = api(`/portal/quotes/${token}/messages`, { method: 'POST', auth: false, body: { name, message: form.message.trim() || `We would like ${d}% off to proceed.`, proposed_discount: d } });
    }
    if (dialog === 'message') {
      if (!form.message.trim()) return toast('Write a message first', 'error');
      call = api(`/portal/quotes/${token}/messages`, { method: 'POST', auth: false, body: { name, message: form.message.trim() } });
    }
    setBusy(true);
    const result = await act(call, { accept: 'Quotation accepted — thank you!', decline: 'Quotation declined', counter: 'Counter-offer sent', message: 'Message sent' }[dialog]);
    setBusy(false);
    if (result) { setQuote(result); setDialog(null); setForm((f) => ({ ...f, message: '', proposed_discount: '', reason: '' })); }
  }

  const p = quote.pricing;
  const openOffer = quote.messages.find((m) => m.offer_status === 'open');
  const titles = { accept: 'Accept this quotation', decline: 'Decline this quotation', counter: 'Propose a counter-offer', message: 'Send a message' };
  return (
    <>
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wider text-slate-400">Quotation from {quote.seller}</p>
          <h1 className="mt-1 text-2xl font-bold text-slate-900">{quote.title}</h1>
          <p className="mt-1 text-sm text-slate-500">{quote.number}{quote.version > 1 ? ` · revision ${quote.version}` : ''} · prepared for {quote.customer.name} by {quote.rep_name} · valid until {fmtDate(quote.valid_until)}</p>
        </div>
        <div className="flex items-center gap-2"><StatusBadge status={quote.status} /><Button variant="ghost" size="sm" className="no-print" onClick={() => window.print()}>Print / PDF</Button></div>
      </div>

      {quote.status === 'accepted' && <p className="mt-5 rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">✓ You accepted this quotation. Your order is being prepared and invoices have been issued.</p>}
      {quote.under_revision && <p className="mt-5 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">Your requested pricing is with {quote.seller} for internal approval. You’ll be able to accept the revised quotation here once it’s confirmed.</p>}
      {quote.status === 'expired' && <p className="mt-5 rounded-xl border border-slate-200 bg-slate-100 px-4 py-3 text-sm text-slate-700">This quotation expired on {fmtDate(quote.valid_until)}. Contact {quote.rep_email} for a fresh quote.</p>}
      {quote.can_respond && quote.days_to_expiry != null && quote.days_to_expiry <= 5 && <p className="mt-5 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">This offer expires in {Math.max(quote.days_to_expiry, 0)} day(s).</p>}

      <div className="mt-6 grid gap-6 lg:grid-cols-[1fr_300px]">
        <div className="space-y-6">
          <Card title="What’s included" padded={false}>
            <div className="scroll-thin overflow-x-auto">
              <table className="min-w-full divide-y divide-slate-100">
                <thead className="bg-slate-50/70"><tr><th className="th">Item</th><th className="th text-right">Unit price</th><th className="th text-right">Qty</th><th className="th text-right">Discount</th><th className="th text-right">Amount</th></tr></thead>
                <tbody className="divide-y divide-slate-100">
                  {quote.lines.map((l) => (
                    <tr key={l.id}>
                      <td className="td"><p className="font-medium text-slate-900">{l.name}</p><p className="text-xs text-slate-500">{l.sku}{l.is_subscription ? ` · billed per ${PERIOD[l.billing_period]}` : ''}</p></td>
                      <td className="td num text-right">{inr(l.unit_price)}</td><td className="td num text-right">{l.quantity}</td>
                      <td className="td num text-right">{l.discount_percent ? `${l.discount_percent}%` : '—'}</td>
                      <td className="td num text-right font-semibold text-slate-900">{inr2(l.line_total)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {quote.notes && <p className="border-t border-slate-100 px-5 py-4 text-sm text-slate-600"><b className="text-slate-800">Notes:</b> {quote.notes}</p>}
          </Card>

          <Card title="Conversation" className="no-print" action={quote.can_respond && <Button size="sm" variant="secondary" onClick={() => setDialog('message')}>Send a message</Button>}>
            {quote.messages.length === 0 ? <p className="text-sm text-slate-500">No messages yet. Questions about this quotation? Send {quote.rep_name} a message.</p> : (
              <ul className="space-y-3">
                {quote.messages.map((m) => (
                  <li key={m.id} className={`flex ${m.side === 'customer' ? 'justify-end' : 'justify-start'}`}>
                    <div className={`max-w-[85%] rounded-2xl px-4 py-2.5 text-sm ${m.side === 'customer' ? 'rounded-br-sm bg-brand-600 text-white' : 'rounded-bl-sm bg-slate-100 text-slate-800'}`}>
                      <p className={`mb-0.5 text-[11px] font-semibold ${m.side === 'customer' ? 'text-brand-100' : 'text-slate-500'}`}>{m.author_name} · {fmtDateTime(m.created_at)}</p>
                      <p className="whitespace-pre-wrap">{m.message}</p>
                      {m.proposed_discount != null && <p className="mt-1.5"><Badge tone={m.offer_status === 'accepted' ? 'emerald' : m.offer_status === 'rejected' ? 'rose' : 'amber'}>Counter-offer {m.proposed_discount}% · {m.offer_status === 'open' ? 'awaiting reply' : m.offer_status}</Badge></p>}
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>

        <aside className="space-y-4">
          <Card title="Total">
            <dl className="space-y-2 text-sm">
              <div className="flex justify-between text-slate-600"><dt>Subtotal</dt><dd className="num">{inr2(p.subtotal)}</dd></div>
              {p.discount_total > 0 && <div className="flex justify-between text-emerald-700"><dt>Discount</dt><dd className="num">− {inr2(p.discount_total)}</dd></div>}
              <div className="flex justify-between text-slate-600"><dt>GST</dt><dd className="num">{inr2(p.tax_total)}</dd></div>
              <div className="flex justify-between border-t border-slate-200 pt-3 text-lg font-bold text-slate-900"><dt>Total</dt><dd className="num">{inr2(p.total)}</dd></div>
              {p.recurring_total > 0 && <p className="pt-1 text-xs text-slate-500">Includes {inr(p.recurring_total)} of recurring services (first period shown; the first invoice is pro-rated).</p>}
              <p className="text-xs text-slate-500">Payment terms: net {quote.payment_terms_days} days</p>
            </dl>
          </Card>
          {quote.can_respond && (
            <div className="no-print space-y-2">
              <Button size="lg" variant="success" className="w-full" onClick={() => setDialog('accept')}>Accept quotation</Button>
              <Button variant="secondary" className="w-full" disabled={!!openOffer} title={openOffer ? 'You already have a counter-offer awaiting a reply' : ''} onClick={() => setDialog('counter')}>{openOffer ? 'Counter-offer pending' : 'Negotiate price'}</Button>
              <Button variant="ghost" className="w-full" onClick={() => setDialog('decline')}>Decline</Button>
            </div>
          )}
        </aside>
      </div>

      {dialog && (
        <Modal open title={titles[dialog]} subtitle={`${quote.number} · ${inr2(p.total)}`} onClose={() => setDialog(null)}
          footer={<><Button variant="ghost" onClick={() => setDialog(null)}>Cancel</Button><Button variant={dialog === 'accept' ? 'success' : dialog === 'decline' ? 'danger' : 'primary'} loading={busy} onClick={submit}>{{ accept: 'Confirm acceptance', decline: 'Decline quotation', counter: 'Send counter-offer', message: 'Send' }[dialog]}</Button></>}>
          <div className="grid gap-4">
            <Field label="Your name"><input className="input" value={form.name} maxLength={120} onChange={(e) => setForm({ ...form, name: e.target.value })} /></Field>
            {dialog === 'accept' && <p className="text-sm text-slate-600">By accepting you confirm the order for <b>{inr2(p.total)}</b> on net-{quote.payment_terms_days} terms. {quote.seller} will reserve stock and issue invoices immediately.</p>}
            {dialog === 'decline' && <Field label="Reason (optional)"><textarea className="input" rows={2} value={form.reason} maxLength={255} onChange={(e) => setForm({ ...form, reason: e.target.value })} /></Field>}
            {dialog === 'counter' && <Field label="Discount you’re asking for (%)" hint="Applied across all items. The seller can accept or decline."><input className="input" type="number" min="1" max="90" step="0.5" autoFocus value={form.proposed_discount} onChange={(e) => setForm({ ...form, proposed_discount: e.target.value })} /></Field>}
            {['counter', 'message'].includes(dialog) && <Field label="Message"><textarea className="input" rows={3} value={form.message} maxLength={2000} onChange={(e) => setForm({ ...form, message: e.target.value })} /></Field>}
          </div>
        </Modal>
      )}
    </>
  );
}

function Home() {
  const { data, loading, error, reload } = useAsync(() => api('/portal/my/overview'));
  const [invoice, setInvoice] = useState(null);
  if (loading) return <Loading />;
  if (error) return <ErrorBox error={error} onRetry={reload} />;
  const due = data.invoices.reduce((a, i) => a + i.balance, 0);
  const waiting = data.quotations.filter((q) => ['sent', 'negotiating'].includes(q.status));
  return (
    <>
      <h1 className="text-2xl font-bold text-slate-900">{data.company}</h1>
      <p className="mt-1 text-sm text-slate-500">{waiting.length ? `${waiting.length} quotation(s) waiting for your response.` : 'No quotations need your attention right now.'} Outstanding balance: <b className="text-slate-800">{inr(due)}</b></p>
      <Card title="Quotations" className="mt-6" padded={false}>
        <Table rows={data.quotations} empty="No quotations have been shared with you yet" onRowClick={(q) => { window.location.href = `/portal?token=${q.portal_token}`; }} columns={[
          { key: 'title', label: 'Quotation', render: (q) => <><p className="font-semibold text-slate-900">{q.title}</p><p className="text-xs text-slate-500">{q.number} · from {q.rep_name}</p></> },
          { key: 'status', label: 'Status', render: (q) => <StatusBadge status={q.status} /> },
          { key: 'valid_until', label: 'Valid until', render: (q) => fmtDate(q.valid_until) },
          { key: 'total', label: 'Total', right: true, render: (q) => <b className="text-slate-900">{inr(q.total)}</b> },
          { key: 'go', label: '', right: true, render: () => <span className="text-sm font-semibold text-brand-600">Review →</span> },
        ]} />
      </Card>
      <Card title="Invoices" className="mt-6" padded={false}>
        <Table rows={data.invoices} empty="No invoices yet" onRowClick={setInvoice} columns={[
          { key: 'number', label: 'Invoice', render: (i) => <span className="font-semibold text-slate-900">{i.number}</span> },
          { key: 'issue_date', label: 'Issued', render: (i) => fmtDate(i.issue_date) },
          { key: 'due_date', label: 'Due', render: (i) => fmtDate(i.due_date) },
          { key: 'status', label: 'Status', render: (i) => <StatusBadge status={i.status} /> },
          { key: 'total', label: 'Total', right: true, render: (i) => inr(i.total) },
          { key: 'balance', label: 'Balance', right: true, render: (i) => <b>{inr(i.balance)}</b> },
        ]} />
      </Card>
      {invoice && <Modal open wide title={`Invoice ${invoice.number}`} subtitle={<StatusBadge status={invoice.status} />} onClose={() => setInvoice(null)} footer={<Button variant="secondary" onClick={() => window.print()}>Print</Button>}><InvoiceDocument inv={invoice} /></Modal>}
    </>
  );
}

export default function Portal() {
  const [state, setState] = useState(null);
  useEffect(() => {
    const token = queryParam('token');
    const session = getSession();
    if (!token && !session?.token) { window.location.replace('/login'); return; }
    if (!token && session.user.role !== 'customer') { window.location.replace('/'); return; }
    setState({ token, session: session?.user.role === 'customer' ? session : null });
  }, []);
  if (!state) return <Loading />;
  return <Frame session={state.session}>{state.token ? <QuoteView token={state.token} session={state.session} /> : <Home />}</Frame>;
}
