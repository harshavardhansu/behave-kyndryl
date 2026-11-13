#!/usr/bin/env bash
# Connect GitHub Actions to Azure without any password: an app registration with a federated
# credential that trusts only pushes to `main` of this repository, and roles limited to the
# container registry and the container app. Then the IDs (not secrets) are set as GitHub variables.
#
#   az login && gh auth login
#   ./deploy/azure/github-oidc.sh
set -euo pipefail
export PYTHONWARNINGS=ignore AZURE_CORE_ONLY_SHOW_ERRORS=true
cd "$(dirname "$0")/../.."

RG="${RG:-ODL-KYNDR-2444103}"
APP="${APP:-behave-kyndryl}"
REPO="${REPO:-$(gh repo view --json nameWithOwner -q .nameWithOwner)}"
SUB="$(az account show --query id -o tsv)"
TENANT="$(az account show --query tenantId -o tsv)"
SUFFIX="$(printf '%s' "$SUB$RG" | shasum | cut -c1-6)"
ACR="acrbehave$SUFFIX"
NAME="behave-kyndryl-deploy"

retry() { local n=0; until "$@"; do n=$((n + 1)); [ "$n" -ge 12 ] && return 1; sleep 10; done; }

CLIENT_ID="$(az ad app list --display-name "$NAME" --query '[0].appId' -o tsv)"
if [ -z "$CLIENT_ID" ]; then
  CLIENT_ID="$(az ad app create --display-name "$NAME" --sign-in-audience AzureADMyOrg --query appId -o tsv)"
fi
az ad sp show --id "$CLIENT_ID" -o none 2>/dev/null || retry az ad sp create --id "$CLIENT_ID" -o none
PRINCIPAL="$(az ad sp show --id "$CLIENT_ID" --query id -o tsv)"

SUBJECT="repo:$REPO:ref:refs/heads/main"
if [ -z "$(az ad app federated-credential list --id "$CLIENT_ID" --query "[?subject=='$SUBJECT'].name | [0]" -o tsv)" ]; then
  az ad app federated-credential create --id "$CLIENT_ID" -o none --parameters "{
    \"name\": \"github-main\", \"issuer\": \"https://token.actions.githubusercontent.com\",
    \"subject\": \"$SUBJECT\", \"audiences\": [\"api://AzureADTokenExchange\"] }"
fi

for scope in "$(az acr show -n "$ACR" --query id -o tsv)" "$(az containerapp show -g "$RG" -n "$APP" --query id -o tsv)"; do
  if [ -z "$(az role assignment list --assignee "$PRINCIPAL" --role Contributor --scope "$scope" --query '[0].id' -o tsv)" ]; then
    retry az role assignment create --assignee-object-id "$PRINCIPAL" --assignee-principal-type ServicePrincipal --role Contributor --scope "$scope" -o none
  fi
done

gh variable set AZURE_CLIENT_ID --repo "$REPO" --body "$CLIENT_ID"
gh variable set AZURE_TENANT_ID --repo "$REPO" --body "$TENANT"
gh variable set AZURE_SUBSCRIPTION_ID --repo "$REPO" --body "$SUB"
gh variable set ACR_NAME --repo "$REPO" --body "$ACR"
gh variable set RESOURCE_GROUP --repo "$REPO" --body "$RG"
gh variable set CONTAINER_APP --repo "$REPO" --body "$APP"
echo "GitHub Actions in $REPO can now deploy to $APP (pushes to main only)."
