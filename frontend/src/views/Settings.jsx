import { useEffect, useState } from 'react';
import AppShell from '../components/AppShell.jsx';
import { Badge, Button, Card, ErrorBox, Field, Loading, Modal, PageHeader, Table, Tabs, act, toast, useAsync } from '../components/ui.jsx';
import { ROLE_LABEL, api, can } from '../lib/api.js';
import { fmtDateTime, timeAgo } from '../lib/format.js';

function Policy({ user }) {
  const settings = useAsync(() => api('/settings'));
  const tiers = useAsync(() => api('/discount-tiers'));
  const [form, setForm] = useState(null);
  const [tier, setTier] = useState(null);
  const [busy, setBusy] = useState(false);
  const admin = can.admin(user);
  useEffect(() => { if (settings.data) setForm(settings.data); }, [settings.data]);
  if (settings.loading || tiers.loading || !form) return <Loading />;
  if (settings.error) return <ErrorBox error={settings.error} onRetry={settings.reload} />;
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });

  async function save(e) {
    e.preventDefault();
    setBusy(true);
    await act(api('/settings', { method: 'PUT', body: { company_name: form.company_name, min_margin_percent: Number(form.min_margin_percent), manager_threshold: Number(form.manager_threshold), finance_threshold: Number(form.finance_threshold), quote_validity_days: Number(form.quote_validity_days) } }), 'Policy updated — applies to all open quotations');
    setBusy(false);
    settings.reload(true);
  }
  async function saveTier(e) {
    e.preventDefault();
    const ok = await act(api('/discount-tiers', { method: 'POST', body: { name: tier.name || tier.category || 'Standard policy', category: tier.category || null, max_discount_percent: Number(tier.max_discount_percent) } }), 'Discount tier saved');
    if (ok) { setTier(null); tiers.reload(true); }
  }
  async function removeTier(t) {
    if (!window.confirm(`Remove the ${t.category} tier? That category will fall back to the default limit.`)) return;
    await act(api(`/discount-tiers/${t.id}`, { method: 'DELETE' }), 'Tier removed');
    tiers.reload(true);
  }

  return (
    <div className="grid gap-6 xl:grid-cols-2">
      <Card title="Approval policy" subtitle="A deal's 0–100 risk score decides who must sign it off.">
        <form onSubmit={save} className="grid gap-4 sm:grid-cols-2">
          <Field label="Company name" className="sm:col-span-2"><input className="input" disabled={!admin} value={form.company_name} onChange={set('company_name')} /></Field>
          <Field label="Manager approval from score" hint="Below this, quotes auto-approve"><input className="input" type="number" min="1" max="100" disabled={!admin} value={form.manager_threshold} onChange={set('manager_threshold')} /></Field>
          <Field label="Finance approval from score" hint="At or above: Manager, then Finance"><input className="input" type="number" min="1" max="100" disabled={!admin} value={form.finance_threshold} onChange={set('finance_threshold')} /></Field>
          <Field label="Minimum blended margin %" hint="Each point below adds 2 risk points"><input className="input" type="number" min="0" max="90" disabled={!admin} value={form.min_margin_percent} onChange={set('min_margin_percent')} /></Field>
          <Field label="Default quote validity (days)"><input className="input" type="number" min="1" max="365" disabled={!admin} value={form.quote_validity_days} onChange={set('quote_validity_days')} /></Field>
          <div className="sm:col-span-2">
            <div className="flex h-3 overflow-hidden rounded-full text-[0px]">
              <span className="bg-emerald-400" style={{ width: `${form.manager_threshold}%` }}>auto</span>
              <span className="bg-amber-400" style={{ width: `${Math.max(0, form.finance_threshold - form.manager_threshold)}%` }}>manager</span>
              <span className="flex-1 bg-rose-400">finance</span>
            </div>
            <p className="mt-1.5 flex justify-between text-[11px] text-slate-500"><span>Auto-approve</span><span>Sales Manager</span><span>Manager + Finance</span></p>
          </div>
          {admin ? <div className="sm:col-span-2"><Button type="submit" loading={busy}>Save policy</Button></div> : <p className="text-xs text-slate-500 sm:col-span-2">Only administrators can change policy.</p>}
        </form>
      </Card>

      <Card title="Discount tiers" subtitle="Maximum discount per category before a line adds risk (4 points per % over, value-weighted)." padded={false}
        action={admin && <Button size="sm" variant="secondary" onClick={() => setTier({ name: '', category: '', max_discount_percent: 10 })}>+ Add tier</Button>}>
        <Table rows={tiers.data} columns={[
          { key: 'category', label: 'Category', render: (t) => (t.category ? <span className="font-medium text-slate-900">{t.category}</span> : <Badge tone="indigo">Default — all other categories</Badge>) },
          { key: 'max_discount_percent', label: 'Max discount', right: true, render: (t) => <b>{t.max_discount_percent}%</b> },
          ...(admin ? [{ key: 'a', label: '', right: true, render: (t) => (
            <span className="inline-flex gap-1.5"><Button size="sm" variant="ghost" onClick={() => setTier({ ...t, category: t.category || '' })}>Edit</Button>{t.category && <Button size="sm" variant="ghost" onClick={() => removeTier(t)}>Remove</Button>}</span>
          ) }] : []),
        ]} />
      </Card>
      {tier && (
        <Modal open title={tier.id ? 'Edit discount tier' : 'Add discount tier'} onClose={() => setTier(null)}
          footer={<><Button variant="ghost" onClick={() => setTier(null)}>Cancel</Button><Button form="tier-form" type="submit">Save tier</Button></>}>
          <form id="tier-form" onSubmit={saveTier} className="grid gap-4">
            <Field label="Product category" hint="Leave empty to change the default tier"><input className="input" disabled={!!tier.id} value={tier.category} onChange={(e) => setTier({ ...tier, category: e.target.value, name: e.target.value })} placeholder="e.g. Servers" /></Field>
            <Field label="Maximum discount %"><input className="input" type="number" min="0" max="90" step="0.5" required value={tier.max_discount_percent} onChange={(e) => setTier({ ...tier, max_discount_percent: e.target.value })} /></Field>
          </form>
        </Modal>
      )}
    </div>
  );
}

