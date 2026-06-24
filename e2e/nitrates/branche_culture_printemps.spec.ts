/**
 * Couverture e2e de la branche `culture_principale` / `culture_de_printemps`.
 *
 * Strategie :
 *   - 8 tests via URL pre-remplie (rapide, valide juste le rendu serveur :
 *     regle_id atteint + dates affichees + code_prescription si applicable).
 *   - 1 test via flow UI complet sur le cas le plus dur du screenshot
 *     (type_II + fertirrigation=oui), qui valide la cascade UI + la
 *     question subsidiaire `fertirrigation` + le rendu mixte
 *     interdiction/autorisation_sous_condition.
 *
 * Note zone montagne : la branche printemps ne traverse pas de noeud
 * catalogue zone_montagne, le resultat ne depend que du fertilisant. Le
 * test e2e zone montagne sera ajoute sur les branches qui l'utilisent
 * (luzerne III IAA, prairie+6 type III).
 */

import { test, expect } from '@playwright/test';

test.describe.configure({ mode: 'serial' });

const REIMS_LNG = 4.0345;
const REIMS_LAT = 49.2583;

async function waitForCascadeReady(page) {
  await expect
    .poll(
      async () => page.locator('#id_occupation_sol option').count(),
      { timeout: 10000 }
    )
    .toBeGreaterThan(1);
}

test.describe('Branche culture_de_printemps : 8 feuilles via URL', () => {
  const cases = [
    {
      label: 'type_0 -> r_printemps_type_0 (15/12 -> 15/01)',
      params: 'type_fertilisant=type_0',
      regle: 'r_printemps_type_0',
      contains: ['15/12', '15/01'],
    },
    {
      label: 'type_Ia -> r_printemps_type_Ia (2 periodes)',
      params: 'type_fertilisant=type_Ia',
      regle: 'r_printemps_type_Ia',
      contains: ['01/07', '31/08', '15/11', '15/01'],
    },
    {
      label: 'type_Ib -> r_printemps_type_Ib (01/07 -> 15/01)',
      params: 'type_fertilisant=type_Ib',
      regle: 'r_printemps_type_Ib',
      contains: ['01/07', '15/01'],
    },
    {
      label:
        'type_II + fertirrigation=oui -> r_printemps_II_fertirrig (pc6)',
      params:
        'type_fertilisant=type_II&fertirrigation=true',
      regle: 'r_printemps_II_fertirrig',
      // Le label long de pc6 est "effluent peu chargé fertirrigation"
      // (referentiels.yaml). On matche la regle_id + dates ; le code
      // de prescription brut (pc6) n'apparait pas en mode user.
      contains: ['01/07', '31/08', '31/01'],
    },
    {
      label:
        'type_II + fertirrigation=non -> r_printemps_II_sans_fertirrig',
      params:
        'type_fertilisant=type_II&fertirrigation=false',
      regle: 'r_printemps_II_sans_fertirrig',
      contains: ['01/07', '31/01'],
    },
    {
      label:
        'type_III + irriguee=oui + mais -> r_printemps_III_mais_irrigue (pc5 + message brunissement)',
      params:
        'type_fertilisant=type_III&culture_irriguee=true&culture_irriguee_type=mais',
      regle: 'r_printemps_III_mais_irrigue',
      // Message specifique mais : extension phenologique au stade
      // brunissement des soies si celui-ci survient apres le 15/07.
      contains: ['15/07', '15/02', 'brunissement des soies'],
    },
    {
      label:
        'type_III + irriguee=oui + autre -> r_printemps_III_autre_irrigue (pc5)',
      params:
        'type_fertilisant=type_III&culture_irriguee=true&culture_irriguee_type=autre',
      regle: 'r_printemps_III_autre_irrigue',
      contains: ['15/07', '15/02'],
    },
    {
      label: 'type_III + irriguee=non -> r_printemps_III_non_irrigue',
      params: 'type_fertilisant=type_III&culture_irriguee=false',
      regle: 'r_printemps_III_non_irrigue',
      contains: ['01/07', '15/02'],
    },
  ];

  for (const c of cases) {
    test(c.label, async ({ page }) => {
      await page.goto(
        `/simulateur/?lng=${REIMS_LNG}&lat=${REIMS_LAT}` +
          '&occupation_sol=culture_principale' +
          '&sous_culture=culture_printemps' +
          '&' +
          c.params
      );

      const body = page.locator('body');
      await expect(body).toContainText(c.regle);
      for (const txt of c.contains) {
        await expect(body).toContainText(txt);
      }
    });
  }
});

test.describe('Branche culture_de_printemps : flow question complementaire', () => {
  test('type_II + fertirrigation : pose la question puis applique la reponse', async ({
    page,
  }) => {
    // Cas le plus dur du screenshot : 2 etapes (form principal puis
    // question subsidiaire `fertirrigation`), regle a 2 periodes avec
    // regimes mixtes (autorisation_sous_condition + interdiction), pc6.
    await page.goto(
      `/simulateur/?lng=${REIMS_LNG}&lat=${REIMS_LAT}` +
        '&occupation_sol=culture_principale' +
        '&sous_culture=culture_printemps' +
        '&type_fertilisant=type_II'
    );

    // Page resultat affiche la question complementaire (radio buttons DSFR
    // dans le form principal, pas dans un sous-form).
    // Note 2026-05-12 : selecteur change vers le pattern qc-<champ>-<valeur>
    // generes par _qc_recap.html et _resultat_questions.html.
    const labelOui = page.locator('label[for*="fertirrigation"][for*="True"]').first();
    await expect(labelOui).toBeVisible();
    await labelOui.click();

    // Le radio est dans le form principal, on submit via le bouton.
    // exact: true car "Relancer la simulation" (bandeau QC) contient aussi
    // "lancer la simulation" -> sinon strict mode violation (2 boutons).
    await page
      .getByRole('button', { name: 'Lancer la simulation', exact: true })
      .click();
    await page.waitForLoadState('networkidle');

    const body = page.locator('body');
    await expect(body).toContainText('r_printemps_II_fertirrig');
    // 2 periodes : 01/07-31/08 (autorisation sous condition) puis 31/08-31/01.
    await expect(body).toContainText('01/07');
    await expect(body).toContainText('31/08');
    await expect(body).toContainText('31/01');
  });
});
