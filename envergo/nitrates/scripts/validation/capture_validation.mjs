#!/usr/bin/env node
// Boucle sur les BrancheValidation et capture le simulateur en fullpage.

import { chromium } from "@playwright/test";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const BRANCHES_PATH =
  process.env.BRANCHES_PATH || path.join(HERE, "branches_full.json");
const OUTPUT_DIR = process.env.OUTPUT_DIR || path.join(HERE, "out_simu");
const BASE_URL = process.env.BASE_URL || "http://envergo_django:8000";

fs.mkdirSync(OUTPUT_DIR, { recursive: true });
const branches = JSON.parse(fs.readFileSync(BRANCHES_PATH, "utf-8"));

const browser = await chromium.launch({ headless: true });
const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 } });
const page = await ctx.newPage();

let i = 0;
for (const b of branches) {
  i++;
  const url = BASE_URL + b.url;
  const fname = `${b.id}__${b.regle_id || "no_regle"}.png`;
  const out = path.join(OUTPUT_DIR, fname);
  process.stdout.write(`[${i}/${branches.length}] ${b.regle_id} ... `);
  try {
    await page.goto(url, { waitUntil: "networkidle", timeout: 30000 });
    // Donne 800ms au cascade JS pour pre-remplir les radios depuis NITRATES_INITIAL_DATA.
    await page.waitForTimeout(800);
    await page.screenshot({ path: out, fullPage: true });
    console.log("OK", fname);
  } catch (err) {
    console.log("FAIL", err.message);
  }
}

await browser.close();
console.log(`\nDone : ${branches.length} captures dans ${OUTPUT_DIR}`);
