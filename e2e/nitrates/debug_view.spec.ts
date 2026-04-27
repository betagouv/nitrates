import { test, expect } from '@playwright/test';

// Reims (Marne, Grand Est, ZV bassin Seine-Normandie)
const REIMS_LNG = 4.03;
const REIMS_LAT = 49.26;

// Centre approximatif d'une parcelle RPG en Ille-et-Vilaine (35, Bretagne)
const RENNES_LNG = -1.5636201;
const RENNES_LAT = 48.1215230;

test.describe('Nitrates debug view', () => {
  test('home page shows the Leaflet map and the placeholder cartouche', async ({ page }) => {
    await page.goto('/');

    await expect(page).toHaveTitle(/Simulateur nitrates/);
    await expect(page.locator('h1')).toHaveText('Simulateur nitrates');

    const map = page.locator('#nitrates-map');
    await expect(map).toBeVisible();
    // Leaflet adds these classes once initialized.
    await expect(map).toHaveClass(/leaflet-container/);

    const cartouche = page.locator('#nitrates-debug');
    await expect(cartouche).toContainText('Cliquez sur la carte');
  });

  test('clicking on Reims fills the cartouche with Marne / Grand Est / ZV Seine-Normandie', async ({
    page,
  }) => {
    await page.goto('/');
    await expect(page.locator('#nitrates-map')).toHaveClass(/leaflet-container/);

    // Fire a Leaflet click directly (more reliable than DOM coords on a tiled map).
    await page.evaluate(([lng, lat]) => {
      const w = window as any;
      w.nitratesMap.fire('click', { latlng: w.L.latLng(lat, lng) });
    }, [REIMS_LNG, REIMS_LAT]);

    const cartouche = page.locator('#nitrates-debug');
    await expect(cartouche).toContainText('Informations parcelle');
    await expect(cartouche).toContainText('51');
    await expect(cartouche).toContainText('44');
    await expect(cartouche).toContainText('Grand Est');
    await expect(cartouche).toContainText(/OUI.*Seine-Normandie/);
    // Reims n'est pas sur une parcelle PAC importée, donc pas de RPG.
    await expect(cartouche).toContainText(/aucune parcelle RPG/);
  });

  test('clicking on a known RPG parcel in Ille-et-Vilaine shows the parcel info', async ({
    page,
  }) => {
    await page.goto('/');
    await expect(page.locator('#nitrates-map')).toHaveClass(/leaflet-container/);

    await page.evaluate(([lng, lat]) => {
      const w = window as any;
      w.nitratesMap.fire('click', { latlng: w.L.latLng(lat, lng) });
    }, [RENNES_LNG, RENNES_LAT]);

    const cartouche = page.locator('#nitrates-debug');
    await expect(cartouche).toContainText('Informations parcelle');
    await expect(cartouche).toContainText('35');
    await expect(cartouche).toContainText('53');
    await expect(cartouche).toContainText('Bretagne');
    // Identifiant exact de la parcelle qu'on a importée et vérifiée précédemment.
    await expect(cartouche).toContainText('7793966');
  });
});
