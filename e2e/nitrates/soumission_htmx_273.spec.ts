import { test, expect, Page } from '@playwright/test';
import { soumettreSimulation } from './soumission';

/**
 * #273 / #643 : la soumission du simulateur passe en htmx. Les questions
 * complementaires et le resultat apparaissent sans rechargement de page (plus
 * de « saut » vers le haut), la carte reste en place, l'URL suit chaque etape
 * et le retour arriere revient a l'etape precedente.
 */

const REIMS_LNG = 4.0345;
const REIMS_LAT = 49.2583;

// Mais + fraction liquide de digestat : le serveur pose la QC fertirrigation.
async function remplirMaisDigestat(page: Page) {
  await page.goto(`/simulateur/?lng=${REIMS_LNG}&lat=${REIMS_LAT}`);
  await expect
    .poll(
      async () =>
        page.locator('#q_destination_epandage input[type="radio"]').count(),
      { timeout: 15000 },
    )
    .toBeGreaterThan(0);
  const cocher = async (name: string, index: number) => {
    await page
      .locator(`input[type=radio][name="${name}"]`)
      .nth(index)
      .evaluate((el: HTMLInputElement) => el.click());
    await page.waitForTimeout(250);
  };
  await cocher('cflow_destination', 2); // culture principale
  await cocher('cflow_type_couvert', 1); // culture de printemps
  await cocher('cflow_sous_culture', 0); // mais
  await page.locator('label[for="id_categorie_fertilisant__digestats"]').click();
  await page
    .locator(
      'label[for="id_sous_fertilisant__fraction_liquide_digestat_methanisation"]',
    )
    .click();
}

// Marqueur pose dans la page : il disparait si la page est rechargee.
async function marquerPage(page: Page) {
  await page.evaluate(() => {
    (window as any).__pageInitiale = true;
  });
}

async function pageRechargee(page: Page): Promise<boolean> {
  return page.evaluate(() => (window as any).__pageInitiale !== true);
}

test.describe('#273 soumission htmx du simulateur', () => {
  test('QC puis resultat sans rechargement, carte conservee, URL a jour', async ({
    page,
  }) => {
    await remplirMaisDigestat(page);
    await marquerPage(page);

    // 1re soumission : la QC fertirrigation apparait sous le formulaire.
    await soumettreSimulation(page);
    await expect(page.locator('#qc-bloc[data-qc-en-attente]')).toHaveCount(1);
    expect(await pageRechargee(page)).toBe(false);
    await expect(page.locator('#nitrates-map.leaflet-container')).toHaveCount(1);
    await expect(
      page.locator('#form-submit-row button[type="submit"]'),
    ).toHaveText(/Suivant/);
    const urlQc = new URL(page.url());
    expect(urlQc.searchParams.get('categorie_fertilisant')).toBe('digestats');
    expect(urlQc.searchParams.get('fertirrigation')).toBeNull();

    // Reponse a la QC puis « Suivant » : resultat final, toujours sans
    // rechargement.
    await page.locator('label[for*="fertirrigation"][for*="True"]').first().click();
    await soumettreSimulation(page);
    await expect(page.locator('.result-col')).toBeVisible();
    await expect(page.locator('.results-row')).toHaveClass(/layout--split/);
    await expect(page.locator('#recap-choix')).toBeVisible();
    await expect(page.locator('#form-after-localisation')).toBeHidden();
    await expect(page.locator('#form-submit-row')).toBeHidden();
    await expect(page.locator('#nitrates-progress-bar')).toBeHidden();
    await expect(page.locator('#qc-bloc[data-qc-en-attente]')).toHaveCount(0);
    expect(await pageRechargee(page)).toBe(false);
    expect(new URL(page.url()).searchParams.get('fertirrigation')).toBe('True');
  });

  test('retour arriere : revient a l etape QC, puis avance au resultat', async ({
    page,
  }) => {
    await remplirMaisDigestat(page);
    await soumettreSimulation(page);
    await expect(page.locator('#qc-bloc[data-qc-en-attente]')).toHaveCount(1);
    await page.locator('label[for*="fertirrigation"][for*="True"]').first().click();
    await soumettreSimulation(page);
    await expect(page.locator('.result-col')).toBeVisible();

    await page.goBack();
    await expect(page.locator('#qc-bloc[data-qc-en-attente]')).toHaveCount(1, {
      timeout: 30000,
    });
    await expect(page.locator('.result-col')).toHaveCount(0);
    expect(new URL(page.url()).searchParams.get('fertirrigation')).toBeNull();

    await page.goForward();
    await expect(page.locator('.result-col')).toBeVisible({ timeout: 30000 });
  });

  test('Modifier puis relancer : nouveau resultat sans rechargement', async ({
    page,
  }) => {
    await remplirMaisDigestat(page);
    await soumettreSimulation(page);
    await page.locator('label[for*="fertirrigation"][for*="True"]').first().click();
    await soumettreSimulation(page);
    await expect(page.locator('.result-col')).toBeVisible();
    await marquerPage(page);

    // Retour en saisie, autre fertilisant (engrais mineral, sans QC).
    await page.locator('[data-recap-modifier]').click();
    await expect(page.locator('#form-after-localisation')).toBeVisible();
    await page.locator('label[for="id_categorie_fertilisant__engrais_mineral"]').click();
    const sousFertilisant = page.locator('input[name="sous_fertilisant"]');
    if (await sousFertilisant.count()) {
      await sousFertilisant
        .first()
        .evaluate((el: HTMLInputElement) => el.click());
    }
    await soumettreSimulation(page);

    // Mais + engrais mineral : nouvelle QC (culture irriguee), l'ancienne
    // (fertirrigation) a disparu avec le changement de fertilisant.
    await expect(page.locator('#qc-bloc[data-qc-en-attente]')).toHaveCount(1);
    await expect(page.locator('[data-qc-champ="culture_irriguee"]')).toHaveCount(1);
    await expect(page.locator('[data-qc-champ="fertirrigation"]')).toHaveCount(0);
    const urlQc = new URL(page.url());
    expect(urlQc.searchParams.get('categorie_fertilisant')).toBe('engrais_mineral');
    // La reponse QC du parcours precedent ne repart pas.
    expect(urlQc.searchParams.get('fertirrigation')).toBeNull();

    await page
      .locator('[data-qc-champ="culture_irriguee"] input[type="radio"]')
      .first()
      .evaluate((el: HTMLInputElement) => el.click());
    await soumettreSimulation(page);
    await expect(page.locator('.result-col')).toBeVisible();
    await expect(page.locator('#recap-choix')).toBeVisible();
    expect(await pageRechargee(page)).toBe(false);
  });

  test('erreur serveur : repli sur la soumission classique', async ({ page }) => {
    await remplirMaisDigestat(page);
    await marquerPage(page);
    await page.route('**/simulateur/?*', async (route) => {
      if (route.request().headers()['hx-request']) {
        await route.fulfill({ status: 500, body: 'erreur' });
      } else {
        await route.continue();
      }
    });
    await soumettreSimulation(page);
    await expect(page.locator('#qc-bloc[data-qc-en-attente]')).toHaveCount(1);
    expect(await pageRechargee(page)).toBe(true);
  });
});
