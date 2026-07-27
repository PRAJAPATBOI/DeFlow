// Full quote-to-cash journey driven through the UI, one isolated browser context per role:
// rep builds a quote -> manager approves -> rep sends -> customer negotiates and accepts in the portal
// -> fulfilment, invoicing and billing -> customer account -> governance -> mobile layout.
import { BASE, SHOTS, launch, settle } from './browser.mjs';

const browser = await launch();
const problems = [];
const steps = [];
const ok = (cond, label) => { steps.push(`${cond ? 'PASS' : 'FAIL'}  ${label}`); if (!cond) problems.push(`ASSERT ${label}`); };
async function newPage() {
  const ctx = await browser.createBrowserContext();
  const page = await ctx.newPage();
  await page.setViewport({ width: 1440, height: 900 });
  page.on('console', (m) => { if (m.type() === 'error' && !/status of 4\d\d/.test(m.text())) problems.push(`[console] ${page.url()} :: ${m.text()}`); });
  page.on('pageerror', (e) => problems.push(`[pageerror] ${page.url()} :: ${e.message}`));
  page.on('dialog', (d) => d.accept());
  return page;
}
const click = async (page, text, scope = 'button') => {
  const done = await page.evaluate((text, scope) => {
    const el = [...document.querySelectorAll(scope)].find((b) => b.textContent.trim().startsWith(text) && !b.disabled);
    if (el) el.click();
    return !!el;
  }, text, scope);
  if (!done) throw new Error(`No ${scope} "${text}" on ${page.url()}`);
  await settle(page);
};
const text = (page) => page.evaluate(() => document.body.innerText);
const login = async (page, email) => {
  await page.goto(`${BASE}/login`); await settle(page);
  await page.type('input[type=email]', email); await page.type('input[type=password]', 'Demo@1234');
  await page.keyboard.press('Enter'); await page.waitForNavigation({ waitUntil: 'networkidle0' }).catch(() => {}); await settle(page);
};
const setInput = async (page, selector, value) => { await page.click(selector, { clickCount: 3 }); await page.type(selector, String(value)); };

