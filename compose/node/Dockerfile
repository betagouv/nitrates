FROM docker.io/node:22.13-bookworm-slim

# System binaries used by gulp-imagemin (arm64: npm postinstall download of
# prebuilt amd64 binaries fails under ignore-scripts=true).
RUN apt-get update && apt-get install -y --no-install-recommends \
    optipng gifsicle libjpeg-turbo-progs \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY ./package.json /app
COPY ./package-lock.json /app
COPY ./.npmrc /app

RUN npm ci && npm cache clean --force \
 && mkdir -p node_modules/optipng-bin/vendor node_modules/gifsicle/vendor node_modules/mozjpeg/vendor \
 && ln -s /usr/bin/optipng  node_modules/optipng-bin/vendor/optipng \
 && ln -s /usr/bin/gifsicle node_modules/gifsicle/vendor/gifsicle \
 && ln -s /usr/bin/cjpeg    node_modules/mozjpeg/vendor/cjpeg

ENV PATH ./node_modules/.bin/:$PATH
