import { useEffect, useState } from 'react';
import AppShell from '../components/AppShell.jsx';
import { RiskGauge } from '../components/charts.jsx';
import { Badge, Button, Card, Empty, ErrorBox, Field, Loading, Modal, StatusBadge, Tabs, act, toast, useAsync } from '../components/ui.jsx';
import { api, can } from '../lib/api.js';
import { EVENT_LABEL, PERIOD, fmtDate, fmtDateTime, inr, inr2, pct, queryParam } from '../lib/format.js';
import QuotationEditor from './QuotationEditor.jsx';

const CLOSED = ['accepted', 'rejected', 'declined', 'lost', 'expired'];

function CommentModal({ config, onClose, onDone }) {
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  useEffect(() => setText(''), [config]);
  if (!config) return null;
  async function go() {
    if (config.required && text.trim().length < 3) return toast('Please add a short comment', 'error');
    setBusy(true);
    const result = await act(api(config.url, { method: 'POST', body: { [config.field || 'comment']: text.trim() || null } }), config.success);
    setBusy(false);
    if (result) onDone(result);
  }
  return (
    <Modal open title={config.title} subtitle={config.subtitle} onClose={onClose}
      footer={<><Button variant="ghost" onClick={onClose}>Cancel</Button><Button variant={config.variant || 'primary'} loading={busy} onClick={go}>{config.cta}</Button></>}>
      <Field label={config.required ? 'Comment (required)' : 'Comment (optional)'}>
        <textarea className="input" rows={3} autoFocus value={text} onChange={(e) => setText(e.target.value)} placeholder={config.placeholder} />
      </Field>
    </Modal>
  );
}

