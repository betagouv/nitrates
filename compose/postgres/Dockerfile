# REVERT_AT_MERGE_TIME_FOR_UPSTREAM_ENVERGO : Django 5.2 exige PostgreSQL 14+.
# Aligne sur dev/staging/prod Scalingo (PostgreSQL 17, PostGIS 3.6) (refs #647).
# Image officielle publiée en amd64 seulement : émulée sur Mac ARM, comme la 13.
FROM --platform=linux/amd64 postgis/postgis:17-3.5

COPY ./compose/postgres/maintenance /usr/local/bin/maintenance
RUN chmod +x /usr/local/bin/maintenance/*
RUN mv /usr/local/bin/maintenance/* /usr/local/bin \
    && rmdir /usr/local/bin/maintenance
