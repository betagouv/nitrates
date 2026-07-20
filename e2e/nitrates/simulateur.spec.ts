import { test, expect } from '@playwright/test';

// Le simulateur charge Leaflet + WMTS IGN + GeoJSON ZV ; les workers
// paralleles peuvent OOM-crash le conteneur node. On serialise par fichier.
test.describe.configure({ mode: 'serial' });

// Reims (Marne, Grand Est, ZV bassin Seine-Normandie)
const REIMS_LNG = 4.0345;
const REIMS_LAT = 49.2583;

// Quelque part en mer atlantique, hors France (et donc hors ZV)
const OFFSHORE_LNG = -30.0;
const OFFSHORE_LAT = 30.0;

/**
 * Attend que la cascade JS ait fini de fetch arbre+referentiels et rendu
 * les radios DSFR. On poll sur la presence d'un libelle attendu dans le
 * conteneur dedie a la 1re cascade (categorie_culture).
 */
async function waitForCascadeReady(page) {
  // Issues #89 + #96 (2026-05-25) : le form Culture est cache tant que
  // l'utilisateur n'a pas clique sur la carte. On simule un clic Reims
  // pour deverrouiller la zone du form avant de tester la cascade.
  // Idempotent : si lat/lng deja remplis (rechargement avec params),
  // la zone est deja visible et le clic supplementaire est sans effet.
  await page.evaluate(([lng, lat]) => {
    const w = window as any;
    if (w.nitratesMap && w.L) {
      w.nitratesMap.fire('click', { latlng: w.L.latLng(lat, lng) });
    }
  }, [REIMS_LNG, REIMS_LAT]);

  // Note 2026-05-12 : la cascade n'utilise plus des <select> mais des
  // radios DSFR dans des conteneurs [data-cascade]. On attend qu'au moins
  // un radio soit rendu dans le conteneur categorie_culture.
  await expect
    .poll(
      async () =>
        page.locator('[data-cascade="categorie_culture"] input[type="radio"]').count(),
      { timeout: 10000 }
    )
    .toBeGreaterThan(0);
}

/**
 * DSFR cache visuellement les inputs radio derriere leur label : un
 * locator.check() echoue car le label intercepte les clics. On cible
 * donc le label par son `for=id_<champ>__<slug(value)>`.
 *
 * NB : `slug` cote JS remplace non-alphanumeric par `_`. Pour les
 * valeurs utilisees ici (alphanum + underscore), c'est identique.
 */
async function clickCascadeRadio(page, name, value) {
  await page.locator(`label[for="id_${name}__${value}"]`).click();
}

