# Scripts validation

Scripts Playwright utilitaires pour générer les captures des feuilles
de l'arbre nitrates (mode viewer + form + simulateur). Utilisés pour
peupler / rafraichir les screenshots de l'app validation admin.

## Usage

Depuis le repo, dans le conteneur node :

```bash
docker compose exec node node /app/envergo/nitrates/scripts/validation/capture_validation.mjs
docker compose exec node node /app/envergo/nitrates/scripts/validation/capture_viewer.mjs
docker compose exec node node /app/envergo/nitrates/scripts/validation/capture_yaml.mjs
```

Outputs : `out_simu/`, `out_yaml/` (gitignored — relancer pour
régénérer).

## Fixtures

- `branches_validation.json` : sous-ensemble des `BrancheValidation`
  utilisé par `capture_viewer.mjs` / `capture_yaml.mjs` (deeplinks
  admin).
- `branches_full.json` : liste complète avec URLs simulateur, pour
  `capture_validation.mjs`.

Ces fichiers sont régénérables côté Django (cf. `BrancheValidation`
model), mais on les commit comme snapshot d'exemple pour pouvoir
relancer sans repasser par Django.
