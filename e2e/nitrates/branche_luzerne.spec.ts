/**
 * Couverture e2e de la branche `culture_principale` / `luzerne`.
 *
 * Branche la plus complexe : 12 cas, 7 feuilles directes + 5
 * renvoi_vers, 3 niveaux de questions et 2 catalogues SIG imbriques
 * sur Type III IAA (zone_montagne_d113_14 + zone_note_7_vs_note_6).
 *
 * Validation via URL pre-remplie. Cas le plus dur : type_III + IAA +
 * montagne note_7 (Accous 64) qui traverse :
 *   - q_luzerne_fertilisant -> type_III
 *   - q_luzerne_III_icpe -> icpe_a
 *   - q_luzerne_III_icpe_a_iaa -> true
 *   - n_luzerne_III_iaa_montagne_d113_14 (catalogue SIG bool)
 *   - n_luzerne_III_iaa_montagne_zonage (catalogue SIG note_7/note_6)
 *   - r_luzerne_III_iaa_montagne_note7
 */

import { test, expect } from '@playwright/test';

test.describe.configure({ mode: 'serial' });

const REIMS_LNG = 4.0345;
const REIMS_LAT = 49.2583;

const INSEE_ACCOUS_64 = '64006'; // PA, montagne -> note_7 elargie
const INSEE_AIGUEBELETTE_73 = '73001'; // Savoie, montagne -> note_6
const INSEE_REIMS_51 = '51454'; // hors montagne


test.describe('Branche luzerne : 12 cas via URL', () => {
  const cases = [
    {
      // Note 2026-05-12 : la luzerne type_0 renvoie maintenant vers le NOEUD
      // q_prairie_plus6_type_0_icpe (au lieu de la regle directe), donc une
      // QC `plan_epandage` est requise.
      label: 'type_0 + plan_epandage=autre -> r_prairie_plus_6_type_0 (15/12 -> 15/01)',
      params: 'type_fertilisant=type_0&plan_epandage=autre',
      regle: 'r_prairie_plus_6_type_0',
      contains: ['15/12', '15/01'],
    },
    {
      label:
        'type_I + ICPE A + IAA -> r_luzerne_I_icpe_a_iaa (calculatrice)',
      params: 'type_fertilisant=type_I&plan_epandage=icpe_a&fertilisant_iaa=true',
      regle: 'r_luzerne_I_icpe_a_iaa',
      // Regle calculatrice : la periode est dans parametres.periode_reglementaire
      // (pas dans periodes), et le template MVP ne rend pas encore les dates
      // pour les calculatrices. On valide uniquement la regle_id ; le test
      // unit Django garantit le contenu detaille (cf. test_branche_luzerne.py).
      contains: [],
    },
    {
      label: 'type_I + ICPE A + non IAA -> r_luzerne_I_icpe_a_sans_iaa',
      params:
        'type_fertilisant=type_I&plan_epandage=icpe_a&fertilisant_iaa=false',
      regle: 'r_luzerne_I_icpe_a_sans_iaa',
      contains: ['15/12', '15/01'],
    },
    {
      label: 'type_I + autre -> r_luzerne_I_autre',
      params: 'type_fertilisant=type_I&plan_epandage=autre',
      regle: 'r_luzerne_I_autre',
      contains: ['15/12', '15/01'],
    },
    {
      label:
        'type_II + ICPE A + IAA -> r_luzerne_II_icpe_a_iaa (calculatrice)',
      params:
        'type_fertilisant=type_II&plan_epandage=icpe_a&fertilisant_iaa=true',
      regle: 'r_luzerne_II_icpe_a_iaa',
      // Calculatrice : pas d'assertion sur les dates (cf. ci-dessus).
      contains: [],
    },
    {
      // Note 2026-05-12 : non IAA renvoie maintenant vers q_prairie_plus6_II_effluent
      // qui pose une QC `effluent_peu_charge` -> requise dans l'URL.
      label:
        'type_II + ICPE A + non IAA + effluent_peu_charge=false -> r_prairie_plus_6_type_II',
      params:
        'type_fertilisant=type_II&plan_epandage=icpe_a&fertilisant_iaa=false&effluent_peu_charge=false',
      regle: 'r_prairie_plus_6_type_II',
      contains: ['15/11', '15/01'],
    },
    {
      label: 'type_II + autre + effluent_peu_charge=false -> r_prairie_plus_6_type_II',
      params: 'type_fertilisant=type_II&plan_epandage=autre&effluent_peu_charge=false',
      regle: 'r_prairie_plus_6_type_II',
      contains: ['15/11', '15/01'],
    },
    {
      label:
        'type_III + ICPE A + IAA + Accous (montagne note 7) -> r_luzerne_III_iaa_montagne_note7',
      params: `type_fertilisant=type_III&plan_epandage=icpe_a&fertilisant_iaa=true&code_insee=${INSEE_ACCOUS_64}`,
      regle: 'r_luzerne_III_iaa_montagne_note7',
      // Calculatrice : pas d'assertion sur les dates.
      contains: [],
    },
    {
      label:
        'type_III + ICPE A + IAA + Aiguebelette (montagne note 6) -> r_luzerne_III_iaa_montagne_note6',
      params: `type_fertilisant=type_III&plan_epandage=icpe_a&fertilisant_iaa=true&code_insee=${INSEE_AIGUEBELETTE_73}`,
      regle: 'r_luzerne_III_iaa_montagne_note6',
      contains: [],
    },
    {
      label:
        'type_III + ICPE A + IAA + Reims (hors montagne) -> r_luzerne_III_iaa_non_montagne',
      params: `type_fertilisant=type_III&plan_epandage=icpe_a&fertilisant_iaa=true&code_insee=${INSEE_REIMS_51}`,
      regle: 'r_luzerne_III_iaa_non_montagne',
      contains: [],
    },
    {
      label:
        'type_III + ICPE A + non IAA -> renvoi r_prairie_plus_6_type_III',
      params: `type_fertilisant=type_III&plan_epandage=icpe_a&fertilisant_iaa=false&code_insee=${INSEE_REIMS_51}`,
      regle: 'r_prairie_plus_6_type_III',
      contains: ['01/10', '15/01'],
    },
    {
      label: 'type_III + autre -> renvoi r_prairie_plus_6_type_III',
      params: `type_fertilisant=type_III&plan_epandage=autre&code_insee=${INSEE_REIMS_51}`,
      regle: 'r_prairie_plus_6_type_III',
      contains: ['01/10', '15/01'],
    },
  ];

  for (const c of cases) {
    test(c.label, async ({ page }) => {
      await page.goto(
        `/simulateur/?lng=${REIMS_LNG}&lat=${REIMS_LAT}` +
          '&occupation_sol=culture_principale' +
          '&sous_culture=luzerne' +
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
