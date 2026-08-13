/**
 * #186 - Rendu du calendrier aux EXTRÉMITÉS de l'année agricole.
 *
 * Trois défauts signalés par la métier, tous localisés aux bords de la barre
 * (1er juillet à gauche, 30 juin à droite), là où aucun tic de borne ne vient
 * matérialiser la frontière :
 *
 *  1. "contour gauche/droite absent" : une zone adossée à un bord dessinait un
 *     rectangle à angles droits qui débordait l'arrondi 8px de la barre, sans
 *     bordure latérale pour la refermer (elles ont été retirées en #132/#134,
 *     où chaque frontière INTERNE est portée par le tic de sa borne).
 *  2. label de borne coupé : centré via translateX(-50%) à 0%, la moitié du
 *     texte sortait du conteneur -> "/07" au lieu de "01/07".
 *  3. "point Aujourd'hui incomplet" : rond de 9px centré, amputé de moitié par
 *     l'overflow:hidden de la barre.
 *
 * On teste la GÉOMÉTRIE MESURÉE (getBoundingClientRect), pas les styles inline :
 * c'est le seul contrat valable pour les deux renderers (le statique pose des
 * %, le dynamique des px). Les tests unitaires Python/JS couvrent, eux, les
 * flags de bord en amont (test_templatetags_calendrier.py, *.test.js).
 */
import { test, expect, Locator, Page } from '@playwright/test';

/** Interdiction 01/07 -> 15/01 : zone collée au bord GAUCHE + borne à 0%. */
const URL_BORD_GAUCHE =
  '/simulateur/?lat=49.2583&lng=4.0345&code_insee=51454&categorie_culture=autres_cultures_principales&sous_culture_form=cultures_perennes_vergers_vignes&occupation_sol=culture_principale&sous_culture=autres_cultures&categorie_fertilisant=fumiers&sous_fertilisant=fumier_volaille&type_fertilisant=type_II';

/** Zones aux deux bords (capture 3 du ticket). */
const URL_DEUX_BORDS =
  '/simulateur/?lat=49.2583&lng=4.0345&code_insee=51454&occupation_sol=couvert_intercultures&sous_culture=cine_apres_0101&type_fertilisant=type_II&plan_epandage=icpe_autre&categorie_fertilisant=digestats&sous_fertilisant=digestat_brut_methanisation';

/** Calendrier DYNAMIQUE (calculatrice, .calc-cal) : même contrat de rendu. */
const URL_DYNAMIQUE =
  '/simulateur/?lat=49.2583&lng=4.0345&code_insee=51454&categorie_culture=couvert_intercultures_longue&sous_culture_form=couvert_recolte_plus_en_place_apres_3112&occupation_sol=couvert_intercultures&sous_culture=cie_avant_3112&type_fertilisant=type_III&categorie_fertilisant=engrais_mineral&sous_fertilisant=engrais_azote_mineral&date_semis_couvert=15/08';

/** Gèle les animations et masque la carte (sinon les captures Leaflet timeout). */
async function figer(page: Page) {
  await page.addStyleTag({
    content: `*,*::before,*::after{animation:none!important;transition:none!important}
              .leaflet-container,#map{visibility:hidden!important}`,
  });
}

async function ouvrirCalendrier(page: Page, url: string, sel = '.calendrier-epandage') {
  await page.goto(url);
  const cal = page.locator(sel).first();
  await expect(cal).toBeVisible();
  // Le calendrier dynamique est rendu par JS APRÈS le load, et le layout
  // anti-collision des bornes (calendrier_bornes_layout.js) repasse ensuite :
  // on attend qu'au moins une zone soit posée ET que la barre ait une largeur
  // stable, sinon les rects mesurés plus bas sont ceux d'un DOM intermédiaire.
  await expect(cal.locator('.calendrier-epandage__zone').first()).toBeVisible();
  await expect
    .poll(async () =>
      cal.evaluate(
        (el) =>
          (el.querySelector('.calendrier-epandage__bar') as HTMLElement)
            .getBoundingClientRect().width
      )
    )
    .toBeGreaterThan(0);
  await figer(page);
  return cal;
}

