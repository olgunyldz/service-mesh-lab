#!/usr/bin/env bash
# Tüm ortamı sıfırdan kurar
set -euo pipefail
D="$(dirname "$0")"

bash "$D/00-check-prereqs.sh"
bash "$D/01-create-clusters.sh"
bash "$D/02-install-metallb.sh"
bash "$D/03-generate-certs.sh"
bash "$D/04-install-istio.sh"
bash "$D/05-install-gateways.sh"
bash "$D/06-deploy-manifests.sh"
bash "$D/07-verify.sh"
