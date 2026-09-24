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

  test('clavier : Tab depuis la carte mène au plein écran puis à la légende, Entrée coche, Échap revient', async ({
    page,
  }) => {
    await page.locator('#map-search').focus();
    await page.keyboard.press('Tab');
    await expect(page.locator('#nitrates-map')).toBeFocused();
    await page.keyboard.press('Tab');
    await expect(page.getByRole('button', { name: 'Afficher la carte en plein écran' })).toBeFocused();
    await page.keyboard.press('Tab');
    await expect(page.locator('.leaflet-control-layers-base input:checked')).toBeFocused();
    await page.keyboard.press('Tab');
    await page.keyboard.press('Enter');
    expect(await couchesCochees(page)).toContain('Cadastre');
    await page.keyboard.press('Escape');
    await expect(page.locator('#nitrates-map')).toBeFocused();
  });

  test('clavier : les polygones ZV / ZAR ne sont pas des arrêts de Tab', async ({ page }) => {
    const legende = page.locator('.leaflet-control-layers');
    await legende.getByLabel('Zones vulnérables nitrates').check();
    await legende.getByLabel("Zones d'action renforcée (ZAR)").check();
    await expect
      .poll(() => page.locator('.leaflet-overlay-pane path').count(), { timeout: 15000 })
      .toBeGreaterThan(0);
    await page.locator('#nitrates-map').focus();
    for (let i = 0; i < 6; i++) {
      await page.keyboard.press('Tab');
      const tag = await page.evaluate(() => document.activeElement!.tagName.toLowerCase());
      expect(tag).not.toBe('path');
    }
  });

  test('un clic sur la carte lui donne le focus clavier', async ({ page }) => {
    await page.locator('#nitrates-map').click({ position: { x: 200, y: 200 } });
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

  test('vue par défaut : France entière', async ({ page }) => {
    const v = await page.evaluate(() => {
      const m = (window as any).nitratesMap;
      return { z: m.getZoom(), lat: m.getCenter().lat, lng: m.getCenter().lng };
    });
    expect(v.z).toBe(6);
    expect(v.lat).toBeCloseTo(46.6, 0);
    expect(v.lng).toBeCloseTo(2.45, 0);
  });

  test('plein écran : le bouton bascule dans les deux sens', async ({ page }) => {
    const carte = page.locator('#nitrates-map');
    await page.getByRole('button', { name: 'Afficher la carte en plein écran' }).click();
    await expect(page.getByRole('button', { name: 'Quitter le plein écran (Échap)' })).toBeVisible();
    await page.getByRole('button', { name: 'Quitter le plein écran (Échap)' }).click();
    await expect(page.getByRole('button', { name: 'Afficher la carte en plein écran' })).toBeVisible();
    expect(await page.evaluate(() => document.fullscreenElement)).toBeNull();
    await expect(carte).not.toHaveClass(/nitrates-map--plein-ecran/);
  });

  test('plein écran (repli sans API) : Entrée ouvre, Échap ferme, Tab hors carte ferme', async ({
    page,
  }) => {
    await page.addInitScript(() => {
      Object.defineProperty(Element.prototype, 'requestFullscreen', { value: undefined });
    });
    await page.reload();
    const carte = page.locator('#nitrates-map');
    const bouton = page.locator('.nitrates-map-plein-ecran button');
    await bouton.focus();
    await page.keyboard.press('Enter');
    await expect(carte).toHaveClass(/nitrates-map--plein-ecran/);
    // Entré au clavier : le focus passe sur toute la carte.
    await expect(carte).toBeFocused();
    await page.keyboard.press('Escape');
    await expect(carte).not.toHaveClass(/nitrates-map--plein-ecran/);
    // Réouvre puis sort du cadre au Tab (après la légende) : le plein écran se ferme.
    await bouton.focus();
    await page.keyboard.press('Enter');
    await expect(carte).toHaveClass(/nitrates-map--plein-ecran/);
    for (let i = 0; i < 10; i++) {
      await page.keyboard.press('Tab');
      if (!(await page.evaluate(() => document.getElementById('nitrates-map')!.contains(document.activeElement)))) break;
    }
    await expect(carte).not.toHaveClass(/nitrates-map--plein-ecran/);
  });

  test('Entrée sur la carte : on reste sur la carte, sans défilement', async ({ page }) => {
    await page.evaluate(() => (window as any).nitratesMap.setView([48.96, 4.36], 13, { animate: false }));
    await page.locator('#nitrates-map').focus();
    // Le focus fait défiler en douceur (scroll-behavior DSFR) : on attend la fin.
    await page.waitForTimeout(1000);
    const avant = await page.evaluate(() => window.scrollY);
    await page.keyboard.press('Enter');
    await expect(page.locator('#form-after-localisation')).toBeVisible({ timeout: 15000 });
    await page.waitForTimeout(500);
    await expect(page.locator('#nitrates-map')).toBeFocused();
    expect(await page.evaluate(() => window.scrollY)).toBe(avant);
  });

  test('clic souris sur la carte : le Tab suivant mène à la 1re question', async ({ page }) => {
    await page.evaluate(() => (window as any).nitratesMap.setView([48.96, 4.36], 13, { animate: false }));
    await page.locator('#nitrates-map').click({ position: { x: 300, y: 250 } });
    await expect(page.locator('#form-after-localisation')).toBeVisible({ timeout: 15000 });
    await expect(page.locator('.nitrates-depart-tab')).toBeFocused();
    await page.keyboard.press('Tab');
    const nom = await page.evaluate(() => (document.activeElement as HTMLInputElement).name);
    expect(nom).toBe('cflow_destination');
  });

  test('plein écran au clavier : focus sur toute la carte, aide et raccourcis', async ({ page }) => {
    await page.addInitScript(() => {
      Object.defineProperty(Element.prototype, 'requestFullscreen', { value: undefined });
    });
    await page.reload();
    const carte = page.locator('#nitrates-map');
    const aide = page.locator('.nitrates-map-aide');
    await page.locator('#map-search').focus();
    await page.keyboard.press('Tab');
    await expect(aide).toContainText('plein écran');
    await page.keyboard.press('Tab');
    await page.keyboard.press('Enter');
    await expect(carte).toHaveClass(/nitrates-map--plein-ecran/);
    await expect(carte).toBeFocused();
    await expect(aide).toContainText('quitter le plein écran');
    await page.keyboard.press('l');
    await expect(page.locator('.leaflet-control-layers-base input:checked')).toBeFocused();
    await expect(aide).toContainText('revenir à la carte');
    await page.keyboard.press('c');
    await expect(carte).toBeFocused();
    await page.keyboard.press('f');
    await expect(carte).not.toHaveClass(/nitrates-map--plein-ecran/);
  });

  test('plein écran à la souris : le focus reste sur le bouton, pas d\'aide clavier', async ({
    page,
  }) => {
    await page.getByRole('button', { name: 'Afficher la carte en plein écran' }).click();
    await expect(page.getByRole('button', { name: 'Quitter le plein écran (Échap)' })).toBeFocused();
    await expect(page.locator('.nitrates-map-aide')).toBeHidden();
    await page.getByRole('button', { name: 'Quitter le plein écran (Échap)' }).click();
  });

  test('chargement ZV + ZAR en parallèle : une ligne par couche, masquées à la fin', async ({
    page,
  }) => {
    // Réponses retardées pour voir les deux chargements en même temps.
    await page.route('**/geojson/**', async (route) => {
      await new Promise((r) => setTimeout(r, 1500));
      await route.continue();
    });
    const legende = page.locator('.leaflet-control-layers');
    await legende.getByLabel('Zones vulnérables nitrates').check();
    await legende.getByLabel("Zones d'action renforcée (ZAR)").check();
    const lignes = page.locator('.nitrates-map-chargement:visible');
    await expect(lignes).toHaveCount(2);
    await expect(legende).toContainText('Chargement des zones vulnérables…');
    await expect(legende).toContainText("Chargement des zones d'action renforcée…");
    await expect(lignes).toHaveCount(0, { timeout: 20000 });
    await expect(page.locator('.leaflet-overlay-pane path').first()).toBeAttached();
  });

  test('décocher pendant le chargement masque la ligne, recocher la réaffiche', async ({ page }) => {
    await page.route('**/geojson/zar/', async (route) => {
      await new Promise((r) => setTimeout(r, 2500));
      await route.continue();
    });
    const zar = page.locator('.leaflet-control-layers').getByLabel("Zones d'action renforcée (ZAR)");
    await zar.check();
    await expect(page.locator('.nitrates-map-chargement:visible')).toHaveCount(1);
    await zar.uncheck();
    await expect(page.locator('.nitrates-map-chargement:visible')).toHaveCount(0);
    await zar.check();
    await expect(page.locator('.nitrates-map-chargement:visible')).toHaveCount(1);
    await expect(page.locator('.nitrates-map-chargement:visible')).toHaveCount(0, {
      timeout: 20000,
    });
  });

  test('échec du chargement : message et bouton Réessayer', async ({ page }) => {
    await page.route('**/geojson/zar/', (route) => route.abort());
    const legende = page.locator('.leaflet-control-layers');
    await legende.getByLabel("Zones d'action renforcée (ZAR)").check();
    await expect(legende).toContainText("Échec du chargement des zones d'action renforcée.");
    await page.unroute('**/geojson/zar/');
    await legende.getByRole('button', { name: 'Réessayer' }).click();
    await expect(page.locator('.nitrates-map-chargement:visible')).toHaveCount(0, {
      timeout: 20000,
    });
    await expect(page.locator('.leaflet-overlay-pane path').first()).toBeAttached();
  });
});
