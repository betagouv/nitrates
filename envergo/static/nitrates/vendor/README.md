# Librairies JS embarquees

Copiees telles quelles depuis le registre npm, pas de CDN ni de dependance npm (CSP + supply chain).

| Fichier | Paquet | Source | sha256 |
|---|---|---|---|
| leaflet.vectorgrid-1.3.0.bundled.min.js | leaflet.vectorgrid 1.3.0 (2017, licence Beerware) | https://registry.npmjs.org/leaflet.vectorgrid/-/leaflet.vectorgrid-1.3.0.tgz, `dist/Leaflet.VectorGrid.bundled.min.js` | ed1e89e4c9582593890d0e869d03ed7a4ab56f511c6d2036392d6d50938aa4d5 |
| htmx-2.0.4.min.js | htmx.org 2.0.4 (déc. 2024, licence 0BSD), même version que l'admin | https://registry.npmjs.org/htmx.org/-/htmx.org-2.0.4.tgz, `dist/htmx.min.js` | 69caefd0da92269066e725d7fe175e26b9d50c962e3056459c0c477154cdb9d3 (dist e209dda5c8235479f3166defc7750e1dbcd5a5c1808b7792fc2e6733768fb447 + saut de ligne final ajouté par le hook end-of-file-fixer) |

Pour mettre a jour : retelecharger le tarball, verifier l'integrite npm, recopier le fichier dist et mettre a jour le sha256.
