#!/usr/bin/env bash
# Connect GitHub Actions to Azure without any password: an app registration with a federated
# credential that trusts only this repository's "production" environment (deployable from `main`
# only), and roles limited to the
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

# The deploy job runs in the GitHub environment "production", which only `main` may deploy to.
# GitHub names the job either "repo:<owner>/<repo>:environment:production" or, for newer repositories,
# "repo:<owner>@<owner-id>/<repo>@<repo-id>:environment:production"; trust both, nothing else.
OWNER_ID="$(gh api "repos/$REPO" -q .owner.id)"; REPO_ID="$(gh api "repos/$REPO" -q .id)"
gh api -X PUT "repos/$REPO/environments/production" --input - >/dev/null <<JSON
{"deployment_branch_policy": {"protected_branches": false, "custom_branch_policies": true}}
JSON
if ! gh api "repos/$REPO/environments/production/deployment-branch-policies" -q '.branch_policies[].name' | grep -qx main; then
  gh api -X POST "repos/$REPO/environments/production/deployment-branch-policies" -f name=main -f type=branch >/dev/null
fi
add_subject() {
  if [ -z "$(az ad app federated-credential list --id "$CLIENT_ID" --query "[?subject=='$2'].name | [0]" -o tsv)" ]; then
    az ad app federated-credential create --id "$CLIENT_ID" -o none --parameters "{
      \"name\": \"$1\", \"issuer\": \"https://token.actions.githubusercontent.com\",
      \"subject\": \"$2\", \"audiences\": [\"api://AzureADTokenExchange\"] }"
  fi
}
add_subject github-production "repo:$REPO:environment:production"
add_subject github-production-ids "repo:${REPO%%/*}@$OWNER_ID/${REPO##*/}@$REPO_ID:environment:production"
# Remove the earlier branch-based credential (the deploy job never presents it).
OLD="$(az ad app federated-credential list --id "$CLIENT_ID" --query "[?name=='github-main'].id | [0]" -o tsv)"
[ -z "$OLD" ] || az ad app federated-credential delete --id "$CLIENT_ID" --federated-credential-id "$OLD" -o none

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
