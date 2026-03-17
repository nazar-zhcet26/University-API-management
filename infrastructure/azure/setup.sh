#!/bin/bash
# infrastructure/azure/setup.sh
# ─────────────────────────────────────────────────────────────────────────────
# One-time Azure infrastructure setup for University API
#
# Run this ONCE to create all Azure resources.
# After this, the GitHub Actions pipeline handles everything automatically.
#
# Prerequisites:
#   1. Azure CLI installed: https://docs.microsoft.com/en-us/cli/azure/install-azure-cli
#   2. Logged in: az login
#   3. Correct subscription selected: az account set --subscription <id>
#
# What this creates:
#   - Resource Group
#   - Azure Container Registry (ACR) — stores your Docker images
#   - Azure Container Apps Environment — the hosting platform
#   - Azure Container App — your running API
#   - Azure Cache for Redis — production cache
#   - Service Principal — identity for GitHub Actions to deploy
#   - GitHub Secrets setup instructions
#
# Usage:
#   chmod +x infrastructure/azure/setup.sh
#   ./infrastructure/azure/setup.sh
# ─────────────────────────────────────────────────────────────────────────────

set -e  # exit immediately if any command fails

# ── Configuration — edit these before running ─────────────────────────────────
RESOURCE_GROUP="university-api-rg"
LOCATION="uaenorth"              # UAE North — closest to your university
ACR_NAME="universityapiregistry" # must be globally unique, lowercase, no hyphens
CONTAINER_APP_ENV="university-api-env"
CONTAINER_APP_NAME="university-api"
REDIS_NAME="university-api-cache"

# Your GitHub repository (for service principal scope)
GITHUB_REPO="your-org/university-api"  # CHANGE THIS

# ── Colors for output ─────────────────────────────────────────────────────────
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'

log() { echo -e "${BLUE}[$(date +'%H:%M:%S')]${NC} $1"; }
success() { echo -e "${GREEN}✅ $1${NC}"; }
warn() { echo -e "${YELLOW}⚠️  $1${NC}"; }

# ── Step 1: Resource Group ─────────────────────────────────────────────────────
log "Creating resource group: $RESOURCE_GROUP in $LOCATION"
az group create \
  --name "$RESOURCE_GROUP" \
  --location "$LOCATION" \
  --tags project=university-api environment=production
success "Resource group created"

# ── Step 2: Azure Container Registry ──────────────────────────────────────────
# ACR stores your Docker images — like Docker Hub but private and in Azure
log "Creating Azure Container Registry: $ACR_NAME"
az acr create \
  --resource-group "$RESOURCE_GROUP" \
  --name "$ACR_NAME" \
  --sku Basic \
  --admin-enabled false  # use service principal auth, not admin password

ACR_LOGIN_SERVER=$(az acr show --name "$ACR_NAME" --query "loginServer" --output tsv)
ACR_ID=$(az acr show --name "$ACR_NAME" --query "id" --output tsv)
success "Container Registry created: $ACR_LOGIN_SERVER"

# ── Step 3: Azure Cache for Redis ──────────────────────────────────────────────
log "Creating Azure Cache for Redis: $REDIS_NAME"
log "This takes 5-10 minutes..."
az redis create \
  --resource-group "$RESOURCE_GROUP" \
  --name "$REDIS_NAME" \
  --location "$LOCATION" \
  --sku Basic \
  --vm-size C0  # smallest tier — upgrade for production scale

REDIS_HOST=$(az redis show --name "$REDIS_NAME" --resource-group "$RESOURCE_GROUP" \
  --query "hostName" --output tsv)
REDIS_KEY=$(az redis list-keys --name "$REDIS_NAME" --resource-group "$RESOURCE_GROUP" \
  --query "primaryKey" --output tsv)
REDIS_URL="rediss://:${REDIS_KEY}@${REDIS_HOST}:6380/0"  # rediss:// = TLS
success "Redis created: $REDIS_HOST"

# ── Step 4: Container Apps Environment ────────────────────────────────────────
# The environment is the shared networking/monitoring layer for Container Apps
# Multiple apps can share one environment (APIM, API, background workers)
log "Creating Container Apps Environment: $CONTAINER_APP_ENV"
az containerapp env create \
  --name "$CONTAINER_APP_ENV" \
  --resource-group "$RESOURCE_GROUP" \
  --location "$LOCATION"
success "Container Apps Environment created"

# ── Step 5: Initial Container App Deployment ──────────────────────────────────
# Deploy a placeholder image first — the pipeline will replace it
log "Creating Container App: $CONTAINER_APP_NAME"
az containerapp create \
  --name "$CONTAINER_APP_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --environment "$CONTAINER_APP_ENV" \
  --image "mcr.microsoft.com/azuredocs/containerapps-helloworld:latest" \
  --target-port 8000 \
  --ingress external \
  --min-replicas 1 \
  --max-replicas 10 \
  --cpu 0.5 \
  --memory 1.0Gi \
  --registry-server "$ACR_LOGIN_SERVER"

