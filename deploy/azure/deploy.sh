#!/usr/bin/env bash
# Deploy Behave Kyndryl to Azure: Container Apps (1 replica) + SQLite on Azure Files + managed identity
# + Entra sign-in in front. Safe to run again: existing resources are kept and updated.
#
#   az login            # an account with Owner (or Contributor + User Access Administrator) on the subscription
#   ./deploy/azure/deploy.sh
#
# Secrets are never printed: the storage key goes straight to the Container Apps environment and the
# sign-in secret is stored only as a Container Apps secret. Non-secret settings come from .env.
# Azure AI Foundry is reached with the app's managed identity: no key at all.
set -euo pipefail
export PYTHONWARNINGS=ignore AZURE_CORE_ONLY_SHOW_ERRORS=true

cd "$(dirname "$0")/../.."
env_value() { grep -E "^$1=" .env 2>/dev/null | tail -1 | cut -d= -f2- | tr -d '"'"'"; }

RG="${RG:-ODL-KYNDR-2444103}"
LOCATION="${LOCATION:-westus3}"  # next to the Foundry resource
APP="${APP:-behave-kyndryl}"
TAG="${TAG:-$(git rev-parse --short HEAD)-$(date +%Y%m%d%H%M)}"
SUB="$(az account show --query id -o tsv)"
TENANT="$(az account show --query tenantId -o tsv)"
SUFFIX="$(printf '%s' "$SUB$RG" | shasum | cut -c1-6)"
LAW="log-behave-$SUFFIX"; ACR="acrbehave$SUFFIX"; STORAGE="stbehave$SUFFIX"; SHARE="behave-data"
IDENTITY="id-behave-app"; ENVIRONMENT="cae-behave"; WEB_APP_REG="behave-kyndryl-web"
PROJECT_ENDPOINT="${AZURE_AI_PROJECT_ENDPOINT:-$(env_value AZURE_AI_PROJECT_ENDPOINT)}"
MODEL="${AZURE_AI_MODEL_DEPLOYMENT:-$(env_value AZURE_AI_MODEL_DEPLOYMENT)}"
FOUNDRY_ACCOUNT="$(printf '%s' "$PROJECT_ENDPOINT" | sed -E 's#https://([^.]+)\..*#\1#')"

step() { printf '\n==> %s\n' "$*"; }
retry() { local n=0; until "$@"; do n=$((n + 1)); [ "$n" -ge 12 ] && return 1; sleep 10; done; }
assign() { # assign ROLE to PRINCIPAL on SCOPE (idempotent, waits for the principal to replicate)
  local principal="$1" role="$2" scope="$3" type="${4:-ServicePrincipal}"
  if [ -z "$(az role assignment list --assignee "$principal" --role "$role" --scope "$scope" --query '[0].id' -o tsv)" ]; then
    retry az role assignment create --assignee-object-id "$principal" --assignee-principal-type "$type" --role "$role" --scope "$scope" -o none
  fi
}

[ -n "$PROJECT_ENDPOINT" ] && [ -n "$MODEL" ] || { echo "Set AZURE_AI_PROJECT_ENDPOINT and AZURE_AI_MODEL_DEPLOYMENT in .env first." >&2; exit 1; }
echo "Subscription $SUB | resource group $RG | region $LOCATION | image tag $TAG"

step "Resource providers"
for provider in Microsoft.App Microsoft.ContainerRegistry Microsoft.DBforPostgreSQL Microsoft.KeyVault Microsoft.OperationalInsights Microsoft.ManagedIdentity; do
  az provider register -n "$provider" --wait -o none
done

step "Log Analytics workspace $LAW"
az monitor log-analytics workspace show -g "$RG" -n "$LAW" -o none 2>/dev/null ||
  az monitor log-analytics workspace create -g "$RG" -n "$LAW" -l "$LOCATION" --retention-time 30 -o none
LAW_ID="$(az monitor log-analytics workspace show -g "$RG" -n "$LAW" --query customerId -o tsv)"
LAW_KEY="$(az monitor log-analytics workspace get-shared-keys -g "$RG" -n "$LAW" --query primarySharedKey -o tsv)"

step "Container registry $ACR"
az acr show -n "$ACR" -o none 2>/dev/null || az acr create -g "$RG" -n "$ACR" -l "$LOCATION" --sku Basic --admin-enabled false -o none
ACR_ID="$(az acr show -n "$ACR" --query id -o tsv)"