try {
  // 1. Rep builds a quote that needs manager approval
  const rep = await newPage();
  await login(rep, 'arjun@dealflow360.in');
  ok((await text(rep)).includes('Your book of business'), 'rep lands on a rep-scoped dashboard');
  await rep.goto(`${BASE}/quotation`); await settle(rep);
  await rep.type('input[placeholder^="e.g."]', 'E2E virtualisation rollout');
  await rep.select('select.input', await rep.$eval('select.input', (sel) => [...sel.options].find((o) => o.textContent.startsWith('Nilgiri')).value));
  await rep.type('input[aria-label="Add product"]', 'SW-VIRT'); await settle(rep);
  await click(rep, 'Virtualisation Suite', 'ul button');
  await setInput(rep, 'input[aria-label="Quantity"]', 2);
  await setInput(rep, 'input[aria-label="Discount percent"]', 27);
  await rep.type('input[aria-label="Add product"]', 'SUB-CLD'); await settle(rep);
  await click(rep, 'Cloud Backup', 'ul button');
  await new Promise((r) => setTimeout(r, 900)); await settle(rep);
  let body = await text(rep);
  ok(body.includes('Needs Sales Manager approval'), 'live risk panel routes the quote to the manager');
  ok(body.includes('policy max 20%'), 'discount policy limit shown on the line');
  ok(body.includes('Suggested add-ons'), 'upsell suggestions appear');
  await rep.screenshot({ path: `${SHOTS}/20-editor.png` });
  await click(rep, 'Save & submit');
  await rep.waitForFunction(() => location.search.includes('id='), { timeout: 15000 }); await settle(rep);
  const quoteUrl = rep.url();
  body = await text(rep);
  ok(body.includes('Manager approval'), 'submitted quote is pending manager approval');
  ok(!body.includes('Request changes'), 'rep is not offered approval actions');

  // 2. Manager approves
  const mgr = await newPage();
  await login(mgr, 'manager@dealflow360.in');
  await mgr.goto(`${BASE}/approvals`); await settle(mgr);
  ok((await text(mgr)).includes('E2E virtualisation rollout'), 'quote shows up in the manager queue');
  await mgr.goto(quoteUrl); await settle(mgr);
  await click(mgr, 'Approve'); await mgr.type('textarea', 'Good strategic fit'); await click(mgr, 'Approve', '[role=dialog] footer button');
  ok((await text(mgr)).includes('Approved'), 'manager approval moves the quote to Approved');

  // 3. Rep sends it and grabs the portal link
  await rep.reload(); await settle(rep);
  await click(rep, 'Send to customer');
  const portalUrl = await rep.$eval('code', (c) => c.textContent);
  ok(portalUrl.includes('/portal?token='), 'portal link generated after sending');

  // 4. Customer (no login) negotiates
  const cust = await newPage();
  await cust.goto(portalUrl); await settle(cust);
  body = await text(cust);
  ok(body.includes('E2E virtualisation rollout') && body.includes('Accept quotation'), 'customer opens the quote without logging in');
  ok(!/margin|risk/i.test(body), 'portal shows no margin or risk data');
  await cust.screenshot({ path: `${SHOTS}/21-portal.png` });
  await click(cust, 'Negotiate price');
  await cust.type('[role=dialog] input[type=number]', '29'); await cust.type('[role=dialog] textarea', '29% and we sign today');
  await click(cust, 'Send counter-offer');
  ok((await text(cust)).includes('Counter-offer pending'), 'customer counter-offer is recorded');

  // 5. Rep reviews the impact analysis and accepts
  await rep.reload(); await settle(rep);
  body = await text(rep);
  ok(body.includes('is asking for 29% off') && body.includes('REVENUE IMPACT'), 'rep sees the counter-offer with impact analysis');
  await rep.screenshot({ path: `${SHOTS}/22-negotiation.png` });
  await click(rep, 'Accept 29%');
  body = await text(rep);
  const badge = await rep.evaluate(() => document.querySelector('h1').parentElement.innerText);
  const needsApproval = /approval/i.test(badge);
  ok(needsApproval || body.includes('Sent to customer'), 'accepting the counter-offer updates the quote');
  if (needsApproval) {
    const adm = await newPage(); await login(adm, 'admin@dealflow360.in'); await adm.goto(quoteUrl); await settle(adm);
    while ((await text(adm)).includes('Request changes')) { await click(adm, 'Approve'); await click(adm, 'Approve', '[role=dialog] footer button'); }
    await cust.reload(); await settle(cust);
    await rep.reload(); await settle(rep); await click(rep, 'Send to customer');
  }
  steps.push(`INFO  counter-offer ${needsApproval ? 'required re-approval (handled)' : 'stayed within the approved level'}`);

  // 6. Customer accepts
  await cust.reload(); await settle(cust);
  await click(cust, 'Accept quotation'); await click(cust, 'Confirm acceptance');
  body = await text(cust);
  ok(body.includes('You accepted this quotation'), 'customer acceptance confirmed in the portal');
  ok(!body.includes('Accept quotation'), 'accept button disappears once accepted');

  // 7. Order-to-cash artefacts
  await rep.reload(); await settle(rep);
  ok((await text(rep)).includes('Won'), 'quote is Won for the rep');
  await click(rep, 'Timeline');
  ok((await text(rep)).includes('Order-to-cash started'), 'timeline records order-to-cash');
  await click(rep, 'Billing schedule'); ok((await text(rep)).includes('FIRST-YEAR VALUE'), 'billing schedule tab renders');
  await click(rep, 'Fulfilment plan'); ok(/Shipment 1|Nothing to ship|Backorder/.test(await text(rep)), 'fulfilment plan tab renders');

  await mgr.goto(`${BASE}/fulfillment`); await settle(mgr);
  ok((await text(mgr)).includes('Start picking'), 'manager sees a planned fulfilment order');
  await click(mgr, 'Start picking'); ok((await text(mgr)).includes('Mark shipped'), 'order advances to picking');
  await mgr.screenshot({ path: `${SHOTS}/23-fulfilment.png` });

  const fin = await newPage(); await login(fin, 'finance@dealflow360.in');
  await fin.goto(`${BASE}/invoices`); await settle(fin);
  const quoteNumber = (await rep.evaluate(() => document.querySelector('h1').parentElement.parentElement.innerText)).match(/Q-\d{4}-\d{4}/)[0];
  await fin.evaluate((number) => [...document.querySelectorAll('tbody tr')].find((row) => row.innerText.includes(number)).click(), quoteNumber); await settle(fin);
  ok((await text(fin)).includes('Balance due'), 'invoice detail opens');
  await click(fin, 'Record payment'); await click(fin, 'Save');
  ok((await text(fin)).includes('PAYMENTS RECEIVED'), 'payment recorded on the invoice of the deal just won');
  await fin.screenshot({ path: `${SHOTS}/24-invoice.png` });
  await fin.goto(`${BASE}/subscriptions`); await settle(fin);
  await click(fin, 'Run billing cycle'); await click(fin, 'Raise invoices');
  ok(!(await text(fin)).includes('Raise invoices'), 'billing cycle runs from the UI');
  await fin.goto(`${BASE}/quotation`); await settle(fin);
  ok((await text(fin)).includes('permission'), 'finance cannot create quotations');

  // 8. Customer account, governance, mobile
  const acct = await newPage(); await login(acct, 'customer@aravalli.example');
  ok(acct.url().includes('/portal') && (await text(acct)).includes('Aravalli Steel Works'), 'customer login lands on their portal home');
  await acct.screenshot({ path: `${SHOTS}/25-portal-home.png` });
  await acct.goto(`${BASE}/quotations`); await settle(acct);
  ok(acct.url().includes('/portal'), 'customer is kept out of internal screens');
  const adm = await newPage(); await login(adm, 'admin@dealflow360.in');
  await adm.goto(`${BASE}/settings`); await settle(adm);
  await click(adm, 'Team & access'); ok((await text(adm)).includes('Invite user'), 'admin sees user management');
  await click(adm, 'Audit trail'); ok((await text(adm)).includes('quotation.accept'), 'audit trail lists the acceptance');
  await adm.screenshot({ path: `${SHOTS}/26-audit.png` });
  await adm.setViewport({ width: 390, height: 800 }); await adm.goto(`${BASE}/`); await settle(adm);
  const overflow = await adm.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  ok(overflow <= 1, `no horizontal overflow on a 390px phone (${overflow}px)`);
  await adm.screenshot({ path: `${SHOTS}/27-mobile.png` });
} catch (e) {
  problems.push(`SCRIPT ERROR: ${e.message}`);
}
console.log(steps.join('\n'));
console.log(problems.length ? '\nPROBLEMS:\n' + problems.join('\n') : '\nALL CHECKS PASSED, NO CONSOLE ERRORS');
await browser.close();
process.exit(problems.length ? 1 : 0);
