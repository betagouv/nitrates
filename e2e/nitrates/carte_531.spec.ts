import { test, expect, Page } from '@playwright/test';

// #531 amélioration carto : couches mémorisées, mode automatique, clavier.

const couchesCochees = (page: Page) =>
  page.evaluate(() =>
    [...document.querySelectorAll<HTMLInputElement>('.leaflet-control-layers-selector')]
      .filter((i) => i.checked)
      .map((i) => i.parentElement!.textContent!.trim())
  );

const tuilesChargees = (page: Page, layer: string) =>
  page.evaluate(
    (l) =>
      [...document.querySelectorAll<HTMLImageElement>('.leaflet-tile-pane img.leaflet-tile')].filter(
        (i) => i.src.includes(`LAYER=${l}`)
      ).length,
    layer
  );

test.describe('Carte #531', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/simulateur/');
    await page.evaluate(() => localStorage.clear());
    await page.reload();
    await expect(page.locator('#nitrates-map')).toHaveClass(/leaflet-container/);
  });

  test('défaut : mode automatique, photo seule, pas de cadastre en vue large', async ({ page }) => {
    expect(await couchesCochees(page)).toEqual(['Automatique (selon le zoom)']);
    await expect.poll(() => tuilesChargees(page, 'ORTHOIMAGERY.ORTHOPHOTOS')).toBeGreaterThan(0);
    expect(await tuilesChargees(page, 'CADASTRALPARCELS.PARCELLAIRE_EXPRESS')).toBe(0);
    expect(await tuilesChargees(page, 'GEOGRAPHICALGRIDSYSTEMS.PLANIGNV2')).toBe(0);
  });

  test('mode automatique : le cadastre apparaît une fois zoomé', async ({ page }) => {
    await page.evaluate(() => (window as any).nitratesMap.setZoom(15, { animate: false }));
    await expect
      .poll(() => tuilesChargees(page, 'CADASTRALPARCELS.PARCELLAIRE_EXPRESS'))
      .toBeGreaterThan(0);
    // La case « Cadastre » reste décochée : c'est le mode auto qui l'affiche.
    expect(await couchesCochees(page)).toEqual(['Automatique (selon le zoom)']);
  });

  test('les couches choisies sont retrouvées au rechargement', async ({ page }) => {
    const legende = page.locator('.leaflet-control-layers');
    await legende.getByLabel('Plan IGN').check();
    await legende.getByLabel('Zones vulnérables nitrates').check();
    await page.reload();
    await expect(page.locator('#nitrates-map')).toHaveClass(/leaflet-container/);
    expect(await couchesCochees(page)).toEqual(['Plan IGN', 'Zones vulnérables nitrates']);
  });

  test('clavier : Tab depuis la carte mène à la légende, Entrée coche, Échap revient', async ({
    page,
  }) => {
    await page.locator('#map-search').focus();
    await page.keyboard.press('Tab');
    await expect(page.locator('#nitrates-map')).toBeFocused();
    await page.keyboard.press('Tab');
    await expect(page.locator('.leaflet-control-layers-base input:checked')).toBeFocused();
    await page.keyboard.press('Tab');
    await page.keyboard.press('Enter');
    expect(await couchesCochees(page)).toContain('Cadastre');
    await page.keyboard.press('Escape');
    await expect(page.locator('#nitrates-map')).toBeFocused();
  });

  test('clavier : zoom et déplacement quand la carte a le focus', async ({ page }) => {
    const etat = () =>
      page.evaluate(() => {
        const m = (window as any).nitratesMap;
        return { z: m.getZoom(), lng: m.getCenter().lng };
      });
    await page.locator('#nitrates-map').focus();
    const avant = await etat();
    await page.keyboard.press('Control+Equal');
    await expect.poll(async () => (await etat()).z).toBe(avant.z + 1);
    await page.keyboard.press('ArrowRight');
    await expect.poll(async () => (await etat()).lng).toBeGreaterThan(avant.lng);
  });
});
