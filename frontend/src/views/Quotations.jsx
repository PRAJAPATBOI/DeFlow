import { useMemo, useState } from 'react';
import AppShell from '../components/AppShell.jsx';
import { Button, Card, Empty, ErrorBox, Loading, PageHeader, RiskBadge, StatusBadge, Table, useAsync } from '../components/ui.jsx';
import { api, can } from '../lib/api.js';
import { fmtDate, inr, inrShort, timeAgo } from '../lib/format.js';

const COLUMNS = [
  { id: 'draft', label: 'Draft', statuses: ['draft'], accent: 'bg-slate-400' },
  { id: 'approval', label: 'In approval', statuses: ['pending_manager', 'pending_finance'], accent: 'bg-amber-500' },
  { id: 'approved', label: 'Approved', statuses: ['approved'], accent: 'bg-sky-500' },
  { id: 'customer', label: 'With customer', statuses: ['sent', 'negotiating'], accent: 'bg-indigo-500' },
  { id: 'won', label: 'Won', statuses: ['accepted'], accent: 'bg-emerald-500' },
  { id: 'lost', label: 'Lost', statuses: ['rejected', 'declined', 'lost', 'expired'], accent: 'bg-rose-500' },
];
const open = (q) => { window.location.href = `/quotation?id=${q.id}`; };

function DealCard({ q }) {
  return (
    <a href={`/quotation?id=${q.id}`} className="block rounded-lg border border-slate-200 bg-white p-3 shadow-card transition hover:-translate-y-0.5 hover:border-brand-300 hover:shadow-pop">
      <div className="flex items-center justify-between gap-2">
        <span className="text-[11px] font-semibold text-slate-400">{q.number}</span>
        <RiskBadge level={q.risk_level} />
      </div>
      <p className="mt-1.5 line-clamp-2 text-sm font-semibold text-slate-900">{q.title}</p>
      <p className="mt-0.5 truncate text-xs text-slate-500">{q.customer_name}</p>
      <div className="mt-3 flex items-end justify-between">
        <span className="num text-sm font-bold text-slate-900">{inrShort(q.total)}</span>
        <span className="text-[11px] text-slate-400">{q.rep_name?.split(' ')[0]} · {timeAgo(q.updated_at)}</span>
      </div>
      {(q.has_open_counter || ['pending_finance', 'negotiating'].includes(q.status)) && (
        <div className="mt-2 border-t border-slate-100 pt-2">
          {q.has_open_counter ? <span className="text-[11px] font-semibold text-violet-700">● Counter-offer waiting</span> : <StatusBadge status={q.status} />}
        </div>
      )}
    </a>
  );
}

function Content({ user }) {
  const { data, loading, error, reload } = useAsync(() => api('/quotations'));
  const [view, setView] = useState(() => localStorage.getItem('df.quoteView') || 'board');
  const [search, setSearch] = useState('');
  const [status, setStatus] = useState('');
  const setMode = (v) => { setView(v); localStorage.setItem('df.quoteView', v); };

  const rows = useMemo(() => {
    const term = search.trim().toLowerCase();
    return (data || []).filter((q) => (!status || COLUMNS.find((c) => c.id === status).statuses.includes(q.status))
      && (!term || `${q.number} ${q.title} ${q.customer_name} ${q.rep_name}`.toLowerCase().includes(term)));
  }, [data, search, status]);

  if (loading) return <Loading />;
  if (error) return <ErrorBox error={error} onRetry={reload} />;

  return (
    <>
      <PageHeader title="Quotations" subtitle={`${data.length} quotations · ${inrShort(data.filter((q) => !['accepted', 'rejected', 'declined', 'lost', 'expired'].includes(q.status)).reduce((a, q) => a + q.total, 0))} open pipeline`}>
        <div className="flex rounded-lg bg-slate-200/70 p-0.5 text-xs font-semibold">
          {['board', 'list'].map((v) => (
            <button key={v} onClick={() => setMode(v)} className={`rounded-md px-3 py-1.5 capitalize transition ${view === v ? 'bg-white text-slate-900 shadow-sm' : 'text-slate-500'}`}>{v}</button>
          ))}
        </div>
        {can.sell(user) && <Button onClick={() => { window.location.href = '/quotation'; }}>+ New quotation</Button>}
      </PageHeader>

      <div className="mb-4 flex flex-wrap gap-3">
        <input className="input max-w-xs" placeholder="Search number, title, customer…" value={search} onChange={(e) => setSearch(e.target.value)} aria-label="Search quotations" />
        <select className="input w-auto" value={status} onChange={(e) => setStatus(e.target.value)} aria-label="Filter by stage">
          <option value="">All stages</option>
          {COLUMNS.map((c) => <option key={c.id} value={c.id}>{c.label}</option>)}
        </select>
      </div>

      {view === 'board' ? (
        <div className="scroll-thin -mx-1 flex gap-4 overflow-x-auto px-1 pb-4">
          {COLUMNS.filter((c) => !status || c.id === status).map((col) => {
            const items = rows.filter((q) => col.statuses.includes(q.status));
            return (
              <div key={col.id} className="w-72 shrink-0">
                <div className="mb-2 flex items-center justify-between px-1">
                  <span className="flex items-center gap-2 text-sm font-semibold text-slate-700"><span className={`h-2 w-2 rounded-full ${col.accent}`} />{col.label}<span className="rounded-full bg-slate-200 px-1.5 text-[11px] text-slate-600">{items.length}</span></span>
                  <span className="num text-xs font-medium text-slate-500">{inrShort(items.reduce((a, q) => a + q.total, 0))}</span>
                </div>
                <div className="scroll-thin max-h-[calc(100vh-270px)] min-h-[120px] space-y-2.5 overflow-y-auto rounded-xl bg-slate-100/80 p-2.5">
                  {items.length ? items.map((q) => <DealCard key={q.id} q={q} />) : <p className="py-8 text-center text-xs text-slate-400">No deals</p>}
                </div>
              </div>
            );
          })}
        </div>
      ) : (
        <Card padded={false}>
          {rows.length ? (
            <Table rows={rows} onRowClick={open} columns={[
              { key: 'number', label: 'Quote', render: (q) => <><p className="font-semibold text-slate-900">{q.title}</p><p className="text-xs text-slate-500">{q.number}{q.version > 1 ? ` · v${q.version}` : ''}</p></> },
              { key: 'customer_name', label: 'Customer' },
              { key: 'rep_name', label: 'Rep' },
              { key: 'status', label: 'Status', render: (q) => <StatusBadge status={q.status} /> },
              { key: 'risk', label: 'Risk', render: (q) => <RiskBadge level={q.risk_level} score={q.risk_score} /> },
              { key: 'total', label: 'Total', right: true, render: (q) => <b className="text-slate-900">{inr(q.total)}</b> },
              { key: 'valid_until', label: 'Valid until', render: (q) => fmtDate(q.valid_until) },
            ]} />
          ) : <Empty title="No quotations match" hint="Try a different search or stage filter." />}
        </Card>
      )}
    </>
  );
}

export default function Quotations() {
  return <AppShell page="quotations">{(user) => <Content user={user} />}</AppShell>;
}
