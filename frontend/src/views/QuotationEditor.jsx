import { useEffect, useMemo, useRef, useState } from 'react';
import { RiskGauge } from '../components/charts.jsx';
import { Badge, Button, Card, Empty, Field, PageHeader, act, toast } from '../components/ui.jsx';
import { api } from '../lib/api.js';
import { PERIOD, inr, inr2, pct } from '../lib/format.js';

/** Number input that can be cleared and retyped; commits a clamped value as you type. */
function Num({ value, onCommit, min, max, integer = false, className = '', ...props }) {
  const [raw, setRaw] = useState(String(value));
  useEffect(() => setRaw(String(value)), [value]);
  const parse = (text) => {
    const n = integer ? parseInt(text, 10) : parseFloat(text);
    return Number.isFinite(n) ? Math.min(max, Math.max(min, n)) : null;
  };
  return (
    <input {...props} type="number" min={min} max={max} className={className} value={raw}
      onChange={(e) => { setRaw(e.target.value); const n = parse(e.target.value); if (n !== null) onCommit(n); }}
      onBlur={() => setRaw(String(parse(raw) ?? value))} />
  );
}

function ProductPicker({ products, onPick }) {
  const [term, setTerm] = useState('');
  const [open, setOpen] = useState(false);
  const box = useRef(null);
  useEffect(() => {
    const close = (e) => !box.current?.contains(e.target) && setOpen(false);
    document.addEventListener('mousedown', close);
    return () => document.removeEventListener('mousedown', close);
  }, []);
  const matches = useMemo(() => {
    const t = term.trim().toLowerCase();
    return products.filter((p) => !t || `${p.name} ${p.sku} ${p.category}`.toLowerCase().includes(t)).slice(0, 30);
  }, [products, term]);
  return (
    <div className="relative" ref={box}>
      <input className="input" placeholder="+ Add a product — search by name, SKU or category" value={term} aria-label="Add product"
        onFocus={() => setOpen(true)} onChange={(e) => { setTerm(e.target.value); setOpen(true); }} />
      {open && (
        <ul className="scroll-thin absolute z-20 mt-1 max-h-72 w-full overflow-y-auto rounded-xl border border-slate-200 bg-white py-1 shadow-pop">
          {matches.length === 0 && <li className="px-4 py-3 text-sm text-slate-500">No products match “{term}”.</li>}
          {matches.map((p) => (
            <li key={p.id}>
              <button type="button" onClick={() => { onPick(p); setTerm(''); setOpen(false); }} className="flex w-full items-center justify-between gap-3 px-4 py-2 text-left hover:bg-brand-50">
                <span className="min-w-0">
                  <span className="block truncate text-sm font-medium text-slate-900">{p.name}</span>
                  <span className="block text-xs text-slate-500">{p.sku} · {p.category}{p.is_subscription ? ` · billed ${p.billing_period}` : p.is_stocked ? ` · ${p.stock_available} in stock` : ' · service'}</span>
                </span>
                <span className="num shrink-0 text-sm font-semibold text-slate-700">{inr(p.price)}{p.is_subscription && <span className="text-xs font-normal text-slate-400">/{PERIOD[p.billing_period]}</span>}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export default function QuotationEditor({ quote }) {
  const [products, setProducts] = useState([]);
  const [customers, setCustomers] = useState([]);
  const [policy, setPolicy] = useState({ manager_threshold: 25, finance_threshold: 55 });
  const [form, setForm] = useState(() => ({
    title: quote?.title || '', customer_id: quote?.customer_id || '', payment_terms_days: quote?.payment_terms_days ?? 30,
    valid_until: quote?.valid_until || '', notes: quote?.notes || '',
  }));
  const [lines, setLines] = useState(() => (quote?.lines || []).map((l) => ({ product_id: l.product_id, quantity: l.quantity, discount_percent: l.discount_percent })));
  const [preview, setPreview] = useState(null);
  const [upsells, setUpsells] = useState([]);
  const [busy, setBusy] = useState('');
  const lastAdded = useRef(null);

  useEffect(() => {
    Promise.all([api('/products'), api('/customers'), api('/settings')])
      .then(([p, c, s]) => { setProducts(p); setCustomers(c); setPolicy(s); })
      .catch((e) => toast(e.message, 'error'));
  }, []);

  // Live pricing + risk, debounced.
  useEffect(() => {
    const clean = lines.filter((l) => l.quantity >= 1);
    const timer = setTimeout(() => {
      api('/quotations/preview', { method: 'POST', body: { customer_id: form.customer_id || null, payment_terms_days: Number(form.payment_terms_days) || 0, lines: clean } })
        .then(setPreview).catch(() => {});
    }, 250);
    return () => clearTimeout(timer);
  }, [lines, form.customer_id, form.payment_terms_days]);

  const byId = useMemo(() => Object.fromEntries(products.map((p) => [p.id, p])), [products]);
  const customer = customers.find((c) => c.id === Number(form.customer_id));

  function addProduct(p, discount = 0) {
    setLines((ls) => (ls.some((l) => l.product_id === p.id)
      ? ls.map((l) => (l.product_id === p.id ? { ...l, quantity: l.quantity + 1 } : l))
      : [...ls, { product_id: p.id, quantity: 1, discount_percent: discount }]));
    lastAdded.current = p.id;
    api(`/products/${p.id}/upsells`).then(setUpsells).catch(() => setUpsells([]));
  }
  const patch = (i, change) => setLines((ls) => ls.map((l, j) => (j === i ? { ...l, ...change } : l)));

  function pickCustomer(id) {
    const c = customers.find((x) => x.id === Number(id));
    setForm((f) => ({ ...f, customer_id: id, payment_terms_days: c ? c.payment_terms_days : f.payment_terms_days }));
  }

  async function save(andSubmit) {
    if (!form.title.trim() || form.title.trim().length < 3) return toast('Give the quotation a title (3+ characters)', 'error');
    if (!form.customer_id) return toast('Choose a customer', 'error');
    if (andSubmit && !lines.length) return toast('Add at least one product before submitting', 'error');
    setBusy(andSubmit ? 'submit' : 'save');
    const body = { ...form, customer_id: Number(form.customer_id), payment_terms_days: Number(form.payment_terms_days), valid_until: form.valid_until || null, lines };
    let saved = await act(quote ? api(`/quotations/${quote.id}`, { method: 'PUT', body }) : api('/quotations', { method: 'POST', body }));
    if (saved && andSubmit) saved = await act(api(`/quotations/${saved.id}/submit`, { method: 'POST' }));
    if (saved) window.location.href = `/quotation?id=${saved.id}`;
    else setBusy('');
  }

  const pricing = preview?.pricing;
  const risk = preview?.risk;
  const priced = pricing?.lines || [];
  const suggestions = upsells.filter((u) => !lines.some((l) => l.product_id === u.id)).slice(0, 3);
  const feedback = [...(quote?.events || [])].reverse().find((e) => ['changes_requested', 'submitted'].includes(e.action));
  const route = !risk ? '' : risk.required_level === 0 ? 'Auto-approved on submit' : risk.required_level === 1 ? 'Needs Sales Manager approval' : 'Needs Sales Manager + Finance approval';

  return (
    <>
      <PageHeader title={quote ? `Edit ${quote.number}` : 'New quotation'} subtitle="Pricing, tax and risk update as you type.">
        <Button variant="ghost" onClick={() => { window.location.href = '/quotations'; }}>Cancel</Button>
        <Button variant="secondary" loading={busy === 'save'} disabled={!!busy} onClick={() => save(false)}>Save draft</Button>
        <Button loading={busy === 'submit'} disabled={!!busy} onClick={() => save(true)}>Save &amp; submit</Button>
      </PageHeader>

      {feedback?.action === 'changes_requested' && (
        <p className="mb-6 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900"><b>{feedback.actor_name} requested changes:</b> {feedback.comment}</p>
      )}
      <div className="grid gap-6 xl:grid-cols-[1fr_340px]">
        <div className="space-y-6">
          <Card title="Deal details">
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Title" className="sm:col-span-2"><input className="input" value={form.title} maxLength={200} onChange={(e) => setForm({ ...form, title: e.target.value })} placeholder="e.g. Data centre refresh — Phase 1" /></Field>
              <Field label="Customer" hint={customer ? `${customer.tier} tier · credit limit ${inr(customer.credit_limit)} · ${customer.city || customer.region}` : undefined}>
                <select className="input" value={form.customer_id} onChange={(e) => pickCustomer(e.target.value)}>
                  <option value="">Select a customer…</option>
                  {customers.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
                </select>
              </Field>
              <div className="grid grid-cols-2 gap-4">
                <Field label="Payment terms (days)"><Num className="input" min={0} max={180} integer value={form.payment_terms_days} onCommit={(n) => setForm((f) => ({ ...f, payment_terms_days: n }))} /></Field>
                <Field label="Valid until"><input className="input" type="date" value={form.valid_until} onChange={(e) => setForm({ ...form, valid_until: e.target.value })} /></Field>
              </div>
              <Field label="Notes for the customer" className="sm:col-span-2"><textarea className="input" rows={2} value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} placeholder="Delivery assumptions, scope, anything the customer should know." /></Field>
            </div>
          </Card>

          <Card title="Line items" subtitle={`${lines.length} item${lines.length === 1 ? '' : 's'}`} padded={false}>
            <div className="border-b border-slate-100 p-4"><ProductPicker products={products} onPick={addProduct} /></div>
            {lines.length === 0 ? <Empty title="No products yet" hint="Search the catalogue above to start building this quote." /> : (
              <div className="scroll-thin overflow-x-auto">
                <table className="min-w-full divide-y divide-slate-100">
                  <thead className="bg-slate-50/70"><tr>
                    <th className="th">Product</th><th className="th text-right">Unit price</th><th className="th w-24">Qty</th>
                    <th className="th w-36">Discount %</th><th className="th text-right">Margin</th><th className="th text-right">Net amount</th><th className="th w-10" />
                  </tr></thead>
                  <tbody className="divide-y divide-slate-100">
                    {lines.map((line, i) => {
                      const p = byId[line.product_id];
                      const calc = priced[i]?.product_id === line.product_id ? priced[i] : null;
                      const over = calc?.max_discount != null && line.discount_percent > calc.max_discount;
                      const short = p && p.is_stocked && p.stock_available < line.quantity;
                      return (
                        <tr key={line.product_id}>
                          <td className="td">
                            <p className="font-medium text-slate-900">{p?.name || '…'}</p>
                            <p className="flex flex-wrap items-center gap-1.5 text-xs text-slate-500">{p?.sku}
                              {p?.is_subscription && <Badge tone="indigo">billed {p.billing_period}</Badge>}
                              {short && <Badge tone="amber">only {p.stock_available} in stock</Badge>}
                            </p>
                          </td>
                          <td className="td num text-right">{inr(p?.price)}</td>
                          <td className="td"><Num className="input num px-2 py-1.5" min={1} max={100000} integer aria-label="Quantity" value={line.quantity} onCommit={(n) => patch(i, { quantity: n })} /></td>
                          <td className="td">
                            <Num className={`input num px-2 py-1.5 ${over ? 'border-amber-400 bg-amber-50' : ''}`} min={0} max={90} step="0.5" aria-label="Discount percent" value={line.discount_percent} onCommit={(n) => patch(i, { discount_percent: n })} />
                            {calc?.max_discount != null && <p className={`mt-1 whitespace-nowrap text-[11px] ${over ? 'font-semibold text-amber-700' : 'text-slate-400'}`}>policy max {calc.max_discount}%</p>}
                          </td>
                          <td className={`td num text-right ${calc && calc.margin_percent < 15 ? 'font-semibold text-rose-600' : ''}`}>{calc ? pct(calc.margin_percent) : '—'}</td>
                          <td className="td num text-right font-semibold text-slate-900">{calc ? inr(calc.line_total) : '—'}</td>
                          <td className="td"><button aria-label="Remove line" className="rounded p-1 text-slate-400 hover:bg-rose-50 hover:text-rose-600" onClick={() => setLines((ls) => ls.filter((_, j) => j !== i))}>✕</button></td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </Card>

          {suggestions.length > 0 && (
            <Card title="Suggested add-ons" subtitle="Ranked by margin contribution">
              <div className="grid gap-3 sm:grid-cols-3">
                {suggestions.map((u) => (
                  <div key={u.id} className="rounded-lg border border-slate-200 p-3">
                    <Badge tone="violet">{u.reason}</Badge>
                    <p className="mt-2 text-sm font-semibold text-slate-900">{u.name}</p>
                    <p className="num mt-0.5 text-xs text-slate-500">{inr(u.price)} · +{inr(u.margin_delta)} margin</p>
                    <Button size="sm" variant="secondary" className="mt-3 w-full" onClick={() => addProduct(u)}>Add to quote</Button>
                  </div>
                ))}
              </div>
            </Card>
          )}
        </div>

        <aside className="space-y-6 xl:sticky xl:top-6 xl:self-start">
          <Card title="Deal risk" subtitle={route}>
            <RiskGauge score={risk?.score || 0} level={risk?.level || 'low'} manager={policy.manager_threshold} finance={policy.finance_threshold} />
            {risk?.drivers?.length ? (
              <ul className="mt-3 space-y-2">
                {risk.drivers.map((d) => (
                  <li key={d.factor} className="flex items-start justify-between gap-3 rounded-lg bg-slate-50 px-3 py-2 text-xs text-slate-600">
                    <span>{d.detail}</span><b className="num shrink-0 text-slate-900">+{Math.round(d.points)}</b>
                  </li>
                ))}
              </ul>
            ) : <p className="mt-2 text-center text-xs text-slate-500">Inside discount, margin and credit policy.</p>}
          </Card>
          <Card title="Summary">
            <dl className="space-y-2 text-sm">
              {[['Subtotal', inr2(pricing?.subtotal)], ['Discount', `− ${inr2(pricing?.discount_total)}`], ['GST', inr2(pricing?.tax_total)]].map(([k, v]) => (
                <div key={k} className="flex justify-between text-slate-600"><dt>{k}</dt><dd className="num">{v}</dd></div>
              ))}
              <div className="flex justify-between border-t border-slate-200 pt-3 text-base font-bold text-slate-900"><dt>Total</dt><dd className="num">{inr2(pricing?.total)}</dd></div>
              <div className="flex justify-between pt-1 text-xs text-slate-500"><dt>Blended margin</dt><dd className="num">{pct(pricing?.margin_percent)}</dd></div>
              {pricing?.mrr > 0 && <div className="flex justify-between text-xs text-slate-500"><dt>Recurring (MRR)</dt><dd className="num">{inr(pricing.mrr)}</dd></div>}
            </dl>
          </Card>
        </aside>
      </div>
    </>
  );
}