step "Managed identity $IDENTITY"
az identity show -g "$RG" -n "$IDENTITY" -o none 2>/dev/null || az identity create -g "$RG" -n "$IDENTITY" -l "$LOCATION" -o none
IDENTITY_ID="$(az identity show -g "$RG" -n "$IDENTITY" --query id -o tsv)"
IDENTITY_PRINCIPAL="$(az identity show -g "$RG" -n "$IDENTITY" --query principalId -o tsv)"
IDENTITY_CLIENT="$(az identity show -g "$RG" -n "$IDENTITY" --query clientId -o tsv)"

step "Storage for the workspace database ($STORAGE/$SHARE)"
# The lab subscription cannot create PostgreSQL B1ms, so the workspace uses SQLite on an Azure file share:
# data survives restarts and redeploys; one replica only (the mission engine already requires that).
az storage account show -g "$RG" -n "$STORAGE" -o none 2>/dev/null ||
  az storage account create -g "$RG" -n "$STORAGE" -l "$LOCATION" --sku Standard_LRS --kind StorageV2 \
    --min-tls-version TLS1_2 --allow-blob-public-access false -o none
STORAGE_KEY="$(az storage account keys list -g "$RG" -n "$STORAGE" --query '[0].value' -o tsv)"
az storage share-rm show -g "$RG" --storage-account "$STORAGE" -n "$SHARE" -o none 2>/dev/null ||
  az storage share-rm create -g "$RG" --storage-account "$STORAGE" -n "$SHARE" --quota 5 -o none

step "Access: registry pull and Azure AI Foundry"
assign "$IDENTITY_PRINCIPAL" AcrPull "$ACR_ID"
FOUNDRY_ID="$(az cognitiveservices account list --query "[?name=='$FOUNDRY_ACCOUNT'].id | [0]" -o tsv)"
[ -n "$FOUNDRY_ID" ] || { echo "Foundry resource $FOUNDRY_ACCOUNT not found in this subscription." >&2; exit 1; }
assign "$IDENTITY_PRINCIPAL" 53ca6127-db72-4b80-b1b0-d745d6d5456d "$FOUNDRY_ID"  # "Azure AI User" (now shown as "Foundry User")

step "Build the image in Azure ($ACR/$APP:$TAG)"
mkdir -p data
az acr build -r "$ACR" -t "$APP:$TAG" -t "$APP:latest" -f deploy/app.Containerfile . > data/acr-build.log 2>&1 ||
  { echo "Image build failed; see data/acr-build.log" >&2; tail -40 data/acr-build.log >&2; exit 1; }
IMAGE="$ACR.azurecr.io/$APP:$TAG"

step "Container Apps environment $ENVIRONMENT"
az containerapp env show -g "$RG" -n "$ENVIRONMENT" -o none 2>/dev/null ||
  az containerapp env create -g "$RG" -n "$ENVIRONMENT" -l "$LOCATION" --logs-workspace-id "$LAW_ID" --logs-workspace-key "$LAW_KEY" -o none
az containerapp env storage set -g "$RG" -n "$ENVIRONMENT" --storage-name "$SHARE" --azure-file-account-name "$STORAGE" \
  --azure-file-account-key "$STORAGE_KEY" --azure-file-share-name "$SHARE" --access-mode ReadWrite -o none
unset STORAGE_KEY
ENV_ID="$(az containerapp env show -g "$RG" -n "$ENVIRONMENT" --query id -o tsv)"