function Negotiation({ quote, user, onChange }) {
  const [impact, setImpact] = useState(null);
  const [reply, setReply] = useState('');
  const [busy, setBusy] = useState('');
  const offer = quote.messages.find((m) => m.offer_status === 'open');
  const live = ['sent', 'negotiating'].includes(quote.status);

  useEffect(() => {
    setImpact(null);
    if (offer) api(`/quotations/${quote.id}/messages/${offer.id}/impact`).then(setImpact).catch(() => {});
  }, [offer?.id, quote.id]); // eslint-disable-line react-hooks/exhaustive-deps

  async function respond(accept) {
    setBusy(accept ? 'accept' : 'reject');
    const result = await act(api(`/quotations/${quote.id}/messages/${offer.id}/respond`, { method: 'POST', body: { accept, comment: reply.trim() || null } }), accept ? 'Counter-offer accepted' : 'Counter-offer declined');
    setBusy('');
    if (result) { setReply(''); onChange(result); }
  }
  async function send() {
    if (!reply.trim()) return;
    setBusy('send');
    const ok = await act(api(`/quotations/${quote.id}/messages`, { method: 'POST', body: { message: reply.trim() } }), 'Message sent');
    setBusy('');
    if (ok) { setReply(''); onChange(); }
  }

  return (
    <div className="space-y-4">
      {offer && can.sell(user) && (
        <div className="rounded-xl border border-violet-200 bg-violet-50/60 p-4">
          <p className="text-sm font-semibold text-violet-900">{offer.author_name} is asking for {offer.proposed_discount}% off</p>
          {impact ? (
            <>
              <div className="mt-3 grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
                {[['New total', inr(impact.new_total)], ['Revenue impact', inr(impact.revenue_delta)], ['Margin', `${pct(impact.current_margin_percent)} → ${pct(impact.new_margin_percent)}`], ['Risk after', `${Math.round(impact.risk.score)} · ${impact.risk.level}`]].map(([k, v]) => (
                  <div key={k} className="rounded-lg bg-white px-3 py-2 ring-1 ring-violet-100"><p className="text-[11px] uppercase tracking-wide text-slate-500">{k}</p><p className="num mt-0.5 font-semibold text-slate-900">{v}</p></div>
                ))}
              </div>
              {impact.needs_reapproval && <p className="mt-3 text-xs font-medium text-amber-800">⚠ Accepting pushes this deal beyond what was approved — it will go back for approval before the customer sees the new price.</p>}
            </>
          ) : <p className="mt-2 text-xs text-slate-500">Calculating impact…</p>}
          <div className="mt-3 flex flex-wrap gap-2">
            <Button variant="success" size="sm" loading={busy === 'accept'} disabled={!!busy} onClick={() => respond(true)}>Accept {offer.proposed_discount}%</Button>
            <Button variant="secondary" size="sm" loading={busy === 'reject'} disabled={!!busy} onClick={() => respond(false)}>Decline, hold price</Button>
          </div>
        </div>
      )}
      {quote.messages.length === 0 ? <Empty title="No conversation yet" hint="Messages and counter-offers from the customer portal appear here." /> : (
        <ul className="space-y-3">
          {quote.messages.map((m) => (
            <li key={m.id} className={`flex ${m.side === 'internal' ? 'justify-end' : 'justify-start'}`}>
              <div className={`max-w-[80%] rounded-2xl px-4 py-2.5 text-sm ${m.side === 'internal' ? 'rounded-br-sm bg-brand-600 text-white' : 'rounded-bl-sm bg-slate-100 text-slate-800'}`}>
                <p className={`mb-0.5 text-[11px] font-semibold ${m.side === 'internal' ? 'text-brand-100' : 'text-slate-500'}`}>{m.author_name} · {fmtDateTime(m.created_at)}</p>
                <p className="whitespace-pre-wrap">{m.message}</p>
                {m.proposed_discount != null && <p className="mt-1.5"><Badge tone={m.offer_status === 'accepted' ? 'emerald' : m.offer_status === 'rejected' ? 'rose' : 'violet'}>Counter-offer {m.proposed_discount}% · {m.offer_status}</Badge></p>}
              </div>
            </li>
          ))}
        </ul>
      )}
      {live && can.sell(user) && (
        <div className="flex gap-2 border-t border-slate-100 pt-4">
          <input className="input" placeholder={offer ? 'Optional note to send with your decision…' : 'Write a message to the customer…'} value={reply} onChange={(e) => setReply(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && !offer && send()} aria-label="Message" />
          {!offer && <Button loading={busy === 'send'} onClick={send}>Send</Button>}
        </div>
      )}
    </div>
  );
}

function FulfilmentPlan({ id }) {
  const { data, loading, error } = useAsync(() => api(`/quotations/${id}/fulfillment-plan`), [id]);
  if (loading) return <Loading />;
  if (error) return <ErrorBox error={error} />;
  if (!data.total_units) return <Empty title="Nothing to ship" hint="This quotation only contains services and subscriptions, which are delivered rather than shipped." />;
  return (
    <div className="space-y-4">
      <p className="text-sm text-slate-600">
        {data.fully_allocated ? <Badge tone="emerald">Fully in stock</Badge> : <Badge tone="rose">Partial — backorder needed</Badge>}
        <span className="ml-2">{data.total_units} units in {data.shipment_count} shipment{data.shipment_count === 1 ? '' : 's'} · est. freight {inr(data.total_shipping_cost)}</span>
      </p>
      <div className="grid gap-3 md:grid-cols-2">
        {data.shipments.map((s, i) => (
          <div key={s.warehouse_id} className="rounded-xl border border-slate-200 p-4">
            <div className="flex items-center justify-between"><p className="text-sm font-semibold text-slate-900">Shipment {i + 1} · {s.warehouse}</p><Badge>{s.code}</Badge></div>
            <p className="mt-0.5 text-xs text-slate-500">{s.city} ({s.region}) · {s.lead_days} day lead time · freight {inr(s.shipping_cost)}</p>
            <ul className="mt-3 space-y-1 text-sm">{s.items.map((it) => <li key={it.product_id} className="flex justify-between"><span className="text-slate-700">{it.product}</span><b className="num">× {it.quantity}</b></li>)}</ul>
          </div>
        ))}
        {data.backorder.length > 0 && (
          <div className="rounded-xl border border-rose-200 bg-rose-50/60 p-4">
            <p className="text-sm font-semibold text-rose-900">Backorder</p>
            <p className="mt-0.5 text-xs text-rose-700">Not available in any warehouse right now.</p>
            <ul className="mt-3 space-y-1 text-sm">{data.backorder.map((it) => <li key={it.product_id} className="flex justify-between"><span>{it.product}</span><b className="num">× {it.quantity}</b></li>)}</ul>
          </div>
        )}
      </div>
      <p className="text-xs text-slate-400">The planner uses the fewest warehouses possible, then the cheapest freight. Stock is reserved when the customer accepts.</p>
    </div>
  );
}

function BillingSchedule({ id }) {
  const { data, loading, error } = useAsync(() => api(`/quotations/${id}/billing-schedule`), [id]);
  if (loading) return <Loading />;
  if (error) return <ErrorBox error={error} />;
  return (
    <div className="space-y-5">
      <div className="grid grid-cols-3 gap-3">
        {[['Upfront (one-time)', inr(data.one_time_total)], ['Monthly recurring', inr(data.mrr)], ['First-year value', inr(data.first_year_value)]].map(([k, v]) => (
          <div key={k} className="rounded-lg bg-slate-50 px-4 py-3"><p className="text-[11px] uppercase tracking-wide text-slate-500">{k}</p><p className="num mt-1 text-lg font-bold text-slate-900">{v}</p></div>
        ))}
      </div>
      {data.subscriptions.length > 0 && (
        <ul className="space-y-2">
          {data.subscriptions.map((s) => (
            <li key={s.product} className="rounded-lg border border-slate-200 px-4 py-3 text-sm">
              <p className="font-semibold text-slate-900">{s.product} <span className="font-normal text-slate-500">· {inr(s.period_amount)} per {PERIOD[s.billing_period]}</span></p>
              <p className="mt-0.5 text-xs text-slate-500">First charge {inr2(s.first_charge)}{s.prorated ? ` (pro-rated for ${s.prorated_days} days)` : ''} · then billed on the 1st from {fmtDate(s.next_billing_date)}</p>
            </li>
          ))}
        </ul>
      )}
      <div>
        <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">Projected invoices if accepted today (incl. GST)</p>
        <ol className="scroll-thin max-h-64 space-y-1 overflow-y-auto">
          {data.timeline.map((t) => (
            <li key={t.date} className="flex items-center justify-between rounded-md px-3 py-1.5 text-sm odd:bg-slate-50">
              <span className="text-slate-600">{fmtDate(t.date)} <span className="ml-2 text-xs text-slate-400">{t.items.length} item{t.items.length === 1 ? '' : 's'}</span></span>
              <b className="num text-slate-900">{inr2(t.amount)}</b>
            </li>
          ))}
        </ol>
      </div>
    </div>
  );
}

function Detail({ quote, user, policy, reload, setQuote }) {
  const [tab, setTab] = useState(quote.has_open_counter ? 'negotiation' : 'items');
  const [modal, setModal] = useState(null);
  const [busy, setBusy] = useState('');
  const base = `/quotations/${quote.id}`;
  const mine = quote.rep_id === user.id;
  const canDecide = (quote.status === 'pending_manager' && ['admin', 'sales_manager'].includes(user.role) && (!mine || user.role === 'admin'))
    || (quote.status === 'pending_finance' && ['admin', 'finance'].includes(user.role));
  const portalUrl = quote.portal_token ? `${window.location.origin}/portal?token=${quote.portal_token}` : null;

  async function run(key, path, success) {
    setBusy(key);
    const result = await act(api(base + path, { method: 'POST', body: {} }), success);
    setBusy('');
    if (result) setQuote(result);
  }
  async function revise() {
    setBusy('revise');
    const result = await act(api(`${base}/duplicate`, { method: 'POST' }), 'Revision created');
    if (result) window.location.href = `/quotation?id=${result.id}`;
    else setBusy('');
  }
  const copyLink = () => navigator.clipboard.writeText(portalUrl).then(() => toast('Portal link copied'), () => toast(portalUrl));

  const p = quote.pricing;
  return (
    <>
      <div className="mb-6">
        <a href="/quotations" className="no-print text-xs font-medium text-slate-500 hover:text-brand-600">← All quotations</a>
        <div className="mt-2 flex flex-wrap items-start justify-between gap-4">
          <div>
            <div className="flex flex-wrap items-center gap-2.5">
              <h1 className="text-2xl font-bold text-slate-900">{quote.title}</h1>
              <StatusBadge status={quote.status} />
            </div>
            <p className="mt-1 text-sm text-slate-500">{quote.number}{quote.version > 1 ? ` · v${quote.version}` : ''} · {quote.customer_name} · owned by {quote.rep_name} · valid until {fmtDate(quote.valid_until)}</p>
          </div>
          <div className="no-print flex flex-wrap gap-2">
            {canDecide && <>
              <Button variant="success" onClick={() => setModal({ title: 'Approve quotation', cta: 'Approve', variant: 'success', url: `${base}/approve`, success: 'Approved', placeholder: 'Why is this deal worth the risk?' })}>Approve</Button>
              <Button variant="secondary" onClick={() => setModal({ title: 'Request changes', subtitle: 'Sends the quote back to the rep as a draft.', cta: 'Send back', url: `${base}/request-changes`, required: true, success: 'Sent back to the rep', placeholder: 'What needs to change?' })}>Request changes</Button>
              <Button variant="danger" onClick={() => setModal({ title: 'Reject quotation', cta: 'Reject', variant: 'danger', url: `${base}/reject`, required: true, success: 'Rejected', placeholder: 'Reason for rejecting' })}>Reject</Button>
            </>}
            {quote.status === 'approved' && can.sell(user) && <Button loading={busy === 'send'} onClick={() => run('send', '/send', 'Sent — portal link is ready to share')}>Send to customer</Button>}
            {['sent', 'negotiating'].includes(quote.status) && can.sell(user) && <>
              <Button variant="success" loading={busy === 'won'} onClick={() => window.confirm('Record the customer’s acceptance? This reserves stock and raises invoices.') && run('won', '/mark-won', 'Deal won — orders and invoices created')}>Mark won</Button>
              <Button variant="secondary" onClick={() => setModal({ title: 'Mark as lost', cta: 'Mark lost', variant: 'danger', url: `${base}/mark-lost`, field: 'reason', required: true, success: 'Marked lost', placeholder: 'Why did we lose this deal?' })}>Mark lost</Button>
            </>}
            {quote.status !== 'draft' && can.sell(user) && <Button variant="secondary" loading={busy === 'revise'} onClick={revise}>Create revision</Button>}
            <Button variant="ghost" onClick={() => window.print()}>Print</Button>
          </div>
        </div>
      </div>

      {portalUrl && !CLOSED.includes(quote.status) && (
        <div className="no-print mb-6 flex flex-wrap items-center gap-3 rounded-xl border border-indigo-200 bg-indigo-50/60 px-4 py-3">
          <span className="text-sm font-semibold text-indigo-900">Customer portal link</span>
          <code className="min-w-0 flex-1 truncate rounded bg-white px-2 py-1 text-xs text-slate-600 ring-1 ring-indigo-100">{portalUrl}</code>
          <Button size="sm" variant="secondary" onClick={copyLink}>Copy</Button>
          <a href={portalUrl} target="_blank" rel="noreferrer" className="text-sm font-semibold text-brand-600 hover:underline">Open ↗</a>
        </div>
      )}
      {quote.lost_reason && CLOSED.includes(quote.status) && quote.status !== 'accepted' && <p className="mb-6 rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800"><b>Reason:</b> {quote.lost_reason}</p>}

      <div className="grid gap-6 xl:grid-cols-[1fr_340px]">
        <Card padded={false}>
          <div className="no-print px-5 pt-2">
            <Tabs value={tab} onChange={setTab} tabs={[
              { id: 'items', label: 'Line items', count: quote.lines.length },
              { id: 'negotiation', label: 'Negotiation', count: quote.messages.length },
              { id: 'timeline', label: 'Timeline', count: quote.events.length },
              { id: 'fulfilment', label: 'Fulfilment plan' },
              { id: 'billing', label: 'Billing schedule' },
            ]} />
          </div>
          <div className="p-5">
            {tab === 'items' && (
              <div className="scroll-thin overflow-x-auto">
                <table className="min-w-full divide-y divide-slate-100">
                  <thead><tr><th className="th pl-0">Product</th><th className="th text-right">Unit price</th><th className="th text-right">Qty</th><th className="th text-right">Disc.</th><th className="th text-right">Margin</th><th className="th pr-0 text-right">Net</th></tr></thead>
                  <tbody className="divide-y divide-slate-100">
                    {quote.lines.map((l) => (
                      <tr key={l.id}>
                        <td className="td pl-0"><p className="font-medium text-slate-900">{l.name}</p><p className="text-xs text-slate-500">{l.sku}{l.is_subscription ? ` · billed ${l.billing_period}` : ''}</p></td>
                        <td className="td num text-right">{inr(l.unit_price)}</td>
                        <td className="td num text-right">{l.quantity}</td>
                        <td className="td num text-right">{l.discount_percent ? pct(l.discount_percent) : '—'}</td>
                        <td className={`td num text-right ${l.margin_percent < 15 ? 'font-semibold text-rose-600' : ''}`}>{pct(l.margin_percent)}</td>
                        <td className="td num pr-0 text-right font-semibold text-slate-900">{inr2(l.line_total)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {quote.notes && <p className="mt-4 rounded-lg bg-slate-50 px-4 py-3 text-sm text-slate-600"><b className="text-slate-800">Notes:</b> {quote.notes}</p>}
              </div>
            )}
            {tab === 'negotiation' && <Negotiation quote={quote} user={user} onChange={(q) => (q?.id ? setQuote(q) : reload(true))} />}
            {tab === 'timeline' && (
              <ol className="relative ml-2 space-y-5 border-l border-slate-200 pl-6">
                {[...quote.events].reverse().map((e) => (
                  <li key={e.id} className="relative">
                    <span className={`absolute -left-[29px] top-1 h-2.5 w-2.5 rounded-full ring-4 ring-white ${['rejected', 'declined', 'lost', 'expired', 'counter_rejected'].includes(e.action) ? 'bg-rose-500' : ['approved', 'auto_approved', 'accepted', 'counter_accepted'].includes(e.action) ? 'bg-emerald-500' : 'bg-brand-500'}`} />
                    <p className="text-sm font-semibold text-slate-900">{EVENT_LABEL[e.action] || e.action}</p>
                    <p className="text-xs text-slate-500">{e.actor_name} · {fmtDateTime(e.created_at)}</p>
                    {e.comment && <p className="mt-1 text-sm text-slate-600">{e.comment}</p>}
                  </li>
                ))}
              </ol>
            )}
            {tab === 'fulfilment' && <FulfilmentPlan id={quote.id} />}
            {tab === 'billing' && <BillingSchedule id={quote.id} />}
          </div>
        </Card>

        <aside className="space-y-6">
          <Card title="Summary">
            <dl className="space-y-2 text-sm">
              {[['Subtotal', inr2(p.subtotal)], ['Discount', `− ${inr2(p.discount_total)}`], ['GST', inr2(p.tax_total)]].map(([k, v]) => (
                <div key={k} className="flex justify-between text-slate-600"><dt>{k}</dt><dd className="num">{v}</dd></div>
              ))}
              <div className="flex justify-between border-t border-slate-200 pt-3 text-base font-bold text-slate-900"><dt>Total</dt><dd className="num">{inr2(p.total)}</dd></div>
              <div className="flex justify-between pt-1 text-xs text-slate-500"><dt>Blended margin</dt><dd className="num">{pct(p.margin_percent)}</dd></div>
              {p.mrr > 0 && <div className="flex justify-between text-xs text-slate-500"><dt>Recurring (MRR)</dt><dd className="num">{inr(p.mrr)}</dd></div>}
              <div className="flex justify-between text-xs text-slate-500"><dt>Payment terms</dt><dd>Net {quote.payment_terms_days}</dd></div>
            </dl>
          </Card>
          <Card title="Deal risk" subtitle={quote.risk.required_level === 0 ? 'Within policy' : quote.risk.required_level === 1 ? 'Sales Manager approval' : 'Manager + Finance approval'}>
            <RiskGauge score={quote.risk.score} level={quote.risk.level} manager={policy.manager_threshold} finance={policy.finance_threshold} />
            {quote.risk.drivers.length > 0 && (
              <ul className="mt-3 space-y-2">
                {quote.risk.drivers.map((d) => <li key={d.factor} className="flex items-start justify-between gap-3 rounded-lg bg-slate-50 px-3 py-2 text-xs text-slate-600"><span>{d.detail}</span><b className="num shrink-0 text-slate-900">+{Math.round(d.points)}</b></li>)}
              </ul>
            )}
          </Card>
          <Card title="Customer">
            <p className="text-sm font-semibold text-slate-900">{quote.customer.name}</p>
            <p className="mt-0.5 text-xs text-slate-500">{quote.customer.contact_name} · {quote.customer.city}</p>
            <dl className="mt-3 space-y-1.5 text-xs text-slate-600">
              <div className="flex justify-between"><dt>Tier</dt><dd className="capitalize">{quote.customer.tier}</dd></div>
              <div className="flex justify-between"><dt>Credit limit</dt><dd className="num">{inr(quote.customer.credit_limit)}</dd></div>
              <div className="flex justify-between"><dt>GSTIN</dt><dd>{quote.customer.gstin || '—'}</dd></div>
            </dl>
          </Card>
        </aside>
      </div>
      <CommentModal config={modal} onClose={() => setModal(null)} onDone={(q) => { setModal(null); setQuote(q); }} />
    </>
  );
}

function Content({ user }) {
  const id = queryParam('id');
  const [quote, setQuote] = useState(null);
  const [policy, setPolicy] = useState({ manager_threshold: 25, finance_threshold: 55 });
  const { loading, error, reload } = useAsync(async () => {
    if (!id) return null;
    const [q, s] = await Promise.all([api(`/quotations/${id}`), api('/settings')]);
    setQuote(q);
    setPolicy(s);
    return q;
  }, [id]);

  if (!id) return can.sell(user) ? <QuotationEditor /> : <Empty title="You don’t have permission to create quotations" />;
  if (loading && !quote) return <Loading />;
  if (error) return <ErrorBox error={error} onRetry={reload} />;
  if (quote.status === 'draft' && can.sell(user)) return <QuotationEditor quote={quote} />;
  return <Detail quote={quote} user={user} policy={policy} reload={reload} setQuote={setQuote} />;
}

export default function Quotation() {
  return <AppShell page="quotations">{(user) => <Content user={user} />}</AppShell>;
}
