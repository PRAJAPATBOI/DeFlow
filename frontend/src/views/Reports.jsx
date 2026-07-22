import { useState } from 'react';
import AppShell from '../components/AppShell.jsx';
import { BarChart, Donut, HBars } from '../components/charts.jsx';
import { Badge, Button, Card, Empty, ErrorBox, Loading, PageHeader, RiskBadge, Stat, StatusBadge, Table, act, useAsync } from '../components/ui.jsx';
import { api, download } from '../lib/api.js';
import { STATUS, inr, inrShort, pct } from '../lib/format.js';

function ReportsContent() {
  const { data, loading, error, reload } = useAsync(() => api('/reports/dashboard'));
  const [exporting, setExporting] = useState(false);
  if (loading) return <Loading />;
  if (error) return <ErrorBox error={error} onRetry={reload} />;
  const k = data.kpis;
  const leak = data.discount_by_category.reduce((a, c) => a + c.discount_given, 0);
  async function exportCsv() {
    setExporting(true);
    await act(download('/reports/export/quotations.csv', 'dealflow360-quotations.csv'), 'Export downloaded');
    setExporting(false);
  }
  return (
    <>
      <PageHeader title="Reports" subtitle="Revenue, collections, discounting and team performance.">
        <Button variant="secondary" loading={exporting} onClick={exportCsv}>Export quotations (CSV)</Button>
        <Button variant="ghost" onClick={() => window.print()}>Print</Button>
      </PageHeader>
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Stat label="Won revenue" value={inrShort(k.won_value)} hint={`${k.won_deals} deals`} />
        <Stat label="Win rate" value={pct(k.win_rate, 0)} hint={`Avg cycle ${k.avg_cycle_days} days`} />
        <Stat label="Avg margin on wins" value={pct(k.avg_margin)} hint="After discounts" />
        <Stat label="Discount given" value={inrShort(leak)} hint="On won deals, vs list price" />
      </div>

      <div className="mt-6 grid gap-6 xl:grid-cols-2">
        <Card title="Invoiced vs collected" subtitle="Cash conversion, last 6 months">
          <BarChart data={data.monthly} xKey="month" series={[{ key: 'invoiced', label: 'Invoiced', color: '#a5b4fc' }, { key: 'collected', label: 'Collected', color: '#10b981' }]} />
        </Card>
        <Card title="Quoted vs won" subtitle="Pipeline creation against closed revenue">
          <BarChart data={data.monthly} xKey="month" series={[{ key: 'quoted', label: 'Quoted', color: '#c7d2fe' }, { key: 'won', label: 'Won', color: '#4f46e5' }]} />
        </Card>
      </div>

      <div className="mt-6 grid gap-6 xl:grid-cols-3">
        <Card title="Discounting by category" subtitle="Average discount on won deals" padded={false}>
          <Table rowKey={(r) => r.category} rows={data.discount_by_category} empty="No won deals yet" columns={[
            { key: 'category', label: 'Category', render: (r) => <span className="font-medium text-slate-900">{r.category}</span> },
            { key: 'avg_discount_percent', label: 'Avg disc.', right: true, render: (r) => <span className={r.avg_discount_percent > 10 ? 'font-semibold text-amber-600' : ''}>{pct(r.avg_discount_percent)}</span> },
            { key: 'discount_given', label: 'Given away', right: true, render: (r) => inrShort(r.discount_given) },
          ]} />
        </Card>
        <Card title="Why deals close" subtitle="All closed quotations">
          <Donut centerValue={pct(k.win_rate, 0)} centerLabel="win rate" slices={[
            { label: 'Won', value: k.won_deals, color: '#10b981' },
            ...data.loss_breakdown.map((l, i) => ({ label: STATUS[l.status]?.label || l.status, value: l.count, color: ['#f43f5e', '#fb923c', '#a855f7', '#94a3b8'][i % 4] })),
          ]} />
        </Card>
        <Card title="Top products" subtitle="Net revenue from won deals">
          <HBars items={data.top_products.map((p) => ({ label: p.name, value: p.revenue, sub: `${p.units} u` }))} color="#0ea5e9" />
        </Card>
      </div>

      <Card title="Sales leaderboard" className="mt-6" padded={false}>
        <Table rowKey={(r) => r.rep} rows={data.leaderboard} columns={[
          { key: 'rep', label: 'Sales rep', render: (r) => <span className="font-semibold text-slate-900">{r.rep}</span> },
          { key: 'won_deals', label: 'Deals won', right: true },
          { key: 'won_value', label: 'Won value', right: true, render: (r) => inr(r.won_value) },
          { key: 'win_rate', label: 'Win rate', right: true, render: (r) => pct(r.win_rate, 0) },
          { key: 'pipeline', label: 'Open pipeline', right: true, render: (r) => inr(r.pipeline) },
        ]} />
      </Card>
    </>
  );
}

