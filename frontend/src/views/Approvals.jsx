import { useState } from 'react';
import AppShell from '../components/AppShell.jsx';
import { Badge, Button, Card, Empty, ErrorBox, Field, Loading, Modal, PageHeader, RiskBadge, StatusBadge, Table, act, toast, useAsync } from '../components/ui.jsx';
import { api } from '../lib/api.js';
import { EVENT_LABEL, fmtDateTime, inr, pct } from '../lib/format.js';

const ACTIONS = {
  approve: { title: 'Approve quotation', cta: 'Approve', variant: 'success', required: false, done: 'Approved' },
  'request-changes': { title: 'Request changes', cta: 'Send back to rep', variant: 'primary', required: true, done: 'Sent back to the rep' },
  reject: { title: 'Reject quotation', cta: 'Reject', variant: 'danger', required: true, done: 'Rejected' },
};

function Content() {
  const queue = useAsync(() => api('/approvals/queue'));
  const history = useAsync(() => api('/approvals/history'));
  const [dialog, setDialog] = useState(null); // { quote, action }
  const [comment, setComment] = useState('');
  const [busy, setBusy] = useState(false);

  async function confirm() {
    const cfg = ACTIONS[dialog.action];
    if (cfg.required && comment.trim().length < 3) return toast('A comment is required', 'error');
    setBusy(true);
    const ok = await act(api(`/quotations/${dialog.quote.id}/${dialog.action}`, { method: 'POST', body: { comment: comment.trim() || null } }), `${dialog.quote.number}: ${cfg.done}`);
    setBusy(false);
    if (ok) { setDialog(null); setComment(''); queue.reload(true); history.reload(true); }
  }

  if (queue.loading) return <Loading />;
  if (queue.error) return <ErrorBox error={queue.error} onRetry={queue.reload} />;
  const mine = queue.data.filter((q) => q.can_act);
  const others = queue.data.filter((q) => !q.can_act);

  const QueueCard = ({ q }) => (
    <Card className="overflow-hidden" padded={false}>
      <div className="flex flex-wrap items-start justify-between gap-4 p-5">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <a href={`/quotation?id=${q.id}`} className="text-base font-semibold text-slate-900 hover:text-brand-600">{q.title}</a>
            <StatusBadge status={q.status} /><RiskBadge level={q.risk.level} score={q.risk.score} />
          </div>
          <p className="mt-1 text-sm text-slate-500">{q.number} · {q.customer_name} · by {q.rep_name} · waiting {q.waiting_hours < 24 ? `${Math.round(q.waiting_hours)}h` : `${Math.round(q.waiting_hours / 24)}d`}</p>
        </div>
        <div className="text-right">
          <p className="num font-display text-xl font-bold text-slate-900">{inr(q.total)}</p>
          <p className="text-xs text-slate-500">margin {pct(q.margin_percent)} · discount {inr(q.discount_total)}</p>
        </div>
      </div>
      <div className="border-t border-slate-100 bg-slate-50/60 px-5 py-3">
        <p className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-slate-500">Why this needs approval</p>
        <ul className="flex flex-wrap gap-2">
          {q.risk.drivers.map((d) => <li key={d.factor}><Badge tone="amber">+{Math.round(d.points)} · {d.detail}</Badge></li>)}
        </ul>
        <div className="mt-4 flex flex-wrap gap-2">
          {q.can_act ? Object.entries(ACTIONS).map(([key, cfg]) => (
            <Button key={key} size="sm" variant={key === 'approve' ? 'success' : key === 'reject' ? 'danger' : 'secondary'} onClick={() => setDialog({ quote: q, action: key })}>{cfg.cta}</Button>
          )) : <span className="text-xs text-slate-500">Waiting on {q.status === 'pending_manager' ? 'a Sales Manager' : 'Finance'}.</span>}
          <a href={`/quotation?id=${q.id}`} className="ml-auto self-center text-sm font-semibold text-brand-600 hover:underline">Review details →</a>
        </div>
      </div>
    </Card>
  );

  return (
    <>
      <PageHeader title="Approvals" subtitle="Quotations are routed here when discounts, margin, credit exposure or payment terms push the risk score over policy." />
      <h2 className="mb-3 text-sm font-semibold text-slate-700">Waiting for you <span className="ml-1 rounded-full bg-amber-100 px-2 py-0.5 text-xs text-amber-800">{mine.length}</span></h2>
      {mine.length ? <div className="space-y-4">{mine.map((q) => <QueueCard key={q.id} q={q} />)}</div> : <Card><Empty title="You’re all caught up" hint="Nothing needs your decision right now." /></Card>}

      {others.length > 0 && <>
        <h2 className="mb-3 mt-8 text-sm font-semibold text-slate-700">In progress with other approvers</h2>
        <div className="space-y-4">{others.map((q) => <QueueCard key={q.id} q={q} />)}</div>
      </>}

      <h2 className="mb-3 mt-8 text-sm font-semibold text-slate-700">Recent decisions</h2>
      <Card padded={false}>
        <Table rows={history.data || []} empty="No decisions yet" onRowClick={(r) => { window.location.href = `/quotation?id=${r.quotation_id}`; }} columns={[
          { key: 'created_at', label: 'When', render: (r) => fmtDateTime(r.created_at) },
          { key: 'number', label: 'Quotation', render: (r) => <><p className="font-medium text-slate-900">{r.title}</p><p className="text-xs text-slate-500">{r.number} · {r.customer_name}</p></> },
          { key: 'action', label: 'Decision', render: (r) => <Badge tone={r.action === 'rejected' ? 'rose' : r.action === 'changes_requested' ? 'amber' : 'emerald'}>{EVENT_LABEL[r.action]}</Badge> },
          { key: 'actor_name', label: 'By' },
          { key: 'comment', label: 'Comment', className: 'max-w-xs truncate text-slate-500' },
          { key: 'total', label: 'Value', right: true, render: (r) => inr(r.total) },
        ]} />
      </Card>

      {dialog && (
        <Modal open title={ACTIONS[dialog.action].title} subtitle={`${dialog.quote.number} · ${dialog.quote.customer_name} · ${inr(dialog.quote.total)}`} onClose={() => setDialog(null)}
          footer={<><Button variant="ghost" onClick={() => setDialog(null)}>Cancel</Button><Button variant={ACTIONS[dialog.action].variant} loading={busy} onClick={confirm}>{ACTIONS[dialog.action].cta}</Button></>}>
          <Field label={ACTIONS[dialog.action].required ? 'Comment (required)' : 'Comment (optional)'}>
            <textarea className="input" rows={3} autoFocus value={comment} onChange={(e) => setComment(e.target.value)} placeholder="Visible to the rep and recorded in the audit trail." />
          </Field>
        </Modal>
      )}
    </>
  );
}

export default function Approvals() {
  return <AppShell page="approvals"><Content /></AppShell>;
}
