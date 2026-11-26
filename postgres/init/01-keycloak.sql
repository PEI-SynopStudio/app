-- Creates the Keycloak database on the first start of the postgres volume.
-- Source: postgres image docker-entrypoint-initdb.d.
CREATE DATABASE keycloak;