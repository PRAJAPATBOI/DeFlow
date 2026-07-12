import AppShell from '../components/AppShell.jsx';
import { BarChart, Donut, HBars } from '../components/charts.jsx';
import { Button, Card, ErrorBox, Loading, PageHeader, Stat, Table, useAsync } from '../components/ui.jsx';
import { api, can } from '../lib/api.js';
import { EVENT_LABEL, inrShort, pct, timeAgo } from '../lib/format.js';

const STAGE_COLORS = { Draft: '#94a3b8', 'In approval': '#f59e0b', Approved: '#0ea5e9', 'With customer': '#6366f1', Won: '#10b981', Lost: '#f43f5e' };

function Content({ user }) {
  const { data, loading, error, reload } = useAsync(() => api('/reports/dashboard'));
  if (loading) return <Loading />;
  if (error) return <ErrorBox error={error} onRetry={reload} />;
  const k = data.kpis;
  const firstName = user.name.split(' ')[0];

  return (
    <>
      <PageHeader title={`Good to see you, ${firstName}`} subtitle={user.role === 'sales_rep' ? 'Your book of business at a glance.' : 'Company-wide pipeline, revenue and collections.'}>
        {can.sell(user) && <Button onClick={() => { window.location.href = '/quotation'; }}>+ New quotation</Button>}
      </PageHeader>

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Stat label="Open pipeline" value={inrShort(k.pipeline_value)} hint={`${k.open_deals} open deals`} />
        <Stat label="Won revenue" value={inrShort(k.won_value)} hint={`${k.won_deals} deals · avg ${inrShort(k.avg_deal_size)}`} />
        <Stat label="Win rate" value={pct(k.win_rate, 0)} hint={`${k.avg_cycle_days} day avg sales cycle`} />
        <Stat label="Recurring revenue" value={inrShort(k.mrr)} hint={`MRR · ${inrShort(k.arr)} ARR`} />
        <Stat label="Outstanding" value={inrShort(k.outstanding)} hint="Receivables not yet collected" />
        <Stat label="Overdue" value={inrShort(k.overdue)} hint={k.overdue > 0 ? 'Needs collection follow-up' : 'Nothing overdue'} />
        <Stat label="Pending approvals" value={k.pending_approvals} hint="Quotes waiting for sign-off" />
        <Stat label="Avg won margin" value={pct(k.avg_margin)} hint="Blended, after discounts" />
      </div>

      <div className="mt-6 grid gap-6 xl:grid-cols-3">
        <Card title="Quoted vs won" subtitle="Last 6 months, incl. GST" className="xl:col-span-2">
          <BarChart height={300} data={data.monthly} xKey="month" series={[{ key: 'quoted', label: 'Quoted', color: '#c7d2fe' }, { key: 'won', label: 'Won', color: '#4f46e5' }]} />
        </Card>
        <Card title="Pipeline by stage" subtitle="Count of quotations">
          <Donut centerValue={data.funnel.reduce((a, s) => a + s.count, 0)} centerLabel="quotations"
            slices={data.funnel.map((s) => ({ label: s.stage, value: s.count, color: STAGE_COLORS[s.stage] }))} />
          <div className="mt-5 border-t border-slate-100 pt-4">
            <HBars items={data.funnel.filter((s) => s.value > 0).map((s) => ({ label: s.stage, value: s.value, color: STAGE_COLORS[s.stage] }))} />
          </div>
        </Card>
      </div>

      <div className="mt-6 grid gap-6 xl:grid-cols-3">
        <Card title="Top products" subtitle="Net revenue from won deals">
          <HBars items={data.top_products.map((p) => ({ label: p.name, value: p.revenue, sub: `${p.units} u` }))} color="#0ea5e9" />
        </Card>
        <Card title="Sales leaderboard" padded={false}>
          <Table rowKey={(r) => r.rep} rows={data.leaderboard} columns={[
            { key: 'rep', label: 'Rep', render: (r) => <span className="font-medium text-slate-900">{r.rep}</span> },
            { key: 'won_value', label: 'Won', right: true, render: (r) => inrShort(r.won_value) },
            { key: 'win_rate', label: 'Win %', right: true, render: (r) => pct(r.win_rate, 0) },
            { key: 'pipeline', label: 'Pipeline', right: true, render: (r) => inrShort(r.pipeline) },
          ]} />
        </Card>
        <Card title="Recent activity" padded={false}>
          <ul className="divide-y divide-slate-100">
            {data.activity.map((a) => (
              <li key={a.id}>
                <a href={`/quotation?id=${a.quotation_id}`} className="block px-5 py-3 transition hover:bg-slate-50">
                  <p className="text-sm text-slate-800"><b className="font-semibold">{a.actor_name}</b> · {EVENT_LABEL[a.action] || a.action}</p>
                  <p className="mt-0.5 truncate text-xs text-slate-500">{a.number} · {a.customer_name} · {timeAgo(a.created_at)}</p>
                </a>
              </li>
            ))}
          </ul>
        </Card>
      </div>
    </>
  );
}

export default function Dashboard() {
  return <AppShell page="dashboard">{(user) => <Content user={user} />}</AppShell>;
}
