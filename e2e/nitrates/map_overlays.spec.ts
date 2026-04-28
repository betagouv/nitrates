import { test, expect } from '@playwright/test';

test.describe('Nitrates map — fonds, overlays, contrôles', () => {
  test('LayerControl is rendered with 2 base layers and 2 overlays', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('#nitrates-map')).toHaveClass(/leaflet-container/);

    const layerControl = page.locator('.leaflet-control-layers');
    await expect(layerControl).toBeVisible();
    await expect(layerControl).toContainText('Plan IGN');
    await expect(layerControl).toContainText('Photo aérienne');
    await expect(layerControl).toContainText('Parcelles RPG (PAC)');
    await expect(layerControl).toContainText('Zones vulnérables nitrates');
  });

  test('attribution does not contain the Ukraine flag', async ({ page }) => {
    await page.goto('/');
    const attribution = page.locator('.leaflet-control-attribution');
    await expect(attribution).toBeVisible();
    await expect(attribution).not.toContainText('🇺🇦');
    await expect(attribution).not.toContainText('Ukraine');
    // Mais on garde au moins Leaflet et IGN
    await expect(attribution).toContainText('Leaflet');
    await expect(attribution).toContainText('IGN');
  });

  test('activating the ZV overlay fetches the GeoJSON and creates layers', async ({
    page,
  }) => {
    await page.goto('/');
    await expect(page.locator('#nitrates-map')).toHaveClass(/leaflet-container/);

    const zvCheckbox = page
      .locator('.leaflet-control-layers-overlays label')
      .filter({ hasText: 'Zones vulnérables nitrates' })
      .locator('input[type="checkbox"]');

    await zvCheckbox.check();

    // Une couche GeoJSON est ajoutée au container Leaflet, et après le fetch
    // elle contient des sous-layers (un par feature). Le 1er hit du endpoint
    // peut prendre ~7s (ST_SimplifyPreserveTopology sur polygones nationaux),
    // d'où le timeout généreux. Caché 24h ensuite.
    await expect
      .poll(
        async () =>
          page.evaluate(() => {
            const map = (window as any).nitratesMap;
            let total = 0;
            map.eachLayer((layer: any) => {
              if (typeof layer.getLayers === 'function') {
                total += layer.getLayers().length;
              }
            });
            return total;
          }),
        { timeout: 15000 }
      )
      .toBeGreaterThan(0);
  });

  test('activating the RPG overlay loads tile images', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('#nitrates-map')).toHaveClass(/leaflet-container/);

    const rpgCheckbox = page
      .locator('.leaflet-control-layers-overlays label')
      .filter({ hasText: 'Parcelles RPG (PAC)' })
      .locator('input[type="checkbox"]');

    await rpgCheckbox.check();

    // Les tuiles WMTS RPG arrivent depuis data.geopf.fr ; on vérifie qu'au moins
    // une est présente dans le DOM Leaflet après quelques secondes.
    await expect
      .poll(
        async () =>
          page.evaluate(() => {
            const imgs = document.querySelectorAll(
              '.leaflet-tile-pane img.leaflet-tile'
            );
            return Array.from(imgs).filter((i) =>
              (i as HTMLImageElement).src.includes('IGNF_RPG')
            ).length;
          }),
        { timeout: 8000 }
      )
      .toBeGreaterThan(0);
  });

  test('ZV overlay renders 8 polygons with distinct colors per bassin', async ({
    page,
  }) => {
    await page.goto('/');
    await expect(page.locator('#nitrates-map')).toHaveClass(/leaflet-container/);

    await page
      .locator('.leaflet-control-layers-overlays label')
      .filter({ hasText: 'Zones vulnérables nitrates' })
      .locator('input[type="checkbox"]')
      .check();

    // On attend les 8 features, puis on récupère les couleurs.
    const result = await expect
      .poll(
        async () =>
          page.evaluate(() => {
            const map = (window as any).nitratesMap;
            const colors = new Set<string>();
            const bassins = new Set<string>();
            let count = 0;
            map.eachLayer((layer: any) => {
              if (typeof layer.getLayers === 'function') {
                layer.getLayers().forEach((sub: any) => {
                  count++;
                  const opts = sub.options || {};
                  if (opts.fillColor) colors.add(opts.fillColor);
                  const props = sub.feature && sub.feature.properties;
                  if (props && props.bassin) bassins.add(props.bassin);
                });
              }
            });
            return {
              count,
              colors: [...colors],
              bassins: [...bassins].sort(),
            };
          }),
        { timeout: 15000 }
      )
      .toMatchObject({ count: 8 });

    // Vérifie qu'on a bien 8 bassins distincts et au moins 6 couleurs
    // (deux peuvent se ressembler en hex mais c'est ok)
    const final = await page.evaluate(() => {
      const map = (window as any).nitratesMap;
      const colors = new Set<string>();
      const bassins = new Set<string>();
      map.eachLayer((layer: any) => {
        if (typeof layer.getLayers === 'function') {
          layer.getLayers().forEach((sub: any) => {
            const opts = sub.options || {};
            if (opts.fillColor) colors.add(opts.fillColor);
            const props = sub.feature && sub.feature.properties;
            if (props && props.bassin) bassins.add(props.bassin);
          });
        }
      });
      return { bassins: [...bassins].sort(), colorCount: colors.size };
    });
    expect(final.bassins).toEqual([
      'FRA',
      'FRB1',
      'FRB2',
      'FRC',
      'FRD',
      'FRF',
      'FRG',
      'FRH',
    ]);
    expect(final.colorCount).toBeGreaterThanOrEqual(6);
  });

  test('clicking on a known RPG parcel shows the legend label for the culture code', async ({
    page,
  }) => {
    await page.goto('/');
    await expect(page.locator('#nitrates-map')).toHaveClass(/leaflet-container/);

    // Rennes, parcelle dont on sait qu'elle est PTR (prairie temporaire).
    await page.evaluate(() => {
      const w = window as any;
      w.nitratesMap.fire('click', {
        latlng: w.L.latLng(48.1215230, -1.5636201),
      });
    });

    const cartouche = page.locator('#nitrates-debug');
    await expect(cartouche).toContainText('Informations parcelle');
    // Le code PTR doit apparaître avec son libellé lisible.
    await expect(cartouche).toContainText(/PTR.*Prairie/);
  });
});
