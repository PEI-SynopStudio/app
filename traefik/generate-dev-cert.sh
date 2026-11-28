#!/bin/sh
# Self-signed certificate for local HTTPS through Traefik (T4.36); the files stay out of git.
# Usage: sh traefik/generate-dev-cert.sh [extra SAN ...], e.g. IP:192.168.1.20 or DNS:pei.example.org
set -eu

# Git Bash on Windows would rewrite "/CN=..." as a Windows path.
export MSYS_NO_PATHCONV=1

dir="$(dirname "$0")/certs"
days="${CERT_DAYS:-365}"
sans="DNS:localhost,DNS:media.localhost,DNS:auth.localhost,IP:127.0.0.1"
for extra in "$@"; do
  sans="$sans,$extra"
done

mkdir -p "$dir"
openssl req -x509 -newkey rsa:2048 -sha256 -nodes -days "$days" \
  -keyout "$dir/local.key" -out "$dir/local.crt" \
  -subj "/CN=SynopStudio local" \
  -addext "subjectAltName=$sans" \
  -addext "extendedKeyUsage=serverAuth"

echo "Wrote $dir/local.crt and $dir/local.key ($sans)"
