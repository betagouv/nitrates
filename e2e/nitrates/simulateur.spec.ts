import { test, expect } from '@playwright/test';

// Le simulateur charge Leaflet + WMTS IGN + GeoJSON ZV ; les workers
// paralleles peuvent OOM-crash le conteneur node. On serialise par fichier.
test.describe.configure({ mode: 'serial' });

// Reims (Marne, Grand Est, ZV bassin Seine-Normandie)
const REIMS_LNG = 4.0345;
const REIMS_LAT = 49.2583;

// Quelque part en mer atlantique, hors France (et donc hors ZV)
const OFFSHORE_LNG = -30.0;
const OFFSHORE_LAT = 30.0;

/**
 * Attend que la cascade JS ait fini de fetch arbre+referentiels et peuple
 * le select occupation_sol. Plus robuste que de matcher sur des options
 * specifiques.
 */
async function waitForCascadeReady(page) {
  await expect
    .poll(async () =>
      page.locator('#id_occupation_sol option').count()
    , { timeout: 10000 })
    .toBeGreaterThan(1);
}

test.describe('Simulateur nitrates : page formulaire', () => {
  test('charge la carte, le panneau debug et les selects vides', async ({ page }) => {
    await page.goto('/simulateur/');

    await expect(page).toHaveTitle(/Simulateur nitrates/);
    await expect(page.locator('h1')).toHaveText('Simulateur nitrates');

    // Carte Leaflet presente
    const map = page.locator('#nitrates-map');
    await expect(map).toBeVisible();
    await expect(map).toHaveClass(/leaflet-container/);

    // Panneau debug
    await expect(page.locator('#nitrates-debug')).toContainText(
      'Cliquez sur la carte'
    );

    // Inputs lat/lng vides
    await expect(page.locator('#id_lat')).toHaveValue('');
    await expect(page.locator('#id_lng')).toHaveValue('');

    // Selects : seul occupation_sol est actif (mais peut etre vide tant
    // que la cascade n'a pas fini son fetch)
    await expect(page.locator('#id_occupation_sol')).toBeEnabled();
    await expect(page.locator('#id_sous_culture')).toBeDisabled();
    await expect(page.locator('#id_type_fertilisant')).toBeDisabled();
    await expect(page.locator('#id_sous_fertilisant')).toBeDisabled();

    // Attendre que la cascade ait peuple le select avec les choix
    await waitForCascadeReady(page);
    const occupationOptions = await page
      .locator('#id_occupation_sol option')
      .allTextContents();
    expect(occupationOptions.join(' ')).toContain('Sol non cultivé');
    expect(occupationOptions.join(' ')).toContain('Culture principale');
  });

  test('clic carte sur Reims pre-remplit lat/lng et le panneau debug', async ({
    page,
  }) => {
    await page.goto('/simulateur/');
    await expect(page.locator('#nitrates-map')).toHaveClass(/leaflet-container/);

    await page.evaluate(([lng, lat]) => {
      const w = window as any;
      w.nitratesMap.fire('click', { latlng: w.L.latLng(lat, lng) });
    }, [REIMS_LNG, REIMS_LAT]);

    // lat/lng pre-remplis
    await expect(page.locator('#id_lat')).toHaveValue(/49\.258/);
    await expect(page.locator('#id_lng')).toHaveValue(/4\.034/);

    // Panneau debug rempli (depuis le meme endpoint que la home)
    const cartouche = page.locator('#nitrates-debug');
    await expect(cartouche).toContainText('Informations parcelle');
    await expect(cartouche).toContainText('Grand Est');
    await expect(cartouche).toContainText(/OUI.*Seine-Normandie/);
  });
});

test.describe('Simulateur nitrates : cascade des selects', () => {
  test('choisir une occupation active le select sous_culture avec les bons choix', async ({
    page,
  }) => {
    await page.goto('/simulateur/');
    // Attendre que la cascade soit initialisee (fetch arbre + referentiels)
    await waitForCascadeReady(page);

    await page.locator('#id_occupation_sol').selectOption('culture_principale');

    await expect(page.locator('#id_sous_culture')).toBeEnabled();
    const sousCultureOptions = await page
      .locator('#id_sous_culture option')
      .allTextContents();
    expect(sousCultureOptions.join(' ')).toContain('Colza');
    expect(sousCultureOptions.join(' ')).toContain('Luzerne');
  });

  test('choisir sol_non_cultive desactive les selects suivants (court-circuit)', async ({
    page,
  }) => {
    await page.goto('/simulateur/');
    await waitForCascadeReady(page);

    await page.locator('#id_occupation_sol').selectOption('sol_non_cultive');

    // Pas de question sous_culture pour cette branche
    await expect(page.locator('#id_sous_culture')).toBeDisabled();
    await expect(page.locator('#id_sous_culture option').first()).toContainText(
      'Non applicable'
    );
  });

  test('cascade complete jusqu au type_fertilisant', async ({ page }) => {
    await page.goto('/simulateur/');
    await waitForCascadeReady(page);

    await page.locator('#id_occupation_sol').selectOption('culture_principale');
    await page.locator('#id_sous_culture').selectOption('colza');

    await expect(page.locator('#id_type_fertilisant')).toBeEnabled();
    const typeOptions = await page
      .locator('#id_type_fertilisant option')
      .allTextContents();
    expect(typeOptions.join(' ')).toContain('type_0');
    expect(typeOptions.join(' ')).toContain('type_II');

    // Le choix sous_culture est conserve (regression test du bug C4d)
    await expect(page.locator('#id_sous_culture')).toHaveValue('colza');
  });
});

