// Génère un PNG d'une sous-zone du board SVG via viewBox restreint.
// Args: <board.svg> <out.png> <x> <y> <w> <h> [pxPerUnit]
import { chromium } from 'playwright';
import fs from 'fs';
import path from 'path';

const [,, svgPath, out, x, y, w, h, ppu='0.5'] = process.argv;
const X=+x, Y=+y, W=+w, H=+h, scale=+ppu;
let svg = fs.readFileSync(svgPath, 'utf-8');

// Remplace width/height/viewBox de la balise <svg> racine pour ne montrer
// que la zone voulue. On garde tout le contenu (les widgets hors zone sont
// simplement hors viewBox, donc non rendus).
const pxW = Math.round(W*scale), pxH = Math.round(H*scale);
svg = svg.replace(
  /<svg width="[\d.]+px" height="[\d.]+px"/,
  `<svg width="${pxW}px" height="${pxH}px" viewBox="${X} ${Y} ${W} ${H}"`
);
const tmp = path.resolve(out.replace(/\.png$/, '.tmp.svg'));
fs.writeFileSync(tmp, svg);

const browser = await chromium.launch();
const page = await browser.newPage({ deviceScaleFactor: 2 });
await page.setViewportSize({ width: Math.max(pxW,50), height: Math.max(pxH,50) });
await page.goto('file://' + tmp);
await page.waitForTimeout(400);
await page.screenshot({ path: out });
await browser.close();
fs.unlinkSync(tmp);
console.log(`${out}  (${pxW}x${pxH}px @${scale})`);
