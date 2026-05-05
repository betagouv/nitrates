/**
 * Couverture e2e de la branche `culture_principale` / `autres_cultures`.
 *
 * 1 seule feuille : interdit 15/12 -> 15/01 quel que soit le
 * fertilisant. La regle est posee directement sur la branche YAML
 * (pas de noeud type_fertilisant intermediaire) -- l'utilisateur
 * saute la question fertilisant dans le flow UI.
 *
 * On valide :
 *   - sans type_fertilisant
 *   - avec type_fertilisant explicite (different types) : meme regle
 */

import { test, expect } from '@playwright/test';

test.describe.configure({ mode: 'serial' });

const REIMS_LNG = 4.0345;
const REIMS_LAT = 49.2583;

test.describe('Branche autres_cultures : 1 feuille tous types', () => {
  const cases = [
    {
      label: 'sans type_fertilisant -> r_autres_cultures_tous_types',
      params: '',
    },
    {
      label: 'type_0 -> r_autres_cultures_tous_types',
      params: 'type_fertilisant=type_0',
    },
    {
      label: 'type_II -> r_autres_cultures_tous_types',
      params: 'type_fertilisant=type_II',
    },
    {
      label: 'type_III -> r_autres_cultures_tous_types',
      params: 'type_fertilisant=type_III',
    },
  ];

  for (const c of cases) {
    test(c.label, async ({ page }) => {
      await page.goto(
        `/simulateur/?lng=${REIMS_LNG}&lat=${REIMS_LAT}` +
          '&occupation_sol=culture_principale' +
          '&sous_culture=autres_cultures' +
          (c.params ? `&${c.params}` : '')
      );

      const body = page.locator('body');
      await expect(body).toContainText('r_autres_cultures_tous_types');
      // Periode unique : 15/12 -> 15/01.
      await expect(body).toContainText('15/12');
      await expect(body).toContainText('15/01');
    });
  }
});