function Users({ me }) {
  const { data, loading, error, reload } = useAsync(() => api('/users'));
  const [creating, setCreating] = useState(null);
  if (loading) return <Loading />;
  if (error) return <ErrorBox error={error} onRetry={reload} />;
  const patch = async (u, body, msg) => { await act(api(`/users/${u.id}`, { method: 'PATCH', body }), msg); reload(true); };
  async function create(e) {
    e.preventDefault();
    const ok = await act(api('/users', { method: 'POST', body: creating }), 'User created');
    if (ok) { setCreating(null); reload(true); }
  }
  return (
    <Card title="Team & access" subtitle="Internal roles control what each person can see and approve." padded={false}
      action={<Button size="sm" onClick={() => setCreating({ name: '', email: '', password: '', role: 'sales_rep' })}>+ Invite user</Button>}>
      <Table rows={data} columns={[
        { key: 'name', label: 'User', render: (u) => <><p className={`font-semibold ${u.is_active ? 'text-slate-900' : 'text-slate-400'}`}>{u.name}{u.id === me.id && <span className="ml-2 text-xs font-normal text-slate-400">(you)</span>}</p><p className="text-xs text-slate-500">{u.email}{u.customer_name ? ` · ${u.customer_name}` : ''}</p></> },
        { key: 'role', label: 'Role', render: (u) => (u.role === 'customer' || u.id === me.id ? <Badge tone={u.role === 'customer' ? 'slate' : 'indigo'}>{ROLE_LABEL[u.role]}</Badge> : (
          <select className="input w-auto py-1.5 text-xs" value={u.role} aria-label={`Role for ${u.name}`} onChange={(e) => patch(u, { role: e.target.value }, `${u.name} is now ${ROLE_LABEL[e.target.value]}`)}>
            {['admin', 'sales_manager', 'sales_rep', 'finance'].map((r) => <option key={r} value={r}>{ROLE_LABEL[r]}</option>)}
          </select>
        )) },
        { key: 'last_login_at', label: 'Last sign-in', render: (u) => (u.last_login_at ? timeAgo(u.last_login_at) : <span className="text-slate-400">never</span>) },
        { key: 'is_active', label: 'Status', render: (u) => <Badge tone={u.is_active ? 'emerald' : 'slate'} dot>{u.is_active ? 'Active' : 'Deactivated'}</Badge> },
        { key: 'a', label: '', right: true, render: (u) => u.id !== me.id && <Button size="sm" variant="ghost" onClick={() => patch(u, { is_active: !u.is_active }, u.is_active ? 'User deactivated' : 'User reactivated')}>{u.is_active ? 'Deactivate' : 'Reactivate'}</Button> },
      ]} />
      {creating && (
        <Modal open title="Invite a team member" onClose={() => setCreating(null)} footer={<><Button variant="ghost" onClick={() => setCreating(null)}>Cancel</Button><Button form="user-form" type="submit">Create user</Button></>}>
          <form id="user-form" onSubmit={create} className="grid gap-4">
            <Field label="Full name"><input className="input" required minLength={2} value={creating.name} onChange={(e) => setCreating({ ...creating, name: e.target.value })} /></Field>
            <Field label="Email"><input className="input" type="email" required value={creating.email} onChange={(e) => setCreating({ ...creating, email: e.target.value })} /></Field>
            <Field label="Role"><select className="input" value={creating.role} onChange={(e) => setCreating({ ...creating, role: e.target.value })}>{['admin', 'sales_manager', 'sales_rep', 'finance'].map((r) => <option key={r} value={r}>{ROLE_LABEL[r]}</option>)}</select></Field>
            <Field label="Temporary password" hint="At least 8 characters"><input className="input" type="text" required minLength={8} value={creating.password} onChange={(e) => setCreating({ ...creating, password: e.target.value })} /></Field>
          </form>
        </Modal>
      )}
    </Card>
  );
}