APP_URL=$(az containerapp show \
  --name "$CONTAINER_APP_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --query "properties.configuration.ingress.fqdn" \
  --output tsv)
success "Container App created: https://$APP_URL"

# ── Step 6: Configure Scaling Rules ───────────────────────────────────────────
# Scale based on HTTP traffic — handles registration week spikes automatically
log "Configuring auto-scaling rules"
az containerapp update \
  --name "$CONTAINER_APP_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --scale-rule-name http-scaling \
  --scale-rule-type http \
  --scale-rule-http-concurrency 50  # scale up when >50 concurrent requests per replica
success "Scaling configured: 1-10 replicas, trigger at 50 concurrent requests"

# ── Step 7: Service Principal for GitHub Actions ──────────────────────────────
# Create an identity for GitHub to authenticate with Azure
# This is a non-human account with only the permissions it needs
log "Creating service principal for GitHub Actions"
SP_NAME="sp-university-api-github"

SP_JSON=$(az ad sp create-for-rbac \
  --name "$SP_NAME" \
  --role Contributor \
  --scopes "/subscriptions/$(az account show --query id -o tsv)/resourceGroups/$RESOURCE_GROUP" \
  --json-auth)

# Extract individual values
CLIENT_ID=$(echo $SP_JSON | python3 -c "import sys, json; print(json.load(sys.stdin)['clientId'])")
TENANT_ID=$(echo $SP_JSON | python3 -c "import sys, json; print(json.load(sys.stdin)['tenantId'])")
SUBSCRIPTION_ID=$(az account show --query id -o tsv)

# Grant ACR push permissions — service principal can push Docker images
az role assignment create \
  --assignee "$CLIENT_ID" \
  --role AcrPush \
  --scope "$ACR_ID"

success "Service principal created: $SP_NAME"

# ── Step 8: Configure Secrets in Container App ────────────────────────────────
# Store sensitive values in Container Apps secrets
# They're referenced as secretref: in the workflow instead of plain text
log "Configuring Container App secrets"
warn "You need to set DATABASE_URL and SECRET_KEY manually"
warn "Run these commands after setting up your PostgreSQL database:"
echo ""
echo "  az containerapp secret set \\"
echo "    --name $CONTAINER_APP_NAME \\"
echo "    --resource-group $RESOURCE_GROUP \\"
echo "    --secrets \\"
echo "      database-url=postgresql+asyncpg://USER:PASS@HOST:5432/university_db \\"
echo "      secret-key=YOUR-RANDOM-32-CHAR-SECRET-KEY \\"
echo "      redis-url=$REDIS_URL"
echo ""

# ── Step 9: Print GitHub Secrets Setup ────────────────────────────────────────
echo ""
echo "═══════════════════════════════════════════════════════════"
echo "  GitHub Secrets — add these in your repo settings"
echo "  Settings → Secrets and variables → Actions → New secret"
echo "═══════════════════════════════════════════════════════════"
echo ""
echo "  AZURE_CLIENT_ID         = $CLIENT_ID"
echo "  AZURE_TENANT_ID         = $TENANT_ID"
echo "  AZURE_SUBSCRIPTION_ID   = $SUBSCRIPTION_ID"
echo "  ACR_LOGIN_SERVER        = $ACR_LOGIN_SERVER"
echo "  AZURE_RESOURCE_GROUP    = $RESOURCE_GROUP"
echo "  CONTAINER_APP_NAME      = $CONTAINER_APP_NAME"
echo "  DATABASE_URL            = <your postgresql connection string>"
echo "  SECRET_KEY              = <generate with: openssl rand -hex 32>"
echo "  REDIS_URL               = $REDIS_URL"
echo ""
echo "═══════════════════════════════════════════════════════════"
echo ""

# ── Step 10: Configure OIDC for GitHub Actions ────────────────────────────────
# OIDC = OpenID Connect — GitHub gets short-lived tokens from Azure AD
# More secure than storing long-lived client secrets as GitHub secrets
log "Configuring OIDC for GitHub Actions (no long-lived secrets needed)"
az ad app federated-credential create \
  --id "$CLIENT_ID" \
  --parameters "{
    \"name\": \"github-main-branch\",
    \"issuer\": \"https://token.actions.githubusercontent.com\",
    \"subject\": \"repo:${GITHUB_REPO}:ref:refs/heads/main\",
    \"audiences\": [\"api://AzureADTokenExchange\"],
    \"description\": \"GitHub Actions OIDC for main branch deployments\"
  }"
success "OIDC configured — GitHub Actions can authenticate without stored secrets"

echo ""
success "Azure infrastructure setup complete!"
echo ""
echo "Next steps:"
echo "  1. Add the GitHub secrets listed above to your repository"
echo "  2. Set up your PostgreSQL database (Azure Database for PostgreSQL or Supabase)"
echo "  3. Run the secret set command above with your real DATABASE_URL and SECRET_KEY"
echo "  4. Push to main branch — the pipeline will deploy automatically"
echo ""
echo "Your API will be live at: https://$APP_URL"
