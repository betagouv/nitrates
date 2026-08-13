import { test, expect } from '@playwright/test';

/**
 * #135 — reset/flush du formulaire au changement d'un champ APRES resultat.
 *
 * Cas A (seul scope de ce dev) : un resultat (ou une QC) est affiche, l'user
 * change un champ DANS le formulaire -> le resultat/QC disparait, l'URL est
 * nettoyee (dictionnaire de cles uniques, pas de doublon, pas de valeur
 * derivee obsolete), et la cascade reprend la main au bon endroit. La
 * resoumission ne repose PAS de fausse QC (« type de fertilisant ? »).
 *
 * Le cas B (re-clic carte / scope SIG) est HORS scope (dev separe).
 */

test.describe.configure({ mode: 'serial' });

const REIMS_LNG = 4.0345;
const REIMS_LAT = 49.2583;

// URL d'un resultat complet colza + engrais mineral type_III (pas de QC).
const RESULTAT_COLZA_URL =
  `/simulateur/?lng=${REIMS_LNG}&lat=${REIMS_LAT}` +
  '&categorie_culture=culture_hiver&sous_culture_form=colza' +
  '&occupation_sol=culture_principale&sous_culture=colza' +
  '&categorie_fertilisant=engrais_mineral' +
  '&sous_fertilisant=engrais_azote_mineral&type_fertilisant=type_III';

function dupKeys(search: string): string[] {
  const p = new URLSearchParams(search);
  const seen = new Set<string>();
  const dups: string[] = [];
  for (const k of p.keys()) {
    if (seen.has(k)) dups.push(k);
    seen.add(k);
  }
  return dups;
}