function Audit() {
  const { data, loading, error, reload } = useAsync(() => api('/audit-logs?limit=200'));
  if (loading) return <Loading />;
  if (error) return <ErrorBox error={error} onRetry={reload} />;
  return (
    <Card title="Audit trail" subtitle="Every state-changing action, newest first. Entries cannot be edited." padded={false}>
      <Table rows={data} empty="No activity recorded" columns={[
        { key: 'created_at', label: 'When', render: (r) => <span className="whitespace-nowrap">{fmtDateTime(r.created_at)}</span> },
        { key: 'actor_name', label: 'Who', render: (r) => <span className="font-medium text-slate-900">{r.actor_name}</span> },
        { key: 'action', label: 'Action', render: (r) => <code className="rounded bg-slate-100 px-1.5 py-0.5 text-xs text-slate-700">{r.action}</code> },
        { key: 'detail', label: 'Detail', className: 'text-slate-500' },
      ]} />
    </Card>
  );
}

function Account({ user }) {
  const [form, setForm] = useState({ current_password: '', new_password: '', confirm: '' });
  const [busy, setBusy] = useState(false);
  async function submit(e) {
    e.preventDefault();
    if (form.new_password !== form.confirm) return toast('New passwords do not match', 'error');
    setBusy(true);
    const ok = await act(api('/auth/change-password', { method: 'POST', body: { current_password: form.current_password, new_password: form.new_password } }), 'Password changed');
    setBusy(false);
    if (ok) setForm({ current_password: '', new_password: '', confirm: '' });
  }
  return (
    <div className="grid gap-6 xl:grid-cols-2">
      <Card title="Profile">
        <dl className="space-y-3 text-sm">
          {[['Name', user.name], ['Email', user.email], ['Role', ROLE_LABEL[user.role]]].map(([k, v]) => <div key={k} className="flex justify-between"><dt className="text-slate-500">{k}</dt><dd className="font-medium text-slate-900">{v}</dd></div>)}
        </dl>
      </Card>
      <Card title="Change password">
        <form onSubmit={submit} className="grid gap-4">
          <Field label="Current password"><input className="input" type="password" required autoComplete="current-password" value={form.current_password} onChange={(e) => setForm({ ...form, current_password: e.target.value })} /></Field>
          <Field label="New password" hint="At least 8 characters"><input className="input" type="password" required minLength={8} autoComplete="new-password" value={form.new_password} onChange={(e) => setForm({ ...form, new_password: e.target.value })} /></Field>
          <Field label="Confirm new password"><input className="input" type="password" required minLength={8} autoComplete="new-password" value={form.confirm} onChange={(e) => setForm({ ...form, confirm: e.target.value })} /></Field>
          <div><Button type="submit" loading={busy}>Update password</Button></div>
        </form>
      </Card>
    </div>
  );
}

function Content({ user }) {
  const tabs = [{ id: 'policy', label: 'Pricing & approval policy' }, ...(can.admin(user) ? [{ id: 'users', label: 'Team & access' }] : []), ...(can.manage(user) ? [{ id: 'audit', label: 'Audit trail' }] : []), { id: 'account', label: 'My account' }];
  const [tab, setTab] = useState('policy');
  return (
    <>
      <PageHeader title="Governance" subtitle="Discount policy, approval thresholds, access control and the audit trail." />
      <Tabs tabs={tabs} value={tab} onChange={setTab} />
      <div className="mt-6">
        {tab === 'policy' && <Policy user={user} />}
        {tab === 'users' && <Users me={user} />}
        {tab === 'audit' && <Audit />}
        {tab === 'account' && <Account user={user} />}
      </div>
    </>
  );
}

export default function Settings() {
  return <AppShell page="settings">{(user) => <Content user={user} />}</AppShell>;
}
