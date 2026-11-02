import { Locator, Page } from '@playwright/test';

/**
 * Soumet le formulaire du simulateur et attend que la page soit a jour (#273).
 *
 * Depuis #273, « Lancer la simulation » / « Suivant » partent en htmx : la page
 * n'est plus rechargee, donc `waitForLoadState('networkidle')` apres le clic
 * rend la main tout de suite, avant la reponse. On attend a la place
 * l'evenement `nitrates:rendu-remplace` emis par soumission_partielle.js, ou le
 * chargement d'une nouvelle page si la soumission est repassee en navigation
 * classique (repli sur erreur).
 */
export async function soumettreSimulation(page: Page, bouton?: Locator) {
  await page.evaluate(() => {
    const w = window as any;
    w.__nitratesRenduRemplace = false;
    document.addEventListener(
      'nitrates:rendu-remplace',
      () => {
        w.__nitratesRenduRemplace = true;
      },
      { once: true },
    );
  });
  await (bouton ?? page.locator('#form-simulateur button[type="submit"]')).click();
  // Rendu htmx -> true ; nouvelle page (repli) -> marqueur absent (undefined).
  await page.waitForFunction(
    () => (window as any).__nitratesRenduRemplace !== false,
    null,
    { timeout: 60000 },
  );
  await page.waitForLoadState('networkidle');
}