step "Container app $APP"
FQDN="$(az containerapp show -g "$RG" -n "$APP" --query properties.configuration.ingress.fqdn -o tsv 2>/dev/null || true)"
SPEC="$(mktemp)"
python3 - "$SPEC" <<PY
import json, sys
env = {
    "AGENTICA_MODE": "demo", "DATABASE_URL": "sqlite:////mnt/data/behave.db",
    "AGENTICA_SECURE_COOKIES": "true", "AGENTICA_FOUNDRY_AUTO_SYNC": "true",
    "AZURE_AI_PROJECT_ENDPOINT": "$PROJECT_ENDPOINT", "AZURE_AI_MODEL_DEPLOYMENT": "$MODEL",
    "AZURE_TENANT_ID": "$TENANT", "AZURE_CLIENT_ID": "$IDENTITY_CLIENT",
    "AGENTICA_AI_ALLOWED_CLASSIFICATIONS": '["Internal"]', "AGENTICA_AI_DAILY_CALL_LIMIT": "${DAILY_CALL_LIMIT:-120}",
    "AGENTICA_DEMO_STEP_SECONDS": "1.2", "AGENTICA_ALLOWED_ORIGINS": "https://$FQDN" if "$FQDN" else "",
    "AGENTICA_DEMO_HOSTS": "$FQDN", "AGENTICA_REQUIRE_PLATFORM_AUTH": "true",
}
health = {"httpGet": {"path": "/api/v1/health", "port": 8000}, "initialDelaySeconds": 10, "periodSeconds": 15}
spec = {
    "location": "$LOCATION",
    "identity": {"type": "UserAssigned", "userAssignedIdentities": {"$IDENTITY_ID": {}}},
    "properties": {
        "managedEnvironmentId": "$ENV_ID",
        "configuration": {
            "activeRevisionsMode": "Single",
            "ingress": {"external": True, "targetPort": 8000, "transport": "auto", "allowInsecure": False},
            "registries": [{"server": "$ACR.azurecr.io", "identity": "$IDENTITY_ID"}],
        },
        "template": {
            "containers": [{
                "name": "$APP", "image": "$IMAGE", "resources": {"cpu": 1.0, "memory": "2Gi"},
                "env": [{"name": k, "value": v} for k, v in env.items() if v],
                "volumeMounts": [{"volumeName": "data", "mountPath": "/mnt/data"}],
                "probes": [{"type": "Liveness", **health}, {"type": "Readiness", **health}],
            }],
            "scale": {"minReplicas": 1, "maxReplicas": 1},
            "volumes": [{"name": "data", "storageType": "AzureFile", "storageName": "$SHARE",
                         "mountOptions": "uid=10001,gid=10001,dir_mode=0750,file_mode=0640,nobrl,mfsymlinks,cache=strict"}],
        },
    },
}
json.dump(spec, open(sys.argv[1], "w"), indent=1)
PY
if az containerapp show -g "$RG" -n "$APP" -o none 2>/dev/null; then
  az containerapp update -g "$RG" -n "$APP" --yaml "$SPEC" -o none
else
  retry az containerapp create -g "$RG" -n "$APP" --yaml "$SPEC" -o none
  FQDN="$(az containerapp show -g "$RG" -n "$APP" --query properties.configuration.ingress.fqdn -o tsv)"
  az containerapp update -g "$RG" -n "$APP" --set-env-vars "AGENTICA_ALLOWED_ORIGINS=https://$FQDN" "AGENTICA_DEMO_HOSTS=$FQDN" -o none
fi
rm -f "$SPEC"

step "Entra sign-in in front of the site ($WEB_APP_REG)"
WEB_APP_ID="$(az ad app list --display-name "$WEB_APP_REG" --query '[0].appId' -o tsv)"
if [ -z "$WEB_APP_ID" ]; then
  WEB_APP_ID="$(az ad app create --display-name "$WEB_APP_REG" --sign-in-audience AzureADMyOrg \
    --web-redirect-uris "https://$FQDN/.auth/login/aad/callback" --enable-id-token-issuance true --query appId -o tsv)"
  retry az ad sp create --id "$WEB_APP_ID" -o none
else
  az ad app update --id "$WEB_APP_ID" --web-redirect-uris "https://$FQDN/.auth/login/aad/callback" -o none
fi
if [ "$(az containerapp auth show -g "$RG" -n "$APP" --query 'platform.enabled' -o tsv 2>/dev/null)" != "true" ]; then
  SIGNIN_SECRET="$(az ad app credential reset --id "$WEB_APP_ID" --append --display-name container-app-sign-in --years 1 --query password -o tsv)"
  az containerapp auth microsoft update -g "$RG" -n "$APP" --client-id "$WEB_APP_ID" --client-secret "$SIGNIN_SECRET" \
    --tenant-id "$TENANT" --yes -o none
  unset SIGNIN_SECRET
fi
az containerapp auth update -g "$RG" -n "$APP" --enabled true --unauthenticated-client-action RedirectToLoginPage \
  --redirect-provider AzureActiveDirectory --excluded-paths "/api/v1/health" -o none

step "Waiting for the app to report healthy"
for _ in $(seq 1 30); do
  if curl -fsS "https://$FQDN/api/v1/health" >/dev/null 2>&1; then echo "Healthy."; HEALTHY=1; break; fi
  sleep 10
done
[ "${HEALTHY:-}" = 1 ] || { echo "The app did not report healthy. Check: az containerapp logs show -g $RG -n $APP" >&2; exit 1; }
echo
echo "Site:   https://$FQDN   (sign in with an account from tenant $TENANT)"
echo "Health: https://$FQDN/api/v1/health"
echo "Logs:   az containerapp logs show -g $RG -n $APP --follow"
