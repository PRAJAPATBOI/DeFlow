// Finds a locally installed Chrome/Edge so no browser download is needed. Override with CHROME_PATH.
import { existsSync, mkdirSync } from 'node:fs';
import puppeteer from 'puppeteer-core';

const CANDIDATES = [
  process.env.CHROME_PATH,
  'C:/Program Files/Google/Chrome/Application/chrome.exe',
  'C:/Program Files (x86)/Google/Chrome/Application/chrome.exe',
  'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
  '/usr/bin/google-chrome',
  '/usr/bin/chromium-browser',
  '/usr/bin/chromium',
].filter(Boolean);

export const BASE = process.env.BASE || 'http://127.0.0.1:8000';
export const SHOTS = process.env.SHOTS_DIR || 'shots';

export async function launch() {
  const executablePath = CANDIDATES.find((p) => existsSync(p));
  if (!executablePath) throw new Error('No Chrome/Edge found. Set CHROME_PATH to a Chromium-based browser.');
  mkdirSync(SHOTS, { recursive: true });
  return puppeteer.launch({ executablePath, headless: 'new', args: ['--no-sandbox'] });
}

export async function settle(page) {
  await page.waitForNetworkIdle({ idleTime: 400, timeout: 15000 }).catch(() => {});
  await new Promise((resolve) => setTimeout(resolve, 300));
}