test.describe('Simulateur nitrates : page formulaire', () => {
  test('charge la carte, le panneau debug et les radios cascade vides', async ({
    page,
  }) => {
    await page.goto('/simulateur/');

    await expect(page).toHaveTitle(/Simulateur/);
    // Note #160 : h1 mise a jour vers le texte Figma.
    await expect(page.locator('h1')).toContainText("conditions d'épandage");

    // Carte Leaflet presente
    const map = page.locator('#nitrates-map');
    await expect(map).toBeVisible();
    await expect(map).toHaveClass(/leaflet-container/);

    // Inputs lat/lng vides
    await expect(page.locator('#id_lat')).toHaveValue('');
    await expect(page.locator('#id_lng')).toHaveValue('');

    // Note 2026-05-12 : la cascade est rendue dynamiquement via radios
    // DSFR dans les conteneurs [data-cascade]. Les hidden inputs sont
    // remplis au fur et a mesure des clics.
    await expect(page.locator('#id_occupation_sol')).toHaveValue('');
    await expect(page.locator('#id_type_fertilisant')).toHaveValue('');

    // Attendre que la cascade soit prete et verifier que les libelles
    // attendus sont presents dans le 1er conteneur.
    await waitForCascadeReady(page);
    const cascadeText =
      (await page.locator('[data-cascade="categorie_culture"]').textContent()) || '';
    // Au moins une categorie d'apres referentiels.yaml doit etre visible.
    expect(cascadeText.toLowerCase()).toMatch(/sol non cultiv|culture/);
  });

  test('clic carte sur Reims pre-remplit lat/lng', async ({ page }) => {
    await page.goto('/simulateur/');
    await expect(page.locator('#nitrates-map')).toHaveClass(/leaflet-container/);

    await page.evaluate(([lng, lat]) => {
      const w = window as any;
      w.nitratesMap.fire('click', { latlng: w.L.latLng(lat, lng) });
    }, [REIMS_LNG, REIMS_LAT]);

    // lat/lng pre-remplis
    await expect(page.locator('#id_lat')).toHaveValue(/49\.258/);
    await expect(page.locator('#id_lng')).toHaveValue(/4\.034/);
  });

  test('form Culture cache tant que pas de clic carte (issues #89, #96)', async ({
    page,
  }) => {
    await page.goto('/simulateur/');
    await expect(page.locator('#nitrates-map')).toHaveClass(/leaflet-container/);

    // Etat initial : message d'invite visible, zone form cachee.
    await expect(page.locator('#form-locked-message')).toBeVisible();
    await expect(page.locator('#form-locked-message')).toContainText(
      'Cliquez sur la carte'
    );
    await expect(page.locator('#form-after-localisation')).toBeHidden();
    // Le bouton submit fait partie de la zone cachee.
    await expect(
      page.locator('button[type="submit"]', { hasText: 'Lancer la simulation' })
    ).toBeHidden();

    // Clic carte : devoile la zone form, masque le message d'invite.
    await page.evaluate(([lng, lat]) => {
      const w = window as any;
      w.nitratesMap.fire('click', { latlng: w.L.latLng(lat, lng) });
    }, [REIMS_LNG, REIMS_LAT]);

    await expect(page.locator('#form-after-localisation')).toBeVisible();
    await expect(page.locator('#form-locked-message')).toBeHidden();
    await expect(
      page.locator('button[type="submit"]', { hasText: 'Lancer la simulation' })
    ).toBeVisible();
  });

  test('form Culture visible direct si lat/lng dans URL (issues #89, #96)', async ({
    page,
  }) => {
    // Rechargement avec params URL : zone deverrouilee cote serveur,
    // pas de clic carte necessaire.
    await page.goto(`/simulateur/?lat=${REIMS_LAT}&lng=${REIMS_LNG}`);
    await expect(page.locator('#form-after-localisation')).toBeVisible();
    // Message d'invite pas rendu (cote serveur).
    await expect(page.locator('#form-locked-message')).toHaveCount(0);
  });
});

test.describe('Simulateur nitrates : pas de parcelle pre-selectionnee (#153)', () => {
  // Regression #153 : un point ZAR (Chateau-Porcien) etait pre-clique au
  // chargement quand aucun lat/lng n'etait fourni. Resultat : une parcelle
  // apparaissait selectionnee, le form se devoilait et un auto-scroll
  // amenait directement aux questions sans laisser lire la page d'accueil.
  // On veut au contraire : carte vierge, aucun marker, message d'invite
  // visible, lat/lng vides. Verifie sur les DEUX endpoints (/ et /simulateur/).
  for (const path of ['/', '/simulateur/']) {
    test(`${path} : carte vierge, aucune parcelle pre-selectionnee`, async ({
      page,
    }) => {
      await page.goto(path);
      await expect(page.locator('#nitrates-map')).toHaveClass(/leaflet-container/);

      // lat/lng vides : rien n'a ete pre-rempli.
      await expect(page.locator('#id_lat')).toHaveValue('');
      await expect(page.locator('#id_lng')).toHaveValue('');

      // Aucun marker Leaflet pose sur la carte (pas de parcelle selectionnee).
      // Le pre-clic posait un L.marker -> icone .leaflet-marker-icon dans le DOM.
      // On laisse le temps a un eventuel clic synthetique de s'executer.
      await page.waitForTimeout(1000);
      await expect(page.locator('#nitrates-map .leaflet-marker-icon')).toHaveCount(0);

      // Le message d'invite est visible et le form reste verrouille : donc
      // pas de devoilement ni d'auto-scroll vers les questions.
      await expect(page.locator('#form-locked-message')).toBeVisible();
      await expect(page.locator('#form-locked-message')).toContainText(
        'Cliquez sur la carte'
      );
      await expect(page.locator('#form-after-localisation')).toBeHidden();
    });
  }
});