test.describe('Simulateur #135 : reset au changement de champ apres resultat', () => {
  test('changer la categorie de fertilisant retire le resultat et nettoie l URL', async ({
    page,
  }) => {
    await page.goto(RESULTAT_COLZA_URL);

    // Etat initial : resultat affiche, layout en 2 colonnes.
    await expect(page.locator('.result-col')).toBeVisible();
    await expect(page.locator('.results-row.layout--split')).toHaveCount(1);
    // #160 : sur un resultat inchange, PAS de bouton « Lancer la simulation »
    // (rien a relancer).
    await expect(page.locator('#form-submit-row')).toBeHidden();

    // L'user change la categorie de fertilisant (composts).
    await page.locator('label[for="id_categorie_fertilisant__composts"]').click();

    // Le resultat disparait, retour colonne unique.
    await expect(page.locator('.result-col')).toHaveCount(0);
    await expect(page.locator('.results-row.layout--split')).toHaveCount(0);
    // Le bouton REAPPARAIT : l'utilisateur a modifie un champ, il peut relancer.
    await expect(page.locator('#form-submit-row')).toBeVisible();
    await expect(
      page.locator('#form-submit-row button[type="submit"]')
    ).toHaveText(/Lancer la simulation/);

    // type_fertilisant obsolete (type_III) est reset par la cascade : il ne
    // doit plus etre dans l'URL miroir (c'etait une cause des bugs precedents).
    await expect
      .poll(() =>
        page.evaluate(() =>
          new URLSearchParams(location.search).get('type_fertilisant')
        )
      )
      .toBeNull();
    // sous_fertilisant obsolete retire aussi (categorie changee).
    await expect
      .poll(() =>
        page.evaluate(() =>
          new URLSearchParams(location.search).get('sous_fertilisant')
        )
      )
      .toBeNull();
    // La nouvelle categorie est bien dans l'URL.
    await expect
      .poll(() =>
        page.evaluate(() =>
          new URLSearchParams(location.search).get('categorie_fertilisant')
        )
      )
      .toBe('composts');

    // Invariant cle : aucune cle dupliquee dans l'URL.
    const search = await page.evaluate(() => location.search);
    expect(dupKeys(search)).toEqual([]);
  });

  test('reprise de la cascade -> resoumission SANS fausse QC type fertilisant', async ({
    page,
  }) => {
    await page.goto(RESULTAT_COLZA_URL);
    await expect(page.locator('.result-col')).toBeVisible();

    // Change categorie -> sous_fertilisant -> nouveau type resolu par cascade.
    await page.locator('label[for="id_categorie_fertilisant__composts"]').click();
    await expect(page.locator('.result-col')).toHaveCount(0);

    await page
      .locator('label[for="id_sous_fertilisant__compost_fientes_volailles"]')
      .click();
    // cascade.js a resolu type_fertilisant (compost fientes volailles -> type_II).
    await expect(page.locator('#id_type_fertilisant')).toHaveValue('type_II');

    // Relance : on doit obtenir le NOUVEAU resultat, pas une fausse QC.
    await page.locator('#form-simulateur button[type="submit"]').click();
    await page.waitForLoadState('networkidle');

    const body = page.locator('body');
    await expect(body).toContainText('r_colza_type_II');
    // Pas de bloc QC en attente reaffiche (la fausse question des bugs passes).
    await expect(page.locator('#qc-bloc[data-qc-en-attente]')).toHaveCount(0);
  });

  test('editer une QC repondue (via Modifier) garde le volet QC, sans resubmit (#213)', async ({
    page,
  }) => {
    // culture_printemps + type_II pose la QC fertirrigation ; on la repond via
    // l'URL pour obtenir un resultat AVEC QC recap editable.
    // NB #213 : l'ancien comportement (raser resultat + bloc QC au clic) est
    // remplace -- le volet QC RESTE a l'ecran, rien n'est soumis, et c'est le
    // « Lancer » suivant qui tranche. Depuis #271, l'edition passe par le
    // bouton « Modifier » de l'encart recap (le form est masque sur la page
    // resultat).
    await page.goto(
      `/simulateur/?lng=${REIMS_LNG}&lat=${REIMS_LAT}` +
        '&occupation_sol=culture_principale&sous_culture=culture_printemps' +
        '&type_fertilisant=type_II&fertirrigation=False'
    );

    // Un resultat + le bloc QC (recap) sont presents.
    await expect(page.locator('#qc-bloc')).toHaveCount(1);
    await page.locator('[data-recap-modifier]').first().click();
    await expect(page.locator('#qc-bloc')).toBeVisible();

    // Marqueur anti-reload : le flip d'une QC ne doit RIEN soumettre.
    await page.evaluate(() => {
      (window as any).__pas_de_reload = true;
    });
    await page.locator('label[for*="fertirrigation"][for*="True"]').first().click();
    await page.waitForTimeout(600);

    // Pas de resubmit, le volet QC reste, la nouvelle reponse est cochee.
    expect(
      await page.evaluate(() => (window as any).__pas_de_reload === true)
    ).toBe(true);
    await expect(page.locator('#qc-bloc')).toBeVisible();
    await expect(
      page.locator('input[name="fertirrigation"][value="True"]:visible')
    ).toBeChecked();
    // Le resultat, lui, a ete retire par « Modifier » (retour en saisie).
    await expect(page.locator('.result-col')).toHaveCount(0);
  });
});

/**
 * #135 — REGRESSION boucle infinie (rapportee par Max le 2026-06-26).
 *
 * Scenario exact : apres avoir navigue dans le form, l'utilisateur arrive sur
 * une page qui pose une QC EN ATTENTE (data-qc-en-attente). Il clique le radio
 * de la QC pour y repondre -> AVANT le fix, reset_form elaguait le bloc QC sous
 * ses doigts. Il relance -> le serveur repose la meme QC -> il reclique -> elle
 * redisparait. Boucle infinie, impossible de finaliser.
 *
 * Le fix : ne JAMAIS elaguer quand l'utilisateur clique un radio DANS le bloc
 * QC en attente. On verifie ici que (a) la QC reste a l'ecran apres clic, et
 * (b) on peut effectivement finaliser jusqu'au resultat.
 */
