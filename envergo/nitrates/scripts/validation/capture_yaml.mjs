#!/usr/bin/env node
// Capture pour chaque BrancheValidation :
//   - viewer : admin YAML tree avec deeplink #regle=X
//   - form   : admin YAML tree avec ?edit=1#regle=X (auto-redirect mode
//              edition + auto-click crayon)
//
// L'app fait tout le boulot (deplie l'arbre, scroll, clic edit). Le script
// ne fait que naviguer + screenshot.

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

// Login Django admin
await page.goto(BASE_URL + "/admin/login/", { waitUntil: "domcontentloaded", timeout: 60000 });
await page.fill('input[name="username"]', ADMIN_USER);
await page.fill('input[name="password"]', ADMIN_PASS);
await page.locator('input[type="submit"], button[type="submit"]').first().click();
await page.waitForLoadState("domcontentloaded", { timeout: 60000 });
await page.waitForTimeout(800);
console.log("Login OK :", await page.title());

// Resoudre l'URL du draft d'edition une seule fois.
await page.goto(BASE_URL + "/admin/nitrates/arbre-decision/?edit=1", {
  waitUntil: "domcontentloaded",
  timeout: 60000,
});
await page.waitForTimeout(1500);
const editUrlBase = page.url().split("#")[0];
console.log("Draft d'edition partage :", editUrlBase);

let i = 0;
for (const b of branches) {
  i++;
  if (!b.regle_id) {
    console.log(`[${i}/${branches.length}] SKIP no regle_id (id=${b.id})`);
    continue;
  }

  // ─── VIEWER : deeplink #regle=X (lecture seule) ──────────────────────
  try {
    const url =
      BASE_URL + `/admin/nitrates/arbre-decision/#regle=${encodeURIComponent(b.regle_id)}`;
    await page.goto(url, { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(600);
    const fname = `${b.id}__${b.regle_id}_viewer.png`;
    await page.screenshot({
      path: path.join(OUTPUT_DIR, fname),
      fullPage: true,
    });
    console.log(`[${i}/${branches.length}] VIEWER OK ${fname}`);
  } catch (err) {
    console.log(`[${i}/${branches.length}] VIEWER ERR : ${err.message}`);
  }

  // ─── FORM : reuse le meme draft, juste change le hash ───────────────
  // On ne re-deploie pas le tree (couteux + redirige) : on charge l'URL
  // direct ?tree_id=X&mode=edition#regle=Y&edit=1 qui evite editer-actif/.
  try {
    const url = editUrlBase + `#regle=${encodeURIComponent(b.regle_id)}&edit=1`;
    await page.goto(url, { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(1500);
    const fname = `${b.id}__${b.regle_id}_form.png`;
    await page.screenshot({
      path: path.join(OUTPUT_DIR, fname),
      fullPage: true,
    });
    console.log(`[${i}/${branches.length}] FORM   OK ${fname}`);
  } catch (err) {
    console.log(`[${i}/${branches.length}] FORM   ERR : ${err.message}`);
  }
}

await browser.close();
console.log(`\nDone : ${OUTPUT_DIR}`);
