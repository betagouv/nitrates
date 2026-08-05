/**
 * Validation #107 (cascade CSS pure) : le tic (::before) d'une borne
 * PHENOLOGIQUE reste NOIR meme quand la borne porte aussi la couleur du
 * regime (--orange / --rouge), dans les deux calendriers (statique et
 * dynamique --big-tick). On charge la vraie feuille calendrier.css et on lit
 * la couleur calculee du ::before pour chaque combinaison de classes.
 *
 * Pas de parcours metier (QC luzerne) : on teste la regle CSS elle-meme, qui
 * est le coeur du correctif. La classe --orange/--phenologique est posee par
 * le JS/template (cf. calculatrice-calendrier.js renderBornes) ; ici on la
 * simule directement. Test de non-regression pour #107.
 *
 * Usage : npm run e2e-nitrates -- tic_phenologique_noir.spec.ts
 */
import { test, expect } from '@playwright/test';

const CSS_URL = '/static/nitrates/calendrier.css';
const NOIR = 'rgb(22, 22, 22)'; // #161616

// Combinaisons de classes reellement produites par le rendu.
const CAS = [
  {
    nom: 'statique : phenologique + orange',
    classes:
      'calendrier-epandage__period-date calendrier-epandage__period-date--phenologique calendrier-epandage__period-date--orange',
  },
  {
    nom: 'statique : phenologique + rouge',
    classes:
      'calendrier-epandage__period-date calendrier-epandage__period-date--phenologique calendrier-epandage__period-date--rouge',
  },
  {
    nom: 'dynamique : phenologique + orange + big-tick',
    classes:
      'calendrier-epandage__period-date calendrier-epandage__period-date--phenologique calendrier-epandage__period-date--orange calendrier-epandage__period-date--big-tick',
  },
  {
    nom: 'dynamique : phenologique + rouge + big-tick',
    classes:
      'calendrier-epandage__period-date calendrier-epandage__period-date--phenologique calendrier-epandage__period-date--rouge calendrier-epandage__period-date--big-tick',
  },
];

test('#107 tic phenologique reste noir sur zone regime', async ({ page }) => {
  await page.goto('/');

  for (const cas of CAS) {
    const couleur = await page.evaluate(
      async ({ classes, cssUrl }) => {
        // Charger la vraie feuille calendrier.css.
        if (!document.querySelector(`link[href="${cssUrl}"]`)) {
          const link = document.createElement('link');
          link.rel = 'stylesheet';
          link.href = cssUrl;
          document.head.appendChild(link);
          await new Promise((r) => {
            link.onload = r;
            link.onerror = r;
          });
        }
        const wrap = document.createElement('div');
        wrap.className = 'calendrier-epandage';
        const el = document.createElement('span');
        el.className = classes;
        el.textContent = 'Dernière coupe luzerne';
        wrap.appendChild(el);
        document.body.appendChild(wrap);
        const c = getComputedStyle(el, '::before').backgroundColor;
        wrap.remove();
        return c;
      },
      { classes: cas.classes, cssUrl: CSS_URL }
    );
    // Le tic (::before) doit etre noir #161616 pour toutes les combinaisons.
    expect(couleur, `tic ${cas.nom}`).toBe(NOIR);
  }
});