test.describe('Simulateur #135 : pas de boucle infinie sur QC en attente', () => {
  // Le parcours exact du bug : digestats + fraction liquide + mais irrigue ->
  // pose la QC fertirrigation en attente.
  const URL_QC_EN_ATTENTE =
    `/simulateur/?lng=${REIMS_LNG}&lat=${REIMS_LAT}` +
    '&categorie_culture=culture_printemps&sous_culture_form=mais' +
    '&categorie_fertilisant=digestats' +
    '&sous_fertilisant=fraction_liquide_digestat_methanisation' +
    '&occupation_sol=culture_principale&sous_culture=culture_printemps' +
    '&culture_irriguee_type=mais&type_fertilisant=type_II';

  test('repondre a la QC en attente ne la fait PAS disparaitre', async ({
    page,
  }) => {
    await page.goto(URL_QC_EN_ATTENTE);

    // La QC fertirrigation est posee, en attente.
    await expect(page.locator('#qc-bloc[data-qc-en-attente]')).toHaveCount(1);
    await expect(
      page.locator('[data-qc-champ="fertirrigation"]')
    ).toBeVisible();

    // L'utilisateur repond a la QC.
    await page.locator('label[for*="fertirrigation"][for*="True"]').first().click();

    // La QC NE DOIT PAS disparaitre (c'etait le bug). On laisse passer le tick
    // setTimeout(0) de reset_form pour etre sur qu'il n'elague pas.
    await page.waitForTimeout(150);
    await expect(page.locator('#qc-bloc')).toHaveCount(1);
    await expect(
      page.locator('[data-qc-champ="fertirrigation"]')
    ).toBeVisible();
    // Le radio reste coche.
    await expect(
      page.locator('input[name="fertirrigation"][value="True"]')
    ).toBeChecked();
  });

  test('on peut FINALISER la QC en attente jusqu au resultat', async ({
    page,
  }) => {
    await page.goto(URL_QC_EN_ATTENTE);
    await expect(page.locator('#qc-bloc[data-qc-en-attente]')).toHaveCount(1);

    // Repond la QC.
    await page.locator('label[for*="fertirrigation"][for*="True"]').first().click();
    await page.waitForTimeout(150);
    await expect(page.locator('#qc-bloc')).toHaveCount(1);

    // Relance : doit aboutir a un resultat, pas reboucler sur la meme QC.
    await page
      .locator('#form-simulateur button[type="submit"]').click();
    await page.waitForLoadState('networkidle');

    // On a un resultat (r_printemps_*), et plus de QC EN ATTENTE.
    await expect(page.locator('body')).toContainText(/r_printemps/);
    await expect(page.locator('#qc-bloc[data-qc-en-attente]')).toHaveCount(0);
    await expect(page.locator('.result-col')).toHaveCount(1);
  });

  test('changer un champ AMONT pendant une QC en attente : URL elaguee, volet QC conserve (#213)', async ({
    page,
  }) => {
    // Si l'utilisateur change la CATEGORIE (champ amont) alors qu'une QC est
    // en attente, l'URL est elaguee de l'aval (le parcours change) MAIS le
    // volet QC n'est PAS rase cote client (#213, anti-clignotement) : le
    // rendu serveur suivant tranche -- si la nouvelle branche pose la meme
    // QC, l'utilisateur ne voit aucune coupure.
    await page.goto(URL_QC_EN_ATTENTE);
    await expect(page.locator('#qc-bloc[data-qc-en-attente]')).toHaveCount(1);

    // Change la categorie de fertilisant (amont de la QC).
    await page.locator('label[for="id_categorie_fertilisant__composts"]').click();
    await page.waitForTimeout(300);

    // Le volet QC reste a l'ecran (pas de clignotement).
    await expect(page.locator('#qc-bloc')).toHaveCount(1);
    // sous_fertilisant reset par la cascade -> retire de l'URL (l'elagage
    // MIROIR de l'URL, lui, reste inchange).
    await expect
      .poll(() =>
        page.evaluate(() =>
          new URLSearchParams(location.search).get('sous_fertilisant')
        )
      )
      .toBeNull();
  });
});

/**
 * #135 — parcours QC COMPLET de bout en bout, sans pre-remplir l'URL : on
 * clique reellement chaque etape (carte -> cascade -> submit -> QC -> submit).
 * C'est le test "dans tous les sens" qui aurait du attraper la boucle.
 */