test.describe('Simulateur nitrates : cascade radios', () => {
  test('clic sur sol_non_cultive remplit occupation_sol et skip sous_culture', async ({
    page,
  }) => {
    await page.goto('/simulateur/');
    await waitForCascadeReady(page);

    await clickCascadeRadio(page, 'categorie_culture', 'sol_non_cultive');

    // Le hidden occupation_sol est resolu directement (pas de sous-categorie).
    await expect(page.locator('#id_occupation_sol')).toHaveValue('sol_non_cultive');
    // Wrapper sous_culture_form reste cache.
    await expect(page.locator('#sous_culture_form-wrapper')).toBeHidden();
    // categorie_fertilisant doit etre apparu (cascade saute le niveau 2).
    await expect(page.locator('#categorie_fertilisant-wrapper')).toBeVisible();
  });

  test('clic sur culture_hiver -> sous_cultures avec colza visible', async ({
    page,
  }) => {
    await page.goto('/simulateur/');
    await waitForCascadeReady(page);

    await clickCascadeRadio(page, 'categorie_culture', 'culture_hiver');

    // Le wrapper sous_culture_form doit etre visible avec au moins colza.
    await expect(page.locator('#sous_culture_form-wrapper')).toBeVisible();
    // Le label colza est rendu (l'input lui-meme est masque par DSFR).
    await expect(page.locator('label[for="id_sous_culture_form__colza"]')).toBeVisible();
  });

  test('titre section Fertilisant cache tant que le niveau n est pas atteint (#160)', async ({
    page,
  }) => {
    // Regression : quand la cascade Culture n'est pas finie, le titre
    // « Fertilisant » s'affichait seul (titre orphelin au-dessus du bouton).
    await page.goto('/simulateur/');
    await waitForCascadeReady(page);

    // Etat initial (aucune culture choisie) : section Fertilisant cachee.
    await expect(page.locator('#section-fertilisant')).toBeHidden();

    // On choisit une culture SANS aller jusqu'au fertilisant (couvert court :
    // sous_culture_form s'affiche mais categorie_fertilisant pas encore).
    await clickCascadeRadio(page, 'categorie_culture', 'couvert_intercultures_courte');
    await expect(page.locator('#sous_culture_form-wrapper')).toBeVisible();
    // La section Fertilisant reste cachee (pas de titre orphelin).
    await expect(page.locator('#section-fertilisant')).toBeHidden();

    // sol_non_cultive saute le niveau 2 -> la section Fertilisant apparait.
    await clickCascadeRadio(page, 'categorie_culture', 'sol_non_cultive');
    await expect(page.locator('#section-fertilisant')).toBeVisible();

    // Retour sur couvert court -> la section Fertilisant se recache.
    await clickCascadeRadio(page, 'categorie_culture', 'couvert_intercultures_courte');
    await expect(page.locator('#section-fertilisant')).toBeHidden();
  });

  test('cascade culture_hiver + colza -> occupation_sol + sous_culture remplis', async ({
    page,
  }) => {
    await page.goto('/simulateur/');
    await waitForCascadeReady(page);

    await clickCascadeRadio(page, 'categorie_culture', 'culture_hiver');
    await clickCascadeRadio(page, 'sous_culture_form', 'colza');

    // Le mapping colza -> {occupation_sol: culture_principale, sous_culture: colza}.
    await expect(page.locator('#id_occupation_sol')).toHaveValue('culture_principale');
    await expect(page.locator('#id_sous_culture')).toHaveValue('colza');

    // Categorie fertilisant est apparue.
    await expect(page.locator('#categorie_fertilisant-wrapper')).toBeVisible();
  });

  test('cascade complete colza + engrais_azote_mineral -> type_III en hidden', async ({
    page,
  }) => {
    await page.goto('/simulateur/');
    await waitForCascadeReady(page);

    await clickCascadeRadio(page, 'categorie_culture', 'culture_hiver');
    await clickCascadeRadio(page, 'sous_culture_form', 'colza');
    await clickCascadeRadio(page, 'categorie_fertilisant', 'engrais_mineral');
    await clickCascadeRadio(page, 'sous_fertilisant', 'engrais_azote_mineral');

    // type_fertilisant resolu via mapping_sous_fertilisant_vers_type.
    await expect(page.locator('#id_type_fertilisant')).toHaveValue('type_III');
  });

  test('cascade colza + compost_fientes_volailles -> type_II', async ({ page }) => {
    await page.goto('/simulateur/');
    await waitForCascadeReady(page);

    await clickCascadeRadio(page, 'categorie_culture', 'culture_hiver');
    await clickCascadeRadio(page, 'sous_culture_form', 'colza');
    await clickCascadeRadio(page, 'categorie_fertilisant', 'composts');
    await clickCascadeRadio(page, 'sous_fertilisant', 'compost_fientes_volailles');

    await expect(page.locator('#id_type_fertilisant')).toHaveValue('type_II');
  });
});

