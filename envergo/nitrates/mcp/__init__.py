"""Serveur MCP (Model Context Protocol) du simulateur nitrates.

Expose le simulateur aux assistants conversationnels (ChatGPT, Le Chat, etc.)
sous forme d'outils que l'assistant appelle quand un agriculteur lui parle de
ses épandages en langage naturel. L'assistant fait la conversation ; les
réponses réglementaires viennent toujours du simulateur (mêmes arbres, mêmes
référentiels, mêmes contenus que le formulaire public).

Modules :
    geocodage  : commune / adresse / coordonnées via les API publiques de l'État
    services   : localisation, catalogues, simulation, comparaison, contenus
    outils     : déclaration des outils MCP (nom, description, schéma d'entrée)
    protocole  : JSON-RPC 2.0 + MCP en transport « Streamable HTTP » sans état

Pas d'authentification : tout ce qui est exposé est déjà public (formulaire,
pages des prescriptions, définitions). Le point d'entrée est derrière le flag
NITRATES_MCP (cf. views_mcp).
"""
