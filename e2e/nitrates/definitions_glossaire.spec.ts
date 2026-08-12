import { test, expect } from '@playwright/test';

// Cartes #110 / #288 — page « Aide & définitions » + glossaire cliquable.
//
// Pré-requis data : les 17 définitions juristes seedées en DB
// (python manage.py seed_contenus_rich).
//
// Serial : même précaution que simulateur.spec.ts (cold-start chromium).
test.describe.configure({ mode: 'serial' });

// Reims (Marne, Grand Est, ZV) — mêmes coordonnées que les specs de branches.
const REIMS_LNG = 4.0345;
const REIMS_LAT = 49.2583;

test.describe('Nitrates — onglets + page Aide & définitions (#110/#288)', () => {
  test("la barre d'onglets est presente et l'onglet actif suit la page", async ({ page }) => {
    await page.goto('/');
    const nav = page.locator('.nitrates-nav');
    await expect(nav).toBeVisible();
    // Sur la home, l'onglet actif est « Simulateur ».
    await expect(nav.locator('a[aria-current="page"]')).toHaveText('Simulateur');

    // Clic sur l'onglet -> page définitions, l'actif bascule.
    await nav.getByRole('link', { name: 'Aide & définitions' }).click();
    await expect(page).toHaveURL(/\/definitions\/$/);
    await expect(nav.locator('a[aria-current="page"]')).toHaveText('Aide & définitions');
  });

  test('la page definitions affiche breadcrumb, sommaire, sections et tableau', async ({ page }) => {
    await page.goto('/definitions/');
    // Breadcrumb : « Accueil » ramène au simulateur.
    await expect(page.locator('.fr-breadcrumb')).toBeAttached();
    // Sommaire latéral avec les 4 sections.
    const sidemenu = page.locator('.fr-sidemenu');
    await expect(sidemenu.getByRole('link', { name: 'Azote et bilans' })).toBeAttached();
    // Le tableau des types de fertilisants (bloc tableau -> fr-table DSFR).
    await expect(page.locator('.fr-table table')).toBeVisible();
    await expect(page.locator('.fr-table')).toContainText('Lisiers');
    // Une définition juriste verbatim est bien rendue.
    await expect(page.locator('#azote-efficace')).toContainText(
      "Somme de l'azote présent dans un fertilisant azoté"
    );
  });

  test('le clic sommaire ancre sur la definition (exergue :target)', async ({ page }) => {
    await page.goto('/definitions/');
    // Le sommaire pointe les sections ; on teste l'ancre directe d'un terme
    // (celle utilisée par la carte flottante et les liens de termes).
    await page.goto('/definitions/#interculture-longue');
    await expect(page.locator('#interculture-longue')).toBeInViewport();
  });

  test('un terme dans une question du form est clique -> carte flottante', async ({ page }) => {
    // Le formulaire est verrouillé tant qu'aucune localisation n'est posée :
    // on arrive avec lat/lng dans l'URL comme les specs de branches (Reims).
    await page.goto(`/simulateur/?lng=${REIMS_LNG}&lat=${REIMS_LAT}`);
    // Attend le JSON glossaire + glossaire.js (defer, en dernier).
    await page.waitForSelector('#glossaire-data', { state: 'attached' });

    // Premier terme VISIBLE du formulaire déverrouillé (Q1 contient « sol non
    // cultivé », défini par les juristes — linkifié par glossaire.js).
    const terme = page.locator('a.def-terme:visible').first();
    await expect(terme).toBeVisible({ timeout: 15000 });

    await terme.click();
    const carte = page.locator('#def-carte');
    await expect(carte).toBeVisible();
    await expect(carte.locator('#def-carte-titre')).not.toBeEmpty();
    // Le lien « Voir toutes les définitions » pointe la page ancrée.
    await expect(carte.locator('#def-carte-toutes')).toHaveAttribute(
      'href',
      /\/definitions\/#.+/
    );

    // Échap ferme la carte.
    await page.keyboard.press('Escape');
    await expect(carte).toBeHidden();
  });

  test("dans un label radio : l'icône ouvre la carte, le texte du terme coche le radio", async ({ page }) => {
    // Dans un label radio, le terme n'est PAS un lien (sinon un label composé
    // presque uniquement du terme, comme « Sol non cultivé (…) » en Q1 #335,
    // ne cocherait plus le radio) : le texte garde le pointillé (span) et
    // seule l'icône ⓘ accolée ouvre la définition.
    await page.goto(`/simulateur/?lng=${REIMS_LNG}&lat=${REIMS_LAT}`);
    await page.waitForSelector('#glossaire-data', { state: 'attached' });
    const labelAvecTerme = page
      .locator('label.fr-label:visible', { has: page.locator('a.def-terme--icone') })
      .first();
    await labelAvecTerme.waitFor({ timeout: 15000 });

    const forId = await labelAvecTerme.getAttribute('for');
    const radio = page.locator(`#${forId}`);

    // Clic sur l'ICÔNE : la carte s'ouvre, le radio ne se coche PAS.
    await labelAvecTerme.locator('a.def-terme--icone').first().click();
    await expect(page.locator('#def-carte')).toBeVisible();
    await expect(radio).not.toBeChecked();
    await page.keyboard.press('Escape');

    // Clic sur le TEXTE du terme (span, pas lien) : le radio se coche.
    await labelAvecTerme.locator('.def-terme-libelle').first().click();
    await expect(radio).toBeChecked();
  });

  test('theme sombre : la page definitions reste lisible', async ({ page }) => {
    await page.goto('/definitions/');
    await page.evaluate(() => {
      document.documentElement.setAttribute('data-fr-theme', 'dark');
    });
    // Les tokens DSFR doivent basculer le fond (pas de couleur en dur).
    const bg = await page.evaluate(
      () => getComputedStyle(document.body).backgroundColor
    );
    expect(bg).not.toBe('rgb(255, 255, 255)');
    await expect(page.locator('h1')).toBeVisible();
  });
});
