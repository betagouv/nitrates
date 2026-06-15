#!/bin/sh
# Régénère couvert_leaves.json : les 113 feuilles couvert du YAML actif,
# avec leur regle_id / contexte / periodes / textes. Source pour
# build_mapping_couvert.py. Nécessite le conteneur Django up (port 8042).
#
# Le `docker exec` simple n'a pas DATABASE_URL : on source /proc/1/environ.
set -e
OUT="$(dirname "$0")/couvert_leaves.json"

docker exec envergo_django_maindev sh -c 'set -a; . /dev/stdin <<EOF
$(tr "\0" "\n" < /proc/1/environ | grep -E "^(DATABASE_URL|DJANGO_|REDIS_URL|CELERY)" | sed "s/\([^=]*\)=\(.*\)/\1=\x27\2\x27/")
EOF
set +a
python manage.py shell -c "
import json
from envergo.nitrates.yaml_tree.feuilles import enumerer_feuilles_couvert_v2, _index_par_id
from envergo.nitrates.yaml_tree.loader_db import load_active_tree
a=load_active_tree(); idx=_index_par_id(a)
out=[]
for f in enumerer_feuilles_couvert_v2(a):
    rid=f[\"regle_id\"]; r=idx.get(rid, {}) if rid else {}
    out.append({
        \"chemin_ids\": f[\"chemin_ids\"], \"regle_id\": rid, \"label\": f[\"label\"],
        \"contexte\": f[\"contexte\"], \"regle_type\": r.get(\"type\"),
        \"regle_texte\": r.get(\"texte\"), \"regle_texte_condition\": r.get(\"texte_condition\"),
        \"regle_message\": r.get(\"message\"), \"regle_periodes\": r.get(\"periodes\"),
    })
print(json.dumps(out, ensure_ascii=False))
" 2>/dev/null' > "$OUT"

echo "écrit $OUT ($(python3 -c "import json;print(len(json.load(open('$OUT'))))") feuilles)"
