#!/bin/bash
# This script is ran by scalingo at the end of the build process

# Interrupt script on error
set -e

# BLAS/LAPACK installes via Aptfile sont dans des sous-dossiers blas/ et
# lapack/ que l'apt-buildpack n'ajoute pas a LD_LIBRARY_PATH. Pendant le
# build, le prefixe .apt est /build/<id>/.apt (pas /app/.apt), on derive
# donc dynamiquement depuis le LD_LIBRARY_PATH deja set par le buildpack.
# Cf. https://doc.scalingo.com/platform/app/app-with-gdal
APT_LIB_DIR=$(echo "${LD_LIBRARY_PATH:-}" | tr ':' '\n' | grep -m1 '\.apt/usr/lib/x86_64-linux-gnu$' || true)
if [ -n "$APT_LIB_DIR" ]; then
  export LD_LIBRARY_PATH="${APT_LIB_DIR}/blas:${APT_LIB_DIR}/lapack:${LD_LIBRARY_PATH}"
  APT_ROOT="${APT_LIB_DIR%/usr/lib/x86_64-linux-gnu}"
  export PROJ_LIB="${APT_ROOT}/usr/share/proj"
fi

compress_enabled() {
python << END
import sys

from environ import Env

env = Env(COMPRESS_ENABLED=(bool, True))
if env('COMPRESS_ENABLED'):
    sys.exit(0)
else:
    sys.exit(1)

END
}

echo ">>> Starting the post_compile hook"

echo ">>> Installing npm dev dependencies for assets generation."
npm ci --dev

# This is required because we disabled all npm scripts in .npmrc
node node_modules/optipng-bin/lib/install.js
npm run build

echo ">>> Uninstall dev dependencies to prevent bloating /staticfiles"
npm prune --production

echo ">>> Build assets"

if compress_enabled
then
  python manage.py compress --force
fi

# not using collectstatic --clear because it takes ages
rm staticfiles -Rf
python manage.py collectstatic --noinput

python manage.py compilemessages -l fr -i .scalingo -i .venv

echo ">>> Leaving the post_compile hook"
