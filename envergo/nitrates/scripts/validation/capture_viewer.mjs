#!/usr/bin/env node
// Capture viewer uniquement (deeplink #regle=X, lecture seule).
// Pas de mode édition pour éviter les crashes Django observés sur 24+ itérations.

import { chromium } from "@playwright/test";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const BRANCHES_PATH =
  process.env.BRANCHES_PATH || path.join(HERE, "branches_validation.json");
const OUTPUT_DIR = process.env.OUTPUT_DIR || path.join(HERE, "out_yaml");
const BASE_URL = process.env.BASE_URL || "http://django:8000";
const ADMIN_USER = process.env.ADMIN_USER || "admin@admin.local";
const ADMIN_PASS = process.env.ADMIN_PASS || "admin";

fs.mkdirSync(OUTPUT_DIR, { recursive: true });
const branches = JSON.parse(fs.readFileSync(BRANCHES_PATH, "utf-8"));

const browser = await chromium.launch({ headless: true });
const ctx = await browser.newContext({ viewport: { width: 1600, height: 1100 } });
const page = await ctx.newPage();

await page.goto(BASE_URL + "/admin/login/", { waitUntil: "domcontentloaded", timeout: 60000 });
await page.fill('input[name="username"]', ADMIN_USER);
await page.fill('input[name="password"]', ADMIN_PASS);
await page.locator('input[type="submit"], button[type="submit"]').first().click();
await page.waitForLoadState("domcontentloaded", { timeout: 60000 });
await page.waitForTimeout(800);
console.log("Login OK");

let i = 0;
for (const b of branches) {
  i++;
  if (!b.regle_id) {
    console.log(`[${i}/${branches.length}] SKIP`);
    continue;
  }
  try {
    const url =
      BASE_URL + `/admin/nitrates/arbre-decision/#regle=${encodeURIComponent(b.regle_id)}`;
    await page.goto(url, { waitUntil: "domcontentloaded", timeout: 30000 });
    await page.waitForTimeout(700);
    const fname = `${b.id}__${b.regle_id}_viewer.png`;
    await page.screenshot({ path: path.join(OUTPUT_DIR, fname), fullPage: true });
    console.log(`[${i}/${branches.length}] OK ${fname}`);
  } catch (err) {
    console.log(`[${i}/${branches.length}] ERR : ${err.message.slice(0, 80)}`);
  }
}

await browser.close();