test.describe('Simulateur nitrates : flow complet et resultats', () => {
  test('flow complet sol_non_cultive -> resultat interdit toute l annee', async ({
    page,
  }) => {
    await page.goto('/simulateur/');
    await waitForCascadeReady(page);

    // Clic carte sur Reims
    await page.evaluate(([lng, lat]) => {
      const w = window as any;
      w.nitratesMap.fire('click', { latlng: w.L.latLng(lat, lng) });
    }, [REIMS_LNG, REIMS_LAT]);
    // Lat/lng populated par le handler leaflet click (async).
    await expect(page.locator('#id_lat')).toHaveValue(/49\.258/);

    await clickCascadeRadio(page, 'categorie_culture', 'sol_non_cultive');
    await expect(page.locator('#id_occupation_sol')).toHaveValue('sol_non_cultive');
    await page.locator('button[type="submit"]').click();

    // Page resultat
    await expect(page).toHaveURL(/\/simulateur\/\?/);
    await expect(page.locator('body')).toContainText('r_sol_non_cultive');
    await expect(page.locator('body')).toContainText('interdi');
    // Periode : toute l'annee, ecrite en annee agricole (01/07 -> 30/06)
    // pour que le calendrier d'epandage rende une zone rouge pleine
    // sur l'axe juil-juin (cf. #54).
    await expect(page.locator('body')).toContainText('01/07');
    await expect(page.locator('body')).toContainText('30/06');
  });

  test('flow complet colza + compost_jeunes (type_0) -> regle r_colza_type_0', async ({
    page,
  }) => {
    await page.goto('/simulateur/');
    await waitForCascadeReady(page);

    await page.evaluate(([lng, lat]) => {
      const w = window as any;
      w.nitratesMap.fire('click', { latlng: w.L.latLng(lat, lng) });
    }, [REIMS_LNG, REIMS_LAT]);
    await expect(page.locator('#id_lat')).toHaveValue(/49\.258/);

    await clickCascadeRadio(page, 'categorie_culture', 'culture_hiver');
    await clickCascadeRadio(page, 'sous_culture_form', 'colza');
    await clickCascadeRadio(page, 'categorie_fertilisant', 'composts');
    // compost_dechets_verts_jeunes_ligneux mappe vers type_0
    await clickCascadeRadio(
      page,
      'sous_fertilisant',
      'compost_dechets_verts_jeunes_ligneux'
    );
    await expect(page.locator('#id_type_fertilisant')).toHaveValue('type_0');

    await page.locator('button[type="submit"]').click();

    await expect(page).toHaveURL(/\/simulateur\/\?/);
    await expect(page.locator('body')).toContainText('r_colza_type_0');
    await expect(page.locator('body')).toContainText('interdi');
    // Periode actuelle de la regle (peut evoluer avec le brouillon)
    await expect(page.locator('body')).toContainText('15/12');
    await expect(page.locator('body')).toContainText('15/01');
  });

  test('point hors ZV affiche le message hors zone vulnerable', async ({ page }) => {
    // On va directement avec les query params (carte ne couvre pas l'offshore
    // dans la viewport par defaut)
    await page.goto(`/simulateur/?lng=${OFFSHORE_LNG}&lat=${OFFSHORE_LAT}`);

    await expect(page.locator('body')).toContainText(/Hors zone vuln|hors ZV/);
  });

  test('flow complet via formulaire pre-rempli depuis URL', async ({ page }) => {
    // Page resultat directement, on verifie que le rendu marche.
    // type_fertilisant peut etre passe directement en URL (utile pour debug
    // et tests) sans passer par la cascade catégorie + sous_fertilisant.
    await page.goto(
      `/simulateur/?lng=${REIMS_LNG}&lat=${REIMS_LAT}` +
        '&occupation_sol=culture_principale' +
        '&sous_culture=colza&type_fertilisant=type_I'
    );

    await expect(page.locator('body')).toContainText('r_colza_type_I');
    // type_I -> interdit du 15/11 au 15/01
    await expect(page.locator('body')).toContainText('15/11');
    await expect(page.locator('body')).toContainText('15/01');
  });

  test('fallback type_Ia retombe sur la branche type_I de l arbre', async ({
    page,
  }) => {
    // L'arbre PAN actuel a une branche `type_I` combinee sur certaines
    // cultures. Le mapping referentiel resout fumier_compact vers type_Ia.
    // Le parcours doit retomber sur type_I et atteindre la meme regle.
    await page.goto(
      `/simulateur/?lng=${REIMS_LNG}&lat=${REIMS_LAT}` +
        '&occupation_sol=culture_principale' +
        '&sous_culture=colza&type_fertilisant=type_Ia'
    );

    // Doit atteindre la meme regle r_colza_type_I via fallback Ia -> I
    await expect(page.locator('body')).toContainText('r_colza_type_I');
  });
});

test.describe('Simulateur nitrates : endpoints API', () => {
  // On passe par page.evaluate(fetch) plutot que request.get : la base
  // request de Playwright n'utilise pas le --host-resolver-rules, donc
  // nitrates.local ne resout pas dans le conteneur node.
  test('/api/referentiels/ renvoie un JSON avec les listes fermees', async ({
    page,
  }) => {
    await page.goto('/simulateur/');
    const data = await page.evaluate(() =>
      fetch('/api/referentiels/').then((r) => r.json())
    );
    expect(data).toHaveProperty('types_fertilisants');
    // Note 2026-05-12 : la cle 'cultures' a ete refacto en
    // 'categories_cultures' + 'sous_cultures' (cf. cascade 5 niveaux).
    expect(data).toHaveProperty('categories_cultures');
    expect(data).toHaveProperty('sous_cultures');
    expect(data).toHaveProperty('codes_prescription');
  });

  test('/api/arbre/ renvoie l arbre PAN national', async ({ page }) => {
    await page.goto('/simulateur/');
    const data = await page.evaluate(() =>
      fetch('/api/arbre/').then((r) => r.json())
    );
    expect(data.arbre.noeud.id).toBe('n_zvn');
  });
});
