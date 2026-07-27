// Smoke test: sign in as admin, open every internal page, fail on any console error or API 4xx/5xx.
// Screenshots land in ./shots (or SHOTS_DIR).
import { BASE, SHOTS, launch, settle } from './browser.mjs';

const browser = await launch();
const page = await browser.newPage();
await page.setViewport({ width: 1440, height: 900 });
const problems = [];
page.on('console', (m) => { if (m.type() === 'error') problems.push(`[console] ${page.url()} :: ${m.text()}`); });
page.on('pageerror', (e) => problems.push(`[pageerror] ${page.url()} :: ${e.message}`));
page.on('response', (r) => { if (r.status() >= 400 && r.url().includes('/api/')) problems.push(`[http ${r.status()}] ${r.url()}`); });
const shot = (name) => page.screenshot({ path: `${SHOTS}/${name}.png` });

await page.goto(`${BASE}/login`); await settle(page); await shot('login');
await page.type('input[type=email]', 'admin@dealflow360.in');
await page.type('input[type=password]', 'Demo@1234');
await page.keyboard.press('Enter');
await page.waitForSelector('main h1'); await settle(page); await shot('dashboard');

const pages = ['quotations', 'approvals', 'deal-health', 'customers', 'products', 'inventory', 'fulfillment',
  'invoices', 'subscriptions', 'reports', 'settings', 'quotation'];
for (const name of pages) {
  await page.goto(`${BASE}/${name}`);
  await page.waitForSelector('main h1', { timeout: 15000 });
  await settle(page);
  console.log(`${name.padEnd(14)} -> ${await page.$eval('main h1', (e) => e.textContent)}`);
  await shot(name);
}
// one won deal, to exercise the detail screen
await page.goto(`${BASE}/quotation?id=1`); await page.waitForSelector('main h1'); await settle(page); await shot('quotation-detail');

console.log(problems.length ? `PROBLEMS:\n${problems.join('\n')}` : 'NO CONSOLE/HTTP ERRORS');
await browser.close();
process.exit(problems.length ? 1 : 0);