/**
 * Contrat central : toute zone qui touche un bord de la barre porte la classe
 * de fermeture correspondante, et RÉCIPROQUEMENT une zone interne n'en porte
 * pas (sinon on réintroduit le double-trait bordure+tic corrigé en #132/#134).
 */
async function verifierZonesDeBord(cal: Locator) {
  const zones = await cal.evaluate((el) => {
    const bar = el.querySelector('.calendrier-epandage__bar') as HTMLElement;
    const b = bar.getBoundingClientRect();
    return [...el.querySelectorAll('.calendrier-epandage__zone')].map((z) => {
      const r = z.getBoundingClientRect();
      return {
        dLeft: r.left - b.left,
        dRight: b.right - r.right,
        bordGauche: z.classList.contains('calendrier-epandage__zone--bord-gauche'),
        bordDroit: z.classList.contains('calendrier-epandage__zone--bord-droit'),
      };
    });
  });
  expect(zones.length).toBeGreaterThan(0);
  for (const z of zones) {
    expect(z.bordGauche).toBe(z.dLeft <= 1);
    expect(z.bordDroit).toBe(z.dRight <= 1);
  }
  return zones;
}

test('#186 statique : zone collée au bord gauche fermée et arrondie', async ({ page }) => {
  const cal = await ouvrirCalendrier(page, URL_BORD_GAUCHE);
  const zones = await verifierZonesDeBord(cal);
  // Le cas d'espèce DOIT contenir une zone au bord, sinon le test ne prouve
  // rien (une URL qui dériverait vers une autre feuille passerait à vide).
  expect(zones.some((z) => z.bordGauche)).toBe(true);

  // L'arrondi est ce qui manquait visuellement : on vérifie qu'il est appliqué
  // et qu'il vaut bien celui de la barre.
  const radius = await cal.evaluate((el) => {
    const z = el.querySelector('.calendrier-epandage__zone--bord-gauche') as HTMLElement;
    const bar = el.querySelector('.calendrier-epandage__bar') as HTMLElement;
    return {
      zone: getComputedStyle(z).borderTopLeftRadius,
      barre: getComputedStyle(bar).borderTopLeftRadius,
    };
  });
  expect(radius.zone).toBe(radius.barre);
  expect(parseFloat(radius.zone)).toBeGreaterThan(0);
});

test("#186 la zone de bord n'invente AUCUN décalage avant la période", async ({
  page,
}) => {
  // Régression métier explicite : une première tentative ajoutait une
  // `border-left` à la zone de bord. Elle créait un liseré de 1px AVANT le
  // début réel de la période -> ça revient à affirmer qu'il se passe quelque
  // chose entre le bord du calendrier et le 01/07, information qu'on n'a pas
  // et qui n'est pas modélisée (l'année agricole ne boucle pas). Et ça
  // désalignait le remplissage du tic de la borne.
  // La fermeture visuelle est portée par la BARRE (box-shadow inset) ; la zone
  // se superpose simplement par-dessus, sans géométrie propre.
  const cal = await ouvrirCalendrier(page, URL_BORD_GAUCHE);
  const m = await cal.evaluate((el) => {
    const z = el.querySelector('.calendrier-epandage__zone--bord-gauche') as HTMLElement;
    const cs = getComputedStyle(z);
    return { bl: cs.borderLeftWidth, br: cs.borderRightWidth };
  });
  expect(parseFloat(m.bl)).toBe(0);
  expect(parseFloat(m.br)).toBe(0);
});