test.describe('Simulateur nitrates : flow complet et resultats', () => {
  test('flow complet sol_non_cultive -> resultat interdit toute l annee', async ({
    page,
  }) => {
    await page.goto('/simulateur/');
    await waitForCascadeReady(page);

    // Clic carte sur Reims
    await page.evaluate(([lng, lat]) => {
      const w = window as any;
      w.nitratesMap.fire('click', { latlng: w.L.latLng(lat, lng) });
    }, [REIMS_LNG, REIMS_LAT]);

    await page.locator('#id_occupation_sol').selectOption('sol_non_cultive');
    await page.locator('button[type="submit"]').click();

    // Page resultat
    await expect(page).toHaveURL(/\/simulateur\/\?/);
    await expect(page.locator('h1')).toHaveText('Résultat de la simulation');
    await expect(page.locator('body')).toContainText('Directive nitrates');
    await expect(page.locator('body')).toContainText('r_sol_non_cultive');
    await expect(page.locator('body')).toContainText('interdiction');
    // Periode : toute l'annee
    await expect(page.locator('body')).toContainText('01/01');
    await expect(page.locator('body')).toContainText('31/12');
  });

  test('flow complet colza + type_0 -> regle r_colza_type_0', async ({ page }) => {
    await page.goto('/simulateur/');
    await waitForCascadeReady(page);

    await page.evaluate(([lng, lat]) => {
      const w = window as any;
      w.nitratesMap.fire('click', { latlng: w.L.latLng(lat, lng) });
    }, [REIMS_LNG, REIMS_LAT]);

    await page.locator('#id_occupation_sol').selectOption('culture_principale');
    await page.locator('#id_sous_culture').selectOption('colza');
    await page.locator('#id_type_fertilisant').selectOption('type_0');
    await page.locator('button[type="submit"]').click();

    await expect(page).toHaveURL(/\/simulateur\/\?/);
    await expect(page.locator('body')).toContainText('r_colza_type_0');
    await expect(page.locator('body')).toContainText('interdiction');
    // Periode actuelle de la regle (peut evoluer avec le brouillon)
    await expect(page.locator('body')).toContainText('15/12');
    await expect(page.locator('body')).toContainText('15/01');
  });

  test('point hors ZV affiche le message hors zone vulnerable', async ({ page }) => {
    // On va directement avec les query params (carte ne couvre pas l'offshore
    // dans la viewport par defaut)
    await page.goto(`/simulateur/?lng=${OFFSHORE_LNG}&lat=${OFFSHORE_LAT}`);

    await expect(page.locator('h1')).toHaveText('Résultat de la simulation');
    await expect(page.locator('body')).toContainText('Hors zone vulnérable');
    await expect(page.locator('body')).toContainText(
      "ne s'applique pas à cette parcelle"
    );
  });

  test('en ZV sans reponses cascade -> questions complementaires affichees', async ({
    page,
  }) => {
    await page.goto(`/simulateur/?lng=${REIMS_LNG}&lat=${REIMS_LAT}`);

    await expect(page.locator('h1')).toHaveText('Résultat de la simulation');
    await expect(page.locator('body')).toContainText('Questions complémentaires');
    await expect(page.locator('body')).toContainText('occupation_sol');
  });

  test('flow complet via formulaire pre-rempli depuis URL', async ({ page }) => {
    // Page resultat directement, on verifie que le rendu marche
    await page.goto(
      `/simulateur/?lng=${REIMS_LNG}&lat=${REIMS_LAT}` +
        '&occupation_sol=culture_principale' +
        '&sous_culture=colza&type_fertilisant=type_I'
    );

    await expect(page.locator('h1')).toHaveText('Résultat de la simulation');
    await expect(page.locator('body')).toContainText('r_colza_type_I');
    // type_I -> interdit du 15/11 au 15/01
    await expect(page.locator('body')).toContainText('15/11');
    await expect(page.locator('body')).toContainText('15/01');
  });
});

test.describe('Simulateur nitrates : endpoints API', () => {
  // On passe par page.evaluate(fetch) plutot que request.get : la base
  // request de Playwright n'utilise pas le --host-resolver-rules, donc
  // nitrates.local ne resout pas dans le conteneur node.
  test('/api/referentiels/ renvoie un JSON avec les listes fermees', async ({
    page,
  }) => {
    await page.goto('/simulateur/');
    const data = await page.evaluate(() =>
      fetch('/api/referentiels/').then((r) => r.json())
    );
    expect(data).toHaveProperty('types_fertilisants');
    expect(data).toHaveProperty('cultures');
    expect(data).toHaveProperty('codes_prescription');
  });

  test('/api/arbre/ renvoie l arbre PAN national', async ({ page }) => {
    await page.goto('/simulateur/');
    const data = await page.evaluate(() =>
      fetch('/api/arbre/').then((r) => r.json())
    );
    expect(data.arbre.noeud.id).toBe('n_zvn');
  });
});
