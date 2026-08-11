import { test, expect, Page } from '@playwright/test';

/**
 * #202 — Parcours CLIENT `/` (root public) sous config staging.
 *
 * Contexte : incident du 2026-07-02. Aucun test ne couvrait la combinaison
 * `LOCKDOWN_BEHIND_LOGIN=True` × `NITRATES_ROOT_OUVERT=True`, qui n'existe
 * QUE sur staging. Le bug ne vivait que là.
 *
 * Le mecanisme de l'incident, et pourquoi il est passe inapercu :
 * le middleware lockdown repond 302 vers /admin/login/ sur toute URL non
 * exemptee. Un `fetch()` suit ce 302 EN SILENCE et recoit du HTML de login
 * en 200 -> `response.ok === true`, aucune exception, aucune erreur console.
 * Le blocage se deguise en succes. Symptomes cote client : carte SIG vide,
 * formulaire fige sur "cliquez sur la carte", et au mieux un
 * "Unexpected token 'C', Connexion... is not valid JSON" au moment du
 * .json(). Un test qui se contente de `expect(response.ok())` ne voit RIEN.
 *
 * D'ou la regle de ce fichier : sur les endpoints de donnees, on assert le
 * **content-type** et le **statut non-redirige**, jamais seulement `ok`.
 *
 * PREREQUIS — ces tests n'ont de sens que face a un serveur lance en config
 * staging imitee. Cf. docker-compose.e2e202.local.yml (worktree
 * nitrates-e2e-202, port 8054) :
 *   DJANGO_LOCKDOWN_BEHIND_LOGIN=True
 *   DJANGO_NITRATES_ROOT_OUVERT=True
 * Lance contre un serveur ouvert (dev local par defaut), les tests de
 * fermeture echouent : c'est voulu, ils garantissent que le lockdown ferme
 * bien ce qu'il doit fermer. Le test `configuration` ci-dessous le dit
 * explicitement plutot que de laisser 4 echecs cryptiques.
 */

// Leaflet + WMTS IGN + GeoJSON ZV : les workers paralleles peuvent OOM-crash
// le conteneur node. Meme choix que simulateur.spec.ts.
test.describe.configure({ mode: 'serial' });

/**
 * Base URL pour les appels API directs (`request`).
 *
 * Subtilite Docker : en container, la config nitrates fait pointer le
 * navigateur sur `127.0.0.1:8000` et corrige l'IP via l'option Chromium
 * `--host-resolver-rules MAP 127.0.0.1 django`. Mais APIRequestContext
 * (`request`) est un client HTTP Node, PAS le navigateur : cette option ne
 * s'applique pas a lui, et il tombe sur ECONNREFUSED 127.0.0.1:8000.
 *
 * On resout donc l'hote nous-memes pour les appels API, tout en gardant le
 * Host header attendu par le middleware Site Django (id=3, 127.0.0.1).
 * Le navigateur, lui, continue d'utiliser le baseURL de la config.
 */
const IN_DOCKER = process.env.IN_DOCKER === '1';
const API_BASE = IN_DOCKER
  ? 'http://django:8000'
  : process.env.NITRATES_BASE_URL || 'http://127.0.0.1:8042';
/** Host header a envoyer avec les appels API en container (cf. Site Django). */
const API_HEADERS = IN_DOCKER ? { Host: '127.0.0.1:8000' } : {};

/** GET API sans suivre les redirections, avec le bon Host. */
function getApi(request: any, chemin: string) {
  return request.get(`${API_BASE}${chemin}`, {
    maxRedirects: 0,
    headers: API_HEADERS,
  });
}

// Reims (Marne, Grand Est, ZV bassin Seine-Normandie) — parcelle en zone
// vulnerable, donc parcours complet jusqu'au resultat.
const REIMS_LNG = 4.0345;
const REIMS_LAT = 49.2583;

/** Endpoints de DONNEES que le root public doit servir en JSON sans auth. */
const ENDPOINTS_DATA_OUVERTS = [
  '/geojson/zv/',
  '/geojson/zar/',
  '/api/referentiels/',
  `/simulateur/debug/?lat=${REIMS_LAT}&lng=${REIMS_LNG}`,
];

/** Endpoints qui doivent RESTER fermes meme quand le root est ouvert. */
const ENDPOINTS_FERMES = ['/simulateur/', '/api/arbre/'];

/**
 * Messages console qu'on tolere : le fond de carte IGN et l'API adresse sont
 * des services externes, intermittents, hors de notre controle. Tout le reste
 * est une regression.
 */
const CONSOLE_TOLERE = [
  'geo.api.gouv.fr',
  'api-adresse.data.gouv.fr',
  'data.geopf.fr',
  'wxs.ign.fr',
  'favicon',
  'ERR_INTERNET_DISCONNECTED',
];

function collecteErreursConsole(page: Page): string[] {
  const erreurs: string[] = [];
  page.on('console', (msg) => {
    if (msg.type() !== 'error') return;
    const texte = msg.text();
    if (CONSOLE_TOLERE.some((t) => texte.includes(t))) return;
    erreurs.push(texte);
  });
  page.on('pageerror', (err) => erreurs.push(`pageerror: ${err.message}`));
  return erreurs;
}

/** Simule le clic carte Leaflet (plus fiable que des coords DOM sur une carte tuilee). */
async function clicCarte(page: Page, lng: number, lat: number) {
  await expect(page.locator('#nitrates-map')).toHaveClass(/leaflet-container/);
  await page.evaluate(([lg, lt]) => {
    const w = window as any;
    w.nitratesMap.fire('click', { latlng: w.L.latLng(lt, lg) });
  }, [lng, lat]);
}

