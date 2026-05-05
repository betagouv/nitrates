/**
 * Couverture e2e de la branche `culture_principale` /
 * `culture_hiver_hors_colza`.
 *
 * 6 feuilles + fallback type_Ia, validees via URL pre-remplie. La
 * branche traverse le noeud catalogue zone_note_5 (Sud-Ouest) sur
 * type_II/III, resolu par code_insee cote backend (cf. zonage_note_5.py).
 */

import { test, expect } from '@playwright/test';

test.describe.configure({ mode: 'serial' });

const REIMS_LNG = 4.0345;
const REIMS_LAT = 49.2583;

const INSEE_TOULOUSE_31 = '31555';
const INSEE_BORDEAUX_33 = '33063';
const INSEE_REIMS_51 = '51454';

test.describe('Branche culture_hiver_hors_colza : 6 feuilles + fallback Ia via URL', () => {
  const cases = [
    {
      label: 'type_0 -> r_hiver_hors_colza_type_0 (15/12 -> 15/01)',
      params: 'type_fertilisant=type_0',
      regle: 'r_hiver_hors_colza_type_0',
      contains: ['15/12', '15/01'],
    },
    {
      label: 'type_I -> r_hiver_hors_colza_type_I (15/11 -> 15/01)',
      params: 'type_fertilisant=type_I',
      regle: 'r_hiver_hors_colza_type_I',
      contains: ['15/11', '15/01'],
    },
    {
      label:
        'type_Ia (fallback) -> r_hiver_hors_colza_type_I (mapping front -> type_I)',
      params: 'type_fertilisant=type_Ia',
      regle: 'r_hiver_hors_colza_type_I',
      contains: ['15/11', '15/01'],
    },
    {
      label:
        'type_II + Toulouse (note 5) -> r_hiver_hors_colza_type_II_note5 (01/10 -> 15/01)',
      params: `type_fertilisant=type_II&code_insee=${INSEE_TOULOUSE_31}`,
      regle: 'r_hiver_hors_colza_type_II_note5',
      contains: ['01/10', '15/01'],
    },
    {
      label:
        'type_II + Reims (hors note 5) -> r_hiver_hors_colza_type_II_autres (01/10 -> 31/01)',
      params: `type_fertilisant=type_II&code_insee=${INSEE_REIMS_51}`,
      regle: 'r_hiver_hors_colza_type_II_autres',
      contains: ['01/10', '31/01'],
    },
    {
      label:
        'type_III + Bordeaux (note 5) -> r_hiver_hors_colza_type_III_note5 (01/09 -> 15/01)',
      params: `type_fertilisant=type_III&code_insee=${INSEE_BORDEAUX_33}`,
      regle: 'r_hiver_hors_colza_type_III_note5',
      contains: ['01/09', '15/01'],
    },
    {
      label:
        'type_III + Reims (hors note 5) -> r_hiver_hors_colza_type_III_autres (01/09 -> 31/01)',
      params: `type_fertilisant=type_III&code_insee=${INSEE_REIMS_51}`,
      regle: 'r_hiver_hors_colza_type_III_autres',
      contains: ['01/09', '31/01'],
    },
  ];

  for (const c of cases) {
    test(c.label, async ({ page }) => {
      await page.goto(
        `/simulateur/?lng=${REIMS_LNG}&lat=${REIMS_LAT}` +
          '&occupation_sol=culture_principale' +
          '&sous_culture=culture_hiver_hors_colza' +
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