test.describe('Simulateur #135 : parcours QC complet par clics reels', () => {
  test('mais irrigue + digestats : cascade -> QC -> finalisation', async ({
    page,
  }) => {
    await page.goto(`/simulateur/?lng=${REIMS_LNG}&lat=${REIMS_LAT}`);

    // Attendre le flow #272 pret (Q1 destination rendue).
    await expect
      .poll(
        async () =>
          page.locator('#q_destination_epandage input[type="radio"]').count(),
        { timeout: 10000 }
      )
      .toBeGreaterThan(0);

    // Flow #272 : Q1 culture principale (index 2) -> Q2 culture printemps ->
    // Q3 precision mais.
    const clickFlow = async (name: string, index: number) => {
      const g = page.locator(`input[type=radio][name="${name}"]`);
      const id = await g.nth(index).getAttribute('id');
      await page.locator(`label[for="${id}"]`).click();
      await page.waitForTimeout(250);
    };
    await clickFlow('cflow_destination', 2); // culture principale
    await clickFlow('cflow_type_couvert', 1); // culture de printemps
    await clickFlow('cflow_sous_culture', 0); // mais
    // Cascade fertilisant : digestats -> fraction liquide.
    await page.locator('label[for="id_categorie_fertilisant__digestats"]').click();
    await page
      .locator(
        'label[for="id_sous_fertilisant__fraction_liquide_digestat_methanisation"]'
      )
      .click();

    // Lancer -> le serveur pose la QC fertirrigation.
    await page
      .locator('#form-simulateur button[type="submit"]').click();
    await page.waitForLoadState('networkidle');
    await expect(page.locator('#qc-bloc[data-qc-en-attente]')).toHaveCount(1);

    // Repondre la QC : elle ne doit PAS disparaitre.
    await page.locator('label[for*="fertirrigation"][for*="True"]').first().click();
    await page.waitForTimeout(150);
    await expect(page.locator('#qc-bloc')).toHaveCount(1);

    // Relancer -> resultat final.
    await page
      .locator('#form-simulateur button[type="submit"]').click();
    await page.waitForLoadState('networkidle');
    await expect(page.locator('body')).toContainText(/r_printemps/);
    await expect(page.locator('#qc-bloc[data-qc-en-attente]')).toHaveCount(0);
  });
});

/**
 * #135 + #272 — cas couvert flow : la saisie du couvert passe par les questions
 * successives Q1..Q4 (question_couvert_flow.js), qui cochent le vrai radio
 * categorie_culture / sous_culture_form et dispatchent leur change. On verifie
 * que ce change synthetique declenche bien l'elagage du resultat sans casser
 * (les radios cflow_* ne sont PAS des champs cascade/derives, mais le
 * sous_culture_form qu'ils pilotent l'est).
 */
test.describe('Simulateur #135 : reset sur saisie couvert (flow #272)', () => {
  const URL_RESULTAT_COUVERT =
    `/simulateur/?lng=${REIMS_LNG}&lat=${REIMS_LAT}` +
    '&categorie_culture=couvert_intercultures_longue' +
    '&sous_culture_form=couvert_non_recolte_toujours_en_place_apres_0101' +
    '&occupation_sol=couvert_intercultures&sous_culture=cine_apres_0101' +
    '&date_semis_couvert=15/08&date_destruction_couvert=15/02' +
    '&categorie_fertilisant=engrais_mineral' +
    '&sous_fertilisant=engrais_azote_mineral&type_fertilisant=type_III';

  test('changer la question recolte apres resultat elague le resultat', async ({
    page,
  }) => {
    await page.goto(URL_RESULTAT_COUVERT);
    await expect(page.locator('.result-col')).toBeVisible();

    // Le flow #272 est reconstruit depuis l'URL (Q1..Q3 cochees). On change
    // l'axe "recolte" (Q3) -> pilote le vrai sous_culture_form -> dispatch
    // change -> reset_form doit elaguer.
    const recolteRadio = page.locator(
      'input[name="cflow_couvert_recolte"][value="recolte"]'
    );
    const id = await recolteRadio.getAttribute('id');
    await page.locator(`label[for="${id}"]`).click();
    await page.waitForTimeout(200);

    // L'invariant robuste : aucune cle d'URL dupliquee apres l'operation.
    const search = await page.evaluate(() => location.search);
    expect(dupKeys(search)).toEqual([]);
  });
});
