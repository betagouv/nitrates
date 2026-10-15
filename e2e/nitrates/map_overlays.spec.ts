import { test, expect } from '@playwright/test';

test.describe('Nitrates map — fonds, overlays, contrôles', () => {
  test('LayerControl is rendered with 3 base layers and 4 overlays', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('#nitrates-map')).toHaveClass(/leaflet-container/);

    const layerControl = page.locator('.leaflet-control-layers');
    await expect(layerControl).toBeVisible();
    // 3 fonds de carte (#531 : « Automatique » par défaut)
    await expect(layerControl).toContainText('Automatique (selon le zoom)');
    await expect(layerControl).toContainText('Plan IGN');
    await expect(layerControl).toContainText('Photo aérienne');
    // 4 overlays : parcelles RPG et communes (#583), ZV, ZAR (#34).
    await expect(layerControl).toContainText('Parcelles agricoles (RPG)');
    await expect(layerControl).toContainText('Communes');
    await expect(layerControl).not.toContainText('Cadastre');
    await expect(layerControl).toContainText('Zones vulnérables nitrates');
    await expect(layerControl).toContainText("Zones d'action renforcée (ZAR)");
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

  test('Communes (#583) : limites sans parcelles cadastrales, noms des communes, encart zoomé', async ({
    page,
  }) => {
    const tuilesPci: string[] = [];
    page.on('request', (r) => {
      const m = r.url().match(/\/tms\/1\.0\.0\/PCI\/(\d+)\//);
      if (m) tuilesPci.push(m[1]);
    });
    await page.goto('/');
    await expect(page.locator('#nitrates-map')).toHaveClass(/leaflet-container/);
    const communes = page.locator('.leaflet-control-layers').getByLabel('Communes');
    // Cochee par defaut.
    await expect(communes).toBeChecked();

    // Echelle ~1 km : limites (tuiles PCI) et noms des communes.
    await page.evaluate(() => (window as any).nitratesMap.setView([48.75, 4.55], 12, { animate: false }));
    await expect.poll(() => tuilesPci.length, { timeout: 10000 }).toBeGreaterThan(0);
    const noms = page.locator('.nitrates-commune-nom span');
    await expect.poll(() => noms.count(), { timeout: 10000 }).toBeGreaterThan(5);
    await expect(noms.filter({ hasText: 'Loisy-sur-Marne' })).toHaveCount(1);

    // Zoome pres (100 m) : jamais de tuile PCI au-dela du 14 (les parcelles
    // cadastrales y arrivent) ; chef-lieu hors champ -> encart du nom.
    await page.evaluate(() => (window as any).nitratesMap.setView([48.7508, 4.5527], 16, { animate: false }));
    await expect(page.locator('.nitrates-commune-courante')).toHaveText('Commune : Loisy-sur-Marne', {
      timeout: 10000,
    });
    expect(tuilesPci.every((z) => Number(z) <= 14)).toBe(true);

    // Decochee : plus de noms ni d'encart.
    await communes.uncheck();
    await expect(noms).toHaveCount(0);
    await expect(page.locator('.nitrates-commune-courante')).toHaveCount(0);
  });

  test('ZV overlay covers every metropolitan bassin with distinct colors', async ({
    page,
  }) => {
    await page.goto('/');
    await expect(page.locator('#nitrates-map')).toHaveClass(/leaflet-container/);

    // Codes servis par l'endpoint : référence pour vérifier que la carte
    // affiche tout ce qu'elle reçoit.
    const servis: string[] = await page.evaluate(async () => {
      const r = await fetch((window as any).NITRATES_ZV_GEOJSON_URL);
      const data = await r.json();
      return [
        ...new Set<string>(data.features.map((f: any) => f.properties.bassin)),
      ].sort();
    });

    await page
      .locator('.leaflet-control-layers-overlays label')
      .filter({ hasText: 'Zones vulnérables nitrates' })
      .locator('input[type="checkbox"]')
      .check();

    // NB : chaque zone ZV est un MultiPolygon que Leaflet éclate en N
    // sous-layers -> on compte les BASSINS distincts, pas les sous-layers.
    const rendu = () =>
      page.evaluate(() => {
        const map = (window as any).nitratesMap;
        const colors = new Set<string>();
        const bassins = new Set<string>();
        map.eachLayer((layer: any) => {
          if (typeof layer.getLayers === 'function') {
            layer.getLayers().forEach((sub: any) => {
              const props = sub.feature && sub.feature.properties;
              if (!props) return;
              if (props.bassin) bassins.add(props.bassin);
              if (sub.options && sub.options.fillColor) colors.add(sub.options.fillColor);
            });
          }
        });
        return { bassins: [...bassins].sort(), colorCount: colors.size };
      });

    await expect
      .poll(async () => (await rendu()).bassins, { timeout: 15000 })
      .toEqual(servis);

    // Couverture métier indépendante du millésime : les 8 bassins DCE de
    // métropole sont couverts, et aucun code inconnu. Depuis le millésime
    // 2026, Rhin (FRC) et Meuse (FRB1) sont livrés d'un bloc sous le code
    // composite « FRB1-FRC » (cf. bassins.py) : on le décompose.
    const METROPOLE = ['FRA', 'FRB1', 'FRB2', 'FRC', 'FRD', 'FRF', 'FRG', 'FRH'];
    const couverts = new Set(servis.flatMap((code) => code.split('-')));
    expect([...couverts].filter((c) => !METROPOLE.includes(c))).toEqual([]);
    expect(METROPOLE.filter((c) => !couverts.has(c))).toEqual([]);

    // Au moins 6 couleurs : Escaut (FRA) et Sambre (FRB2) partagent celle
    // d'Artois-Picardie, comme Rhin (FRC) et Meuse (FRB1) celle de Rhin-Meuse.
    expect((await rendu()).colorCount).toBeGreaterThanOrEqual(6);
  });

  test('clicking on a parcel fills the debug cartouche', async ({
    page,
  }) => {
    // Le panneau debug (#nitrates-debug) n'existe que sur /simulateur/
    // (la home publique / le masque).
    await page.goto('/simulateur/');
    await expect(page.locator('#nitrates-map')).toHaveClass(/leaflet-container/);

    // Rennes (Ille-et-Vilaine). On vérifie seulement que le cartouche se
    // remplit (territoire identifié) ; l'info parcelle vient désormais du
    // cadastre IGN.
    await page.evaluate(() => {
      const w = window as any;
      w.nitratesMap.fire('click', {
        latlng: w.L.latLng(48.1215230, -1.5636201),
      });
    });

    const cartouche = page.locator('#nitrates-debug');
    await expect(cartouche).toContainText('Informations parcelle', {
      timeout: 10000,
    });
    await expect(cartouche).toContainText(/[Pp]arcelle|Bretagne|35/);
  });
});
