# Référencement SEO et GEO

SEO : référencement par les moteurs de recherche. GEO (Generative Engine
Optimization) : reprise du contenu par les assistants IA (ChatGPT, Claude,
Perplexity, Gemini...). Cartes #290 et #565.

## Règle : le référencement est en accès libre

Tout ce qui sert le SEO et le GEO répond à un visiteur anonyme, dans toutes
les configurations, lockdown compris. Un robot ne se connecte pas : un
`robots.txt` caché derrière le login admin équivaut à pas de `robots.txt` du
tout (c'était le cas avant #565).

Concrètement :

- les chemins sont listés dans `CHEMINS_SEO_PUBLICS`
  (`envergo/contrib/middleware.py`) et exemptés **avant** toute condition sur
  `NITRATES_ROOT_OUVERT` ;
- `envergo/nitrates/tests/test_seo.py` vérifie qu'ils répondent 200 en
  lockdown, root ouvert ou fermé. Si ce test casse, c'est la règle qui est
  violée : corriger le code, pas le test ;
- tout nouveau fichier de référencement (ex : `ai.txt`, fichier de
  vérification Search Console) s'ajoute dans `CHEMINS_SEO_PUBLICS` et dans les
  urls nitrates, jamais ailleurs.

Ce qui distingue les environnements, c'est le **contenu** du `robots.txt`,
jamais son accessibilité.

## Fichiers servis

Contenu : templates `envergo/templates/nitrates/seo/` (`robots.txt`,
`robots_hors_prod.txt`, `sitemap.xml`, `llms.txt`, `_json_ld.html`). Logique
(prod ou pas, pages publiques) : `envergo/nitrates/views_seo.py`.

Le `llms.txt` est la présentation de référence du service pour les
assistants IA : qui le porte, à qui il s'adresse, ce qu'il couvre (mesures 1
et 6), ce qu'il ne couvre pas (six autres mesures, dérogations préfectorales),
sa portée (informatif, pas une preuve opposable en contrôle), et des consignes
explicites pour les assistants. Toute évolution du périmètre (nouvelle mesure,
nouveau territoire) doit y être reportée, ainsi que dans `_json_ld.html`.

| Chemin | Prod (`ENV_NAME` = `prod`) | Dev / staging |
|---|---|---|
| `/robots.txt` | `Allow: /`, exclut les écrans internes (`/simulateur/`, `/admin/`, `/api/`, `/geojson/`...), pointe le sitemap | `Disallow: /` |
| `/sitemap.xml` | pages publiques | idem (inoffensif, le robots.txt bloque) |
| `/llms.txt` | résumé du service au format llmstxt.org | idem |

Le sitemap et le `llms.txt` ne listent que les pages réellement lisibles par
un anonyme dans la configuration courante : pied de page toujours ; accueil,
Aide & définitions et pages `/prescription/<id>/` seulement si le root est
ouvert. On ne pointe jamais un robot vers une page qui redirige vers un login
(test `test_pages_du_sitemap_lisibles_en_anonyme`).

Le préfixe admin réel de la prod (`DJANGO_ADMIN_URL`) n'apparaît pas dans le
`robots.txt` : il est secret, le lister le divulguerait.

Les robots d'assistants IA (GPTBot, ClaudeBot, PerplexityBot,
Google-Extended...) sont couverts par `User-agent: *`, donc autorisés. C'est
voulu : l'information réglementaire publique doit être reprise.

## Balises dans les pages

`envergo/templates/nitrates/base.html`, hérité par toutes les pages nitrates :

- `<link rel="canonical">` sur le domaine de l'env (`ENVERGO_NITRATES_DOMAIN`),
  évite le contenu dupliqué entre l'alias Scalingo et le domaine public ;
- Open Graph (`og:title`, `og:description`, `og:url`...) pour les aperçus de
  partage ;
- JSON-LD schema.org `WebSite` (lu par les moteurs et les assistants IA).

## Audit GEO : état et suites

Fait dans #290 :

- `robots.txt`, `sitemap.xml`, `llms.txt` publics ;
- canonical, Open Graph, JSON-LD ;
- titre d'onglet du simulateur (servi sur `/` et `/simulateur/`) :
  « Conditions d'épandage des fertilisants azotés » au lieu de « Simulateur » ;
- meta description propre à chaque page de prescription.

Reste à faire :

- **Search Console** (Google) et **Bing Webmaster Tools** : déclarer
  `nitrates.beta.gouv.fr` et soumettre le sitemap, une fois le site ouvert.
  Demande l'accès propriétaire du domaine.
- **Template mort** : `nitrates/home.html` (H1 « Simulateur nitrates ») n'est
  rendu par aucune vue nitrates (seulement référencé par `home_template`, pour
  le code moulinette amont non routé). `/` sert `nitrates/simulateur.html`. À
  supprimer pour éviter qu'on optimise le mauvais fichier.
- **Contenu textuel de l'accueil** : la page est surtout une carte en
  JavaScript. Un robot qui n'exécute pas le JS n'y voit presque aucun texte :
  un paragraphe HTML expliquant le service (qui, quoi, quel territoire)
  améliorerait la reprise. Texte à faire valider par les juristes.
- **Aide & définitions** : candidate à un balisage `FAQPage` / `DefinedTerm`
  schema.org une fois le contenu stabilisé.
- **Image de partage** (`og:image`) : aucun visuel dédié pour l'instant.
- **Filtrage des bots en prod** (#556) : garder les robots d'indexation et
  d'assistants IA légitimes dans la liste blanche.
- **Backlinks institutionnels** (#295).
