# Couverture de tests — module `envergo/nitrates`

Rapport `coverage.py` (natif, plugin Django) sur la suite `envergo/nitrates/tests/`,
périmètre release **0.3.0**. Mesuré le 2026-06-24 (commit `37ba6d762`).

Configuration : `setup.cfg` `[coverage:*]` (exclut tests, migrations, `__init__`, `apps.py`, settings).
Généré par la CI à chaque run ; ce fichier est un instantané versionné pour suivi.

## Synthèse

- **Total module nitrates : 74 %** (7594 lignes, 1963 non couvertes).
- **Cœur moteur de décision : 100 %** — `parcours.py`, `arbre_decision.py`,
  `expression.py`, `feuilles.py`, `schema.py` ; `validator.py` 98 %, `condition.py` 96 %.
- Couverture la plus basse concentrée sur les commandes d'ingestion/seed Miro
  (one-shot, non testées) et l'éditeur admin YAML (`views_admin_yaml_edit.py` 74 %).

## Rapport complet

```
Name                                                                       Stmts   Miss  Cover   Missing
--------------------------------------------------------------------------------------------------------
envergo/nitrates/admin.py                                                    225     78    65%   41, 60-67, 87, 93-95, 100, 127-130, 190-204, 224-251, 262, 266, 270-280, 295-321, 335-349, 404-406, 472, 495-498, 504-507, 547-548, 563, 577-580
envergo/nitrates/auth.py                                                      38      3    92%   36, 65, 77
envergo/nitrates/bassins.py                                                   24      7    71%   55, 60-64, 73
envergo/nitrates/constants.py                                                 28      0   100%
envergo/nitrates/contenu_rich/compilateur.py                                  91      8    91%   48, 55-56, 58, 66, 188-189, 203
envergo/nitrates/contenu_rich/loader.py                                        9      0   100%
envergo/nitrates/forms.py                                                     11      0   100%
envergo/nitrates/management/commands/attach_couvert_screenshots.py            48     48     0%   20-106
envergo/nitrates/management/commands/attach_validation_screenshot.py          31     31     0%   16-67
envergo/nitrates/management/commands/export_manifeste_capture_couvert.py      42     42     0%   22-110
envergo/nitrates/management/commands/export_manifeste_capture_par_ge.py       47     47     0%   15-128
envergo/nitrates/management/commands/export_manifeste_capture_zar.py          45     45     0%   24-119
envergo/nitrates/management/commands/import_decision_tree.py                  96     12    88%   119-122, 146, 154, 164-165, 171-173, 194
envergo/nitrates/management/commands/import_nitrates_departments.py           82     37    55%   76, 84, 91-145
envergo/nitrates/management/commands/import_nitrates_rpg.py                  116     18    84%   166-170, 174-177, 212-216, 225-226, 234-237, 241-245
envergo/nitrates/management/commands/import_nitrates_zar.py                  126     35    72%   91, 94, 102, 107-129, 132-133, 136-148, 255-256
envergo/nitrates/management/commands/import_nitrates_zv.py                   125     34    73%   99, 107, 114-158, 225, 276
envergo/nitrates/management/commands/import_rpg_cultures.py                   38      0   100%
envergo/nitrates/management/commands/ingest_captures_couvert.py               53     53     0%   21-93
envergo/nitrates/management/commands/ingest_crops_miro_couvert.py             39     39     0%   20-79
envergo/nitrates/management/commands/ingest_crops_miro_par.py                 39     39     0%   19-78
envergo/nitrates/management/commands/ingest_crops_miro_zar.py                 39     39     0%   19-78
envergo/nitrates/management/commands/ingest_miro_widget_ids.py                54     54     0%   29-105
envergo/nitrates/management/commands/ingest_miro_widget_ids_par_ge.py         55     55     0%   32-112
envergo/nitrates/management/commands/ingest_miro_widget_ids_zar.py            54     54     0%   27-103
envergo/nitrates/management/commands/provision_admin.py                       51      4    92%   64, 95, 99, 116
envergo/nitrates/management/commands/provision_carte_98.py                    33      3    91%   94-102
envergo/nitrates/management/commands/provision_zones_est.py                   92     10    89%   94, 126, 144, 154, 158, 166, 171, 175-179, 214
envergo/nitrates/management/commands/seed_branches_validation.py             253    253     0%   26-563
envergo/nitrates/management/commands/seed_branches_validation_couvert.py      92     92     0%   45-281
envergo/nitrates/management/commands/seed_branches_validation_par_ge.py       65     65     0%   36-201
envergo/nitrates/management/commands/seed_branches_validation_zar_ge.py       55     55     0%   45-180
envergo/nitrates/management/commands/seed_contenus_rich.py                    38      4    89%   45-46, 53, 58
envergo/nitrates/management/commands/seed_referentiels.py                    173     13    92%   68-69, 187-193, 209-212, 257-262, 265-270, 324, 340-341
envergo/nitrates/models.py                                                   305     31    90%   63, 219, 227-241, 465, 665, 682, 689-691, 712, 718, 728, 751-752, 946, 949, 959-962, 994-995
envergo/nitrates/models_contenu_rich.py                                       23      2    91%   69, 83
envergo/nitrates/models_ouverture.py                                          19      2    89%   53-54
envergo/nitrates/models_referentiels.py                                       93      7    92%   65, 97, 146, 215, 254, 310, 350
envergo/nitrates/permissions.py                                               56      7    88%   20, 62, 64, 71, 78, 106, 114
envergo/nitrates/regions.py                                                    7      0   100%
envergo/nitrates/regulations/arbre_decision.py                               178      0   100%
envergo/nitrates/regulations/directive_nitrates.py                             3      0   100%
envergo/nitrates/templatetags/nitrates_tags.py                               266     22    92%   40-42, 54, 57-58, 82-83, 216, 230-231, 317, 321, 328-331, 580, 708-713
envergo/nitrates/templatetags/yaml_admin_extras.py                           146     26    82%   15, 22, 29, 46, 68-71, 105, 129-130, 153, 186-190, 211, 255-256, 262-268
envergo/nitrates/urls.py                                                      11      0   100%
envergo/nitrates/views.py                                                    160     31    81%   30-33, 312-313, 353-354, 467-470, 491-492, 495-515, 557-568
envergo/nitrates/views_admin_ouverture.py                                     51      1    98%   123
envergo/nitrates/views_admin_validation.py                                   135     97    28%   36-121, 136-183, 192-196, 205-214, 234-245, 257-273, 280-285, 292-297, 304-309, 321-345, 352-364
envergo/nitrates/views_admin_yaml.py                                         163     21    87%   61-70, 77, 176, 180, 191, 246, 267-269, 316, 331-332, 346, 363-369
envergo/nitrates/views_admin_yaml_edit.py                                    913    240    74%   81-82, 114, 126, 190, 197-198, 301, 313, 338, 357, 361, 369-373, 405-411, 521, 526, 553, 560, 564, 601-604, 641-647, 676, 681, 713, 718, 724-725, 741, 814, 843, 928, 936-937, 954-955, 983, 1019, 1024, 1033-1035, 1037-1040, 1049-1055, 1093, 1097, 1100, 1103, 1137, 1141, 1145, 1158, 1173, 1187, 1223, 1243-1244, 1267, 1305, 1321-1326, 1336, 1348-1358, 1360, 1363, 1366, 1371-1374, 1386, 1388, 1390, 1427-1430, 1557, 1560, 1563, 1566, 1569, 1579, 1584, 1600, 1626-1628, 1674, 1679, 1688, 1700, 1705, 1721, 1745, 1753-1756, 1767-1778, 1795-1817, 1829-1843, 1864, 1894-1908, 1934, 1965, 1984, 1990-1996, 2003, 2009, 2012, 2017-2022, 2046-2050, 2075, 2087, 2116-2213, 2234, 2239, 2276, 2283, 2297, 2301-2302, 2307, 2324
envergo/nitrates/views_contenu_rich_preview.py                                29     20    31%   27-58
envergo/nitrates/views_yaml_browser.py                                        32     16    50%   24-38, 48-52, 55-59
envergo/nitrates/yaml_admin/catalogue_refs.py                                 42      6    86%   76-78, 96, 104, 108
envergo/nitrates/yaml_admin/editor.py                                        324     40    88%   81, 109, 141, 151, 187, 281, 353, 358, 370, 390, 449, 453, 498, 540, 551, 555, 582, 587, 593, 620, 623, 682, 699, 708, 721, 752, 755, 767, 778, 791, 806-809, 820, 841, 844, 872, 874, 877
envergo/nitrates/yaml_admin/flatten.py                                        37      0   100%
envergo/nitrates/yaml_admin/fold.py                                           49      3    94%   33, 39, 78
envergo/nitrates/yaml_admin/forms.py                                         204     10    95%   99, 197, 216, 241, 257, 293, 328, 330, 352-353
envergo/nitrates/yaml_admin/grammar.py                                       290     30    90%   114, 133, 189, 199, 202, 223, 225, 236, 242-250, 261, 290-291, 295, 341-342, 361, 376, 385-386, 464, 478, 502, 529, 550-552, 558, 564
envergo/nitrates/yaml_admin/loader.py                                         26      5    81%   35, 46-49
envergo/nitrates/yaml_admin/preview.py                                       224     28    88%   226, 247-251, 264, 397, 402-403, 418-419, 453, 533, 542, 550-556, 566, 569, 581, 592, 595, 604-605, 615
envergo/nitrates/yaml_admin/tags.py                                           93     10    89%   90, 111, 115, 136, 143, 148, 154, 175-177
envergo/nitrates/yaml_tree/condition.py                                      116      5    96%   168, 210, 229-230, 253
envergo/nitrates/yaml_tree/expression.py                                      49      0   100%
envergo/nitrates/yaml_tree/feuilles.py                                       138      0   100%
envergo/nitrates/yaml_tree/loader.py                                          77      1    99%   29
envergo/nitrates/yaml_tree/loader_db.py                                       51      5    90%   105, 133, 158, 169-170
envergo/nitrates/yaml_tree/parcours.py                                       322      0   100%
envergo/nitrates/yaml_tree/schema.py                                           5      0   100%
envergo/nitrates/yaml_tree/validator.py                                      428     10    98%   125-126, 157, 516-517, 762, 775, 880, 933, 971
envergo/nitrates/zonage_montagne.py                                           52      6    88%   82, 106, 157, 162, 165, 167
envergo/nitrates/zonage_note_5.py                                             28      2    93%   37-38
envergo/nitrates/zonage_zones_est.py                                          42      2    95%   70, 76
--------------------------------------------------------------------------------------------------------
TOTAL                                                                       7594   1963    74%
```
