/**
 * Couverture e2e de la branche `culture_principale` / `colza`.
 *
 * 6 tests via URL pre-remplie + 1 cas le plus dur :
 *   - type_III + zone note 5 (Toulouse, Occitanie) : 2 periodes avec
 *     regimes mixtes (autorisation_sous_condition + interdiction)
 *     + pc11. Resolution code_insee -> zone_note_5 cote backend.
 */

import { test, expect } from '@playwright/test';

test.describe.configure({ mode: 'serial' });

const REIMS_LNG = 4.0345;
const REIMS_LAT = 49.2583;

const INSEE_TOULOUSE_31 = '31555'; // zone note 5 (Occitanie)
const INSEE_BORDEAUX_33 = '33063'; // zone note 5 (Gironde)
const INSEE_REIMS_51 = '51454'; // hors note 5 (Marne)


test.describe('Branche colza : 6 feuilles + fallback type_Ia via URL', () => {
  const cases = [
    {
      label: 'type_0 -> r_colza_type_0 (15/12 -> 15/01)',
      params: 'type_fertilisant=type_0',
      regle: 'r_colza_type_0',
      contains: ['15/12', '15/01'],
    },
    {
      label: 'type_I -> r_colza_type_I (15/11 -> 15/01)',
      params: 'type_fertilisant=type_I',
      regle: 'r_colza_type_I',
      contains: ['15/11', '15/01'],
    },
    {
      label:
        'type_Ia (fallback type_I) -> r_colza_type_I (mapping front -> type_I)',
      params: 'type_fertilisant=type_Ia',
      regle: 'r_colza_type_I',
      contains: ['15/11', '15/01'],
    },
    {
      label:
        'type_II + Toulouse (note 5) -> r_colza_type_II_note5 (15/10 -> 15/01)',
      params: `type_fertilisant=type_II&code_insee=${INSEE_TOULOUSE_31}`,
      regle: 'r_colza_type_II_note5',
      contains: ['15/10', '15/01'],
    },
    {
      label:
        'type_II + Reims (hors note 5) -> r_colza_type_II_autres (15/10 -> 31/01)',
      params: `type_fertilisant=type_II&code_insee=${INSEE_REIMS_51}`,
      regle: 'r_colza_type_II_autres',
      contains: ['15/10', '31/01'],
    },
    {
      label:
        'type_III + Bordeaux (note 5) -> r_colza_type_III_note5 (2 periodes regimes mixtes, pc11)',
      params: `type_fertilisant=type_III&code_insee=${INSEE_BORDEAUX_33}`,
      regle: 'r_colza_type_III_note5',
      contains: ['01/09', '15/10', '15/01'],
    },
    {
      label:
        'type_III + Reims (hors note 5) -> r_colza_type_III_autres (2 periodes regimes mixtes, pc11)',
      params: `type_fertilisant=type_III&code_insee=${INSEE_REIMS_51}`,
      regle: 'r_colza_type_III_autres',
      contains: ['01/09', '15/10', '31/01'],
    },
  ];

  for (const c of cases) {
    test(c.label, async ({ page }) => {
      await page.goto(
        `/simulateur/?lng=${REIMS_LNG}&lat=${REIMS_LAT}` +
          '&occupation_sol=culture_principale' +
          '&sous_culture=colza' +
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
