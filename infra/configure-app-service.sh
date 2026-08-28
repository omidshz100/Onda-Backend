#!/usr/bin/env bash
set -euo pipefail

if (( $# != 4 )); then
  echo "Usage: $0 <resource-group> <app-name> <key-vault-name> <jitsi-url>" >&2
  exit 2
fi

resource_group=$1
app_name=$2
vault_name=$3
jitsi_url=$4

default_hostname=$(az webapp show \
  --resource-group "$resource_group" \
  --name "$app_name" \
  --query defaultHostName \
  --output tsv)

principal_id=$(az webapp identity assign \
  --resource-group "$resource_group" \
  --name "$app_name" \
  --query principalId \
  --output tsv)

vault_id=$(az keyvault show \
  --resource-group "$resource_group" \
  --name "$vault_name" \
  --query id \
  --output tsv)

az role assignment create \
  --assignee-object-id "$principal_id" \
  --assignee-principal-type ServicePrincipal \
  --role "Key Vault Secrets User" \
  --scope "$vault_id" >/dev/null

az webapp config appsettings set \
  --resource-group "$resource_group" \
  --name "$app_name" \
  --settings \
    ONDA_ENVIRONMENT=production \
    ONDA_DATABASE_URL="@Microsoft.KeyVault(VaultName=${vault_name};SecretName=onda-database-url)" \
    ONDA_API_JWT_SECRET="@Microsoft.KeyVault(VaultName=${vault_name};SecretName=onda-api-jwt-secret)" \
    ONDA_JITSI_APP_ID=onda \
    ONDA_JITSI_APP_SECRET="@Microsoft.KeyVault(VaultName=${vault_name};SecretName=onda-jitsi-jwt-secret)" \
    ONDA_JITSI_BASE_URL="$jitsi_url" \
    ONDA_ALLOWED_HOSTS="[\"${default_hostname}\"]" \
    SCM_DO_BUILD_DURING_DEPLOYMENT=true >/dev/null

az webapp config set \
  --resource-group "$resource_group" \
  --name "$app_name" \
  --startup-file "python -m alembic upgrade head && python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips='*'" >/dev/null

echo "Configured ${app_name}. No application code was uploaded by this script."