const HEALTH = { healthy: { tone: 'emerald', label: 'Healthy', bar: 'bg-emerald-500' }, at_risk: { tone: 'amber', label: 'At risk', bar: 'bg-amber-500' }, critical: { tone: 'rose', label: 'Critical', bar: 'bg-rose-500' } };

function DealHealthContent() {
  const { data, loading, error, reload } = useAsync(() => api('/reports/deal-health'));
  const [filter, setFilter] = useState('');
  if (loading) return <Loading />;
  if (error) return <ErrorBox error={error} onRetry={reload} />;
  const deals = data.deals.filter((d) => !filter || d.health === filter);
  return (
    <>
      <PageHeader title="Deal health" subtitle="Every open deal scored on momentum, commercial risk, expiry and unanswered customers — worst first." />
      <div className="grid gap-4 sm:grid-cols-3">
        {Object.entries(HEALTH).map(([key, meta]) => (
          <button key={key} onClick={() => setFilter(filter === key ? '' : key)} className={`rounded-xl border bg-white p-4 text-left shadow-card transition ${filter === key ? 'border-brand-500 ring-2 ring-brand-500/20' : 'border-slate-200 hover:border-brand-300'}`}>
            <Badge tone={meta.tone} dot>{meta.label}</Badge>
            <p className="num mt-2 font-display text-2xl font-bold text-slate-900">{data.summary[key].count} <span className="text-sm font-medium text-slate-400">deals</span></p>
            <p className="num text-xs text-slate-500">{inrShort(data.summary[key].value)} in pipeline</p>
          </button>
        ))}
      </div>
      <Card padded={false} className="mt-6">
        {deals.length === 0 ? <Empty title="No open deals in this band" /> : (
          <ul className="divide-y divide-slate-100">
            {deals.map((d) => (
              <li key={d.id}>
                <a href={`/quotation?id=${d.id}`} className="grid gap-3 px-5 py-4 transition hover:bg-slate-50 md:grid-cols-[90px_1fr_auto] md:items-center">
                  <div>
                    <p className="num font-display text-2xl font-bold text-slate-900">{d.health_score}</p>
                    <div className="mt-1 h-1.5 w-16 overflow-hidden rounded-full bg-slate-100"><div className={`h-full ${HEALTH[d.health].bar}`} style={{ width: `${d.health_score}%` }} /></div>
                  </div>
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2"><p className="font-semibold text-slate-900">{d.title}</p><StatusBadge status={d.status} /><RiskBadge level={d.risk_level} /></div>
                    <p className="mt-0.5 text-xs text-slate-500">{d.number} · {d.customer_name} · {d.rep_name}</p>
                    <div className="mt-2 flex flex-wrap gap-1.5">{d.reasons.length ? d.reasons.map((r) => <Badge key={r} tone="amber">{r}</Badge>) : <Badge tone="emerald">On track</Badge>}</div>
                  </div>
                  <div className="md:text-right">
                    <p className="num font-bold text-slate-900">{inr(d.total)}</p>
                    <p className="mt-0.5 text-xs font-medium text-brand-600">→ {d.next_action}</p>
                  </div>
                </a>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </>
  );
}

export function DealHealth() {
  return <AppShell page="deal-health"><DealHealthContent /></AppShell>;
}

export default function Reports() {
  return <AppShell page="reports"><ReportsContent /></AppShell>;
}
