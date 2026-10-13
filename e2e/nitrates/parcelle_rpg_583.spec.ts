import { test, expect, Page } from '@playwright/test';

// #583 : parcelles RPG (IGN) sur la carte, selection d'une parcelle au clic.
// Depend du WFS de la Geoplateforme, comme les tuiles des autres tests carte.

// Champs de la Marne (parcelles RPG 2025 n° 6151142 et 6151167), loin des bords.
const DANS_PARCELLE = { lat: 48.7508, lng: 4.5527 };
const DANS_VOISINE = { lat: 48.7484, lng: 4.5467 };

const selectionAffichee = (page: Page) =>
  page.evaluate(() => document.querySelectorAll('.leaflet-nitratesSelection-pane path').length);

const pointFormulaire = (page: Page) =>
  page.evaluate(() => ({
    lat: parseFloat((document.getElementById('id_lat') as HTMLInputElement).value),
    lng: parseFloat((document.getElementById('id_lng') as HTMLInputElement).value),
  }));

async function cliquerCentre(page: Page) {
  // La carte est sous le bandeau d'accueil : hors ecran, le clic tomberait a cote.
  await page.locator('#nitrates-map').scrollIntoViewIfNeeded();
  const box = (await page.locator('#nitrates-map').boundingBox())!;
  await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2);
}

test.describe('Carte #583 : parcelles RPG', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/simulateur/');
    await expect(page.locator('#nitrates-map')).toHaveClass(/leaflet-container/);
    await page.evaluate(
      (p) => (window as any).nitratesMap.setView([p.lat, p.lng], 17, { animate: false }),
      DANS_PARCELLE
    );
  });

  test('clic : la parcelle est surlignée et la moulinette reçoit son point central', async ({
    page,
  }) => {
    await cliquerCentre(page);
    await expect.poll(() => selectionAffichee(page), { timeout: 10000 }).toBeGreaterThan(0);
    // Point central de la parcelle, pas le point cliqué : proche mais différent.
    await expect
      .poll(async () => {
        const p = await pointFormulaire(page);
        return Math.abs(p.lat - DANS_PARCELLE.lat) + Math.abs(p.lng - DANS_PARCELLE.lng);
      })
      .toBeGreaterThan(0.0001);
    const p = await pointFormulaire(page);
    expect(Math.abs(p.lat - DANS_PARCELLE.lat)).toBeLessThan(0.005);
    expect(Math.abs(p.lng - DANS_PARCELLE.lng)).toBeLessThan(0.005);
  });

  test('reclic dans la parcelle sélectionnée : désélection, le point reste', async ({ page }) => {
    await cliquerCentre(page);
    await expect.poll(() => selectionAffichee(page), { timeout: 10000 }).toBeGreaterThan(0);
    const avant = await pointFormulaire(page);
    await cliquerCentre(page);
    await expect.poll(() => selectionAffichee(page)).toBe(0);
    expect(await pointFormulaire(page)).toEqual(avant);
  });

  test('une seule parcelle sélectionnée à la fois', async ({ page }) => {
    await cliquerCentre(page);
    await expect.poll(() => selectionAffichee(page), { timeout: 10000 }).toBeGreaterThan(0);
    const avant = await selectionAffichee(page);
    await page.evaluate(
      (p) => (window as any).nitratesMap.setView([p.lat, p.lng], 17, { animate: false }),
      DANS_VOISINE
    );
    const pointAvant = await pointFormulaire(page);
    await cliquerCentre(page);
    // Nouvelle parcelle selectionnee = nouveau point central dans le formulaire.
    await expect
      .poll(async () => (await pointFormulaire(page)).lat, { timeout: 10000 })
      .not.toBe(pointAvant.lat);
    await expect.poll(() => selectionAffichee(page), { timeout: 10000 }).toBeGreaterThan(0);
    // Toujours une seule parcelle surlignee (halo + parcelle = meme nombre de traces).
    expect(await selectionAffichee(page)).toBe(avant);
  });
});