test('#186 le tic du 01/07 tombe au bord EXACT de la barre', async ({ page }) => {
  // Le label est rabattu dans le conteneur pour ne pas être rogné, mais c'est
  // le TIC qui porte la position de la date : il doit rester à 0, sinon le
  // 01/07 est dessiné visuellement à la mi-juillet (c'est ce qui arrivait
  // quand les overrides ::before étaient déclarés AVANT la règle générique et
  // se faisaient écraser par `left:50%` — collision de cascade).
  const cal = await ouvrirCalendrier(page, URL_BORD_GAUCHE);
  const ecart = await cal.evaluate((el) => {
    const bar = el.querySelector('.calendrier-epandage__bar') as HTMLElement;
    const b = el.querySelector(
      '.calendrier-epandage__period-date--bord-gauche'
    ) as HTMLElement;
    const boite = b.getBoundingClientRect();
    // position du tic = bord gauche de la boîte + offset ::before
    const off = parseFloat(getComputedStyle(b, '::before').left);
    return boite.left + off - bar.getBoundingClientRect().left;
  });
  expect(Math.abs(ecart)).toBeLessThanOrEqual(1);
});

test('#186 statique : zones aux deux bords (capture 3 du ticket)', async ({ page }) => {
  const cal = await ouvrirCalendrier(page, URL_DEUX_BORDS);
  await verifierZonesDeBord(cal);
});

test('#186 dynamique : mêmes fermetures de bord que le statique', async ({ page }) => {
  const cal = await ouvrirCalendrier(page, URL_DYNAMIQUE, '.calc-cal .calendrier-epandage');
  const zones = await verifierZonesDeBord(cal);
  expect(zones.some((z) => z.bordGauche || z.bordDroit)).toBe(true);
});

test('#186 label de borne à 0% entièrement visible (plus de "/07" tronqué)', async ({
  page,
}) => {
  const cal = await ouvrirCalendrier(page, URL_BORD_GAUCHE);

  const borne = cal.locator('.calendrier-epandage__period-date--bord-gauche').first();
  await expect(borne).toBeVisible();
  // Le libellé doit être complet : c'est le symptôme vu par la métier.
  // (le markup indente le libellé -> on normalise les espaces avant de comparer)
  await expect(borne).toHaveText(/^\s*01\/07\s*$/);

  // Et il ne doit pas déborder du conteneur (sinon il serait rogné à l'écran).
  const debord = await cal.evaluate((el) => {
    const b = el.querySelector(
      '.calendrier-epandage__period-date--bord-gauche'
    ) as HTMLElement;
    return b.getBoundingClientRect().left - el.getBoundingClientRect().left;
  });
  expect(debord).toBeGreaterThanOrEqual(-0.5);
});

for (const pct of [0, 100]) {
  test(`#186 point "Aujourd'hui" entier à ${pct}% (jamais coupé en deux)`, async ({
    page,
  }) => {
    const cal = await ouvrirCalendrier(page, URL_BORD_GAUCHE);

    // La date du jour n'est pas pilotable depuis le navigateur : on déplace le
    // marqueur aux extrémités via --today-pct, exactement la variable que le
    // serveur renseigne. Le clamp() CSS doit le maintenir dans la barre.
    const m = await cal.evaluate((el, p) => {
      const bar = el.querySelector('.calendrier-epandage__bar') as HTMLElement;
      const pt = el.querySelector('.calendrier-epandage__today') as HTMLElement;
      const lbl = el.querySelector('.calendrier-epandage__today-label') as HTMLElement;
      pt.style.setProperty('--today-pct', `${p}%`);
      lbl.style.setProperty('--today-pct', `${p}%`);
      const b = bar.getBoundingClientRect();
      const r = pt.getBoundingClientRect();
      const l = lbl.getBoundingClientRect();
      return {
        largeur: r.width,
        ptGauche: b.left - r.left,
        ptDroite: r.right - b.right,
        lblGauche: b.left - l.left,
        lblDroite: l.right - b.right,
      };
    }, pct);

    // Le point garde sa taille pleine ET reste intégralement dans la barre.
    expect(m.largeur).toBeGreaterThan(0);
    expect(m.ptGauche).toBeLessThanOrEqual(0.5);
    expect(m.ptDroite).toBeLessThanOrEqual(0.5);
    // Le label était déjà protégé par le clamp() de #134 : on le verrouille.
    expect(m.lblGauche).toBeLessThanOrEqual(0.5);
    expect(m.lblDroite).toBeLessThanOrEqual(0.5);
  });
}
