const inrFull = new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 });
const inrExact = new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', minimumFractionDigits: 2 });

export const inr = (n) => inrFull.format(Number(n) || 0);
export const inr2 = (n) => inrExact.format(Number(n) || 0);

// Indian short scale: 12.4 L, 3.2 Cr
export function inrShort(n) {
  const v = Number(n) || 0;
  const abs = Math.abs(v);
  if (abs >= 1e7) return `₹${(v / 1e7).toFixed(abs >= 1e8 ? 1 : 2)} Cr`;
  if (abs >= 1e5) return `₹${(v / 1e5).toFixed(abs >= 1e6 ? 1 : 2)} L`;
  if (abs >= 1e3) return `₹${(v / 1e3).toFixed(1)}K`;
  return `₹${v.toFixed(0)}`;
}

export const pct = (n, digits = 1) => `${(Number(n) || 0).toFixed(digits)}%`;

function parse(value) {
  if (!value) return null;
  // API timestamps are naive UTC; date-only strings are treated as local calendar dates.
  if (/^\d{4}-\d{2}-\d{2}$/.test(value)) return new Date(`${value}T00:00:00`);
  return new Date(/Z|[+-]\d{2}:\d{2}$/.test(value) ? value : `${value}Z`);
}

export function fmtDate(value) {
  const d = parse(value);
  return d ? d.toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' }) : '—';
}

export function fmtDateTime(value) {
  const d = parse(value);
  return d ? d.toLocaleString('en-IN', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' }) : '—';
}

export function timeAgo(value) {
  const d = parse(value);
  if (!d) return '—';
  const s = Math.max(0, (Date.now() - d.getTime()) / 1000);
  if (s < 60) return 'just now';
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  if (s < 86400 * 30) return `${Math.floor(s / 86400)}d ago`;
  return fmtDate(value);
}

export const STATUS = {
  draft: { label: 'Draft', tone: 'slate' },
  pending_manager: { label: 'Manager approval', tone: 'amber' },
  pending_finance: { label: 'Finance approval', tone: 'orange' },
  approved: { label: 'Approved', tone: 'sky' },
  sent: { label: 'Sent to customer', tone: 'indigo' },
  negotiating: { label: 'Negotiating', tone: 'violet' },
  accepted: { label: 'Won', tone: 'emerald' },
  rejected: { label: 'Rejected', tone: 'rose' },
  declined: { label: 'Declined', tone: 'rose' },
  lost: { label: 'Lost', tone: 'rose' },
  expired: { label: 'Expired', tone: 'slate' },
  under_revision: { label: 'Being revised', tone: 'amber' },
  // invoices
  issued: { label: 'Issued', tone: 'sky' },
  partially_paid: { label: 'Part paid', tone: 'amber' },
  paid: { label: 'Paid', tone: 'emerald' },
  overdue: { label: 'Overdue', tone: 'rose' },
  void: { label: 'Void', tone: 'slate' },
  // fulfilment
  planned: { label: 'Planned', tone: 'slate' },
  picking: { label: 'Picking', tone: 'amber' },
  shipped: { label: 'Shipped', tone: 'indigo' },
  delivered: { label: 'Delivered', tone: 'emerald' },
  backorder: { label: 'Backorder', tone: 'rose' },
  // subscriptions
  active: { label: 'Active', tone: 'emerald' },
  paused: { label: 'Paused', tone: 'amber' },
  cancelled: { label: 'Cancelled', tone: 'slate' },
};

export const EVENT_LABEL = {
  created: 'Created', submitted: 'Submitted for approval', auto_approved: 'Auto-approved', approved: 'Approved',
  rejected: 'Rejected', changes_requested: 'Changes requested', sent: 'Sent to customer',
  counter_offer: 'Counter-offer received', counter_accepted: 'Counter-offer accepted',
  counter_rejected: 'Counter-offer declined', accepted: 'Accepted by customer', declined: 'Declined by customer',
  order_created: 'Order-to-cash started', lost: 'Marked lost', expired: 'Expired',
};

export const PERIOD = { monthly: 'month', quarterly: 'quarter', annual: 'year' };
export const queryParam = (name) => new URLSearchParams(window.location.search).get(name);
