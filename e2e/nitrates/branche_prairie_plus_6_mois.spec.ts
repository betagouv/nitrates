/**
 * Couverture e2e de la branche `culture_principale` /
 * `prairie_plus_6_mois`.
 *
 * Strategie :
 *   - 8 tests via URL pre-remplie (rapide).
 *   - 1 test du cas le plus dur : type_III + zone montagne note_7
 *     (Accous, Pyrenees-Atlantiques 64) qui valide la resolution
 *     code_insee -> zonage_montagne (variante pyrenees_atl) cote
 *     backend, et le rendu de la regle correspondante.
 */

import { test, expect } from '@playwright/test';

test.describe.configure({ mode: 'serial' });

const REIMS_LNG = 4.0345;
const REIMS_LAT = 49.2583;

// Pour les cas zone montagne, on reste sur Reims pour le clic carte
// (la map ZV ne couvre pas forcement Pau ; Reims est en ZV pour
// activer le critere). Le code_insee est passe en query param,
// independant du clic carte. C'est legal cote app : le front pousse
// `code_insee` independamment de lat/lng.
const INSEE_ACCOUS_64 = '64006'; // montagne Pyrenees-Atlantiques -> note_7
const INSEE_AIGUEBELETTE_73 = '73001'; // montagne Savoie -> note_6
const INSEE_REIMS_51 = '51454'; // non montagne


test.describe('Branche prairie_plus_6_mois : 8 feuilles via URL', () => {
  const cases = [
    {
      label: 'type_0 + plan_epandage=icpe_a -> r_prairie_plus_6_type_0_icpe_a',
      params: 'type_fertilisant=type_0&plan_epandage=icpe_a',
      regle: 'r_prairie_plus_6_type_0_icpe_a',
      contains: ['15/12', '15/01'],
    },
    {
      label: 'type_0 + plan_epandage=autre -> r_prairie_plus_6_type_0',
      params: 'type_fertilisant=type_0&plan_epandage=autre',
      regle: 'r_prairie_plus_6_type_0',
      contains: ['15/12', '15/01'],
    },
    {
      label: 'type_I -> r_prairie_plus_6_type_I',
      params: 'type_fertilisant=type_I',
      regle: 'r_prairie_plus_6_type_I',
      contains: ['15/12', '15/01'],
    },
    {
      // #98 : la branche "peu chargé" se joue désormais sur sous_fertilisant
      // (effluents_peu_charges_elevage/non_elevage), plus sur effluent_peu_charge.
      label:
        'type_II + effluents peu chargés -> r_prairie_plus_6_type_II_peu_charge',
      params:
        'type_fertilisant=type_II&sous_fertilisant=effluents_peu_charges_elevage',
      regle: 'r_prairie_plus_6_type_II_peu_charge',
      contains: ['15/11', '15/01'],
    },
    {
      label: 'type_II + effluent_peu_charge=non -> r_prairie_plus_6_type_II',
      params: 'type_fertilisant=type_II&effluent_peu_charge=false',
      regle: 'r_prairie_plus_6_type_II',
      contains: ['15/11', '15/01'],
    },
    {
      label:
        'type_III + commune Pyrenees-Atl (note_7) -> r_prairie_plus_6_type_III_montagne_note7',
      params: `type_fertilisant=type_III&code_insee=${INSEE_ACCOUS_64}`,
      regle: 'r_prairie_plus_6_type_III_montagne_note7',
      contains: ['01/10', '15/02'],
    },
    {
      label:
        'type_III + commune Savoie (note_6) -> r_prairie_plus_6_type_III_montagne_note6',
      params: `type_fertilisant=type_III&code_insee=${INSEE_AIGUEBELETTE_73}`,
      regle: 'r_prairie_plus_6_type_III_montagne_note6',
      contains: ['01/10', '28/02'],
    },
    {
      label:
        'type_III + commune Reims (non montagne) -> r_prairie_plus_6_type_III',
      params: `type_fertilisant=type_III&code_insee=${INSEE_REIMS_51}`,
      regle: 'r_prairie_plus_6_type_III',
      contains: ['01/10', '31/01'],
    },
  ];

  for (const c of cases) {
    test(c.label, async ({ page }) => {
      await page.goto(
        `/simulateur/?lng=${REIMS_LNG}&lat=${REIMS_LAT}` +
          '&occupation_sol=culture_principale' +
          '&sous_culture=prairie_plus_6_mois' +
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