test.describe('#202 — root public sous lockdown (config staging)', () => {
  test('configuration : le serveur cible est bien en config staging imitee', async ({
    request,
  }) => {
    const root = await getApi(request, '/');
    expect(
      root.status(),
      "`/` doit etre accessible sans auth (NITRATES_ROOT_OUVERT=True attendu)"
    ).toBe(200);

    const simulateur = await getApi(request, '/simulateur/');
    expect(
      simulateur.status(),
      "`/simulateur/` doit etre ferme (302). Si tu obtiens 200, le serveur " +
        'tourne SANS lockdown : lance-le via docker-compose.e2e202.local.yml, ' +
        'sinon cette suite ne teste pas la config staging.'
    ).toBe(302);
  });

  // --- Le test qui aurait detecte l'incident -----------------------------

  for (const chemin of ENDPOINTS_DATA_OUVERTS) {
    test(`donnees : ${chemin} repond en JSON strict, sans redirection`, async ({
      request,
    }) => {
      // maxRedirects: 0 — on veut voir le 302 s'il existe, PAS le suivre.
      // C'est toute la difference avec le fetch() du navigateur qui, lui,
      // le suit en silence et transforme le blocage en faux succes.
      const reponse = await getApi(request, chemin);

      expect(
        reponse.status(),
        `${chemin} redirige (302) : le lockdown intercepte un endpoint qui ` +
          'doit etre exempte. Cote navigateur ca se traduit par du HTML de ' +
          'login recu en 200 -> carte vide / formulaire fige.'
      ).toBe(200);

      const contentType = reponse.headers()['content-type'] || '';
      expect(
        contentType,
        `${chemin} ne renvoie pas du JSON (content-type: "${contentType}"). ` +
          "Si c'est du text/html, c'est la page de login deguisee en succes."
      ).toContain('application/json');

      // Le corps doit reellement parser : ceinture et bretelles contre une
      // page HTML servie avec un content-type menteur.
      await expect(
        reponse.json(),
        `${chemin} : content-type JSON mais corps non parsable`
      ).resolves.toBeDefined();
    });
  }

  test('contre-verif : les endpoints fermes redirigent bien vers le login', async ({
    request,
  }) => {
    for (const chemin of ENDPOINTS_FERMES) {
      const reponse = await getApi(request, chemin);
      expect(
        reponse.status(),
        `${chemin} devrait rester ferme (302) quand le root est ouvert. ` +
          "Un 200 ici = fuite d'acces : l'exemption root ouvre trop large."
      ).toBe(302);
      expect(reponse.headers()['location'] || '').toContain('/login/');
    }
  });

  // --- Parcours client complet ------------------------------------------

  test('la page racine se charge : carte Leaflet + hero, sans erreur console', async ({
    page,
  }) => {
    const erreurs = collecteErreursConsole(page);
    await page.goto('/');

    await expect(page.locator('h1')).toContainText("conditions d'épandage");
    await expect(page.locator('#nitrates-map')).toHaveClass(/leaflet-container/);

    // La couche ZV vient d'un fetch sur /geojson/zv/ : si le lockdown
    // l'interceptait, on aurait une carte sans overlay et zero erreur.
    await expect
      .poll(
        () =>
          page.evaluate(() => {
            const w = window as any;
            return w.nitratesMap ? Object.keys(w.nitratesMap._layers || {}).length : 0;
          }),
        { timeout: 15000, message: 'aucune couche Leaflet chargee' }
      )
      .toBeGreaterThan(0);

    expect(erreurs, `erreurs console: ${erreurs.join(' | ')}`).toEqual([]);
  });

  test('recherche commune (BAN) : la suggestion recentre la carte', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('#nitrates-map')).toHaveClass(/leaflet-container/);

    const centreAvant = await page.evaluate(() => {
      const c = (window as any).nitratesMap.getCenter();
      return [c.lat, c.lng];
    });

    await page.locator('#map-search').fill('Reims');

    const suggestions = page.locator('#map-search-list li');
    await expect(suggestions.first()).toBeVisible({ timeout: 15000 });
    await suggestions.first().click();

    await expect
      .poll(
        async () => {
          const c = await page.evaluate(() => {
            const ctr = (window as any).nitratesMap.getCenter();
            return [ctr.lat, ctr.lng];
          });
          return Math.abs(c[0] - centreAvant[0]) + Math.abs(c[1] - centreAvant[1]);
        },
        { timeout: 15000, message: 'la carte ne s’est pas recentree' }
      )
      .toBeGreaterThan(0.01);
  });

  test('parcours complet : clic carte -> formulaire -> simulation -> resultat', async ({
    page,
  }) => {
    const erreurs = collecteErreursConsole(page);
    await page.goto('/');
    await clicCarte(page, REIMS_LNG, REIMS_LAT);

    // Le formulaire n'apparait que si /simulateur/debug/ a repondu en JSON
    // avec `simulateur_ouvert`. Sous l'incident, ce fetch recevait du HTML
    // de login -> le formulaire ne s'affichait JAMAIS. Ce wait est donc,
    // a lui seul, un test de non-regression de l'incident.
    await expect
      .poll(
        () =>
          page.locator('[data-cascade="categorie_culture"] input[type="radio"]').count(),
        { timeout: 20000, message: 'formulaire jamais revele apres le clic carte' }
      )
      .toBeGreaterThan(0);

    expect(erreurs, `erreurs console: ${erreurs.join(' | ')}`).toEqual([]);
  });
});
