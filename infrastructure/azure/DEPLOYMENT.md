# Azure Free Trial — Deployment Guide
# University Services API — Zero to Live

This guide takes you from a brand new Azure free trial account to a
fully deployed, live University Services API. Every command is included.
Expected time: about 45–60 minutes.

---

## Step 0 — Prerequisites on your machine

Install these before you start:

1. Azure CLI: https://docs.microsoft.com/en-us/cli/azure/install-azure-cli
   - Mac:     brew install azure-cli
   - Windows: winget install Microsoft.AzureCLI
   - Verify:  az --version

2. Docker Desktop: https://www.docker.com/products/docker-desktop
   - Needed to build and push your Docker image

3. Git (you likely have this already)

---

## Step 1 — Create Azure free trial account

1. Go to https://azure.microsoft.com/free
2. Click "Start free"
3. Sign in with a Microsoft account (or create one)
4. You get: $200 credit valid for 30 days + 12 months of free services

NOTE: Credit card is required for identity verification.
You will NOT be charged during the free trial unless you manually
upgrade to pay-as-you-go.

---

## Step 2 — Log in via Azure CLI

Open your terminal and run:

    az login

A browser window opens. Sign in with your Azure account.
After login, your terminal shows your subscription details.

Confirm you're on the right subscription:

    az account show

You should see your free trial subscription listed.

---

## Step 3 — Create a Resource Group

A resource group is a container for all related Azure resources.
Think of it as a folder for your project.

    az group create \
      --name university-api-rg \
      --location uaenorth \
      --tags project=university-api environment=production

Use "uaenorth" for UAE North (closest to your university).
Other options: eastus, westeurope, southeastasia

---

## Step 4 — Create Azure Container Registry (ACR)

ACR is your private Docker image registry — like Docker Hub but
hosted in your Azure account.

    az acr create \
      --resource-group university-api-rg \
      --name universityapiregistry \
      --sku Basic

NOTE: The name must be globally unique and lowercase only.
If "universityapiregistry" is taken, try "uniservicesapi2026" or similar.

Get your registry URL (you'll need this later):

    az acr show \
      --name universityapiregistry \
      --query loginServer \
      --output tsv

It will look like: universityapiregistry.azurecr.io
Save this value.

---

## Step 5 — Create Azure Database for PostgreSQL

The free trial includes a small PostgreSQL instance.

    az postgres flexible-server create \
      --resource-group university-api-rg \
      --name university-api-db \
      --location uaenorth \
      --admin-user pgadmin \
      --admin-password "UniversityDB@2026!" \
      --sku-name Standard_B1ms \
      --tier Burstable \
      --storage-size 32 \
      --version 15

This takes about 5 minutes.

Create the database inside the server:

    az postgres flexible-server db create \
      --resource-group university-api-rg \
      --server-name university-api-db \
      --database-name university_db

Allow your Container App to connect (allow Azure services):

    az postgres flexible-server firewall-rule create \
      --resource-group university-api-rg \
      --name university-api-db \
      --rule-name allow-azure-services \
      --start-ip-address 0.0.0.0 \
      --end-ip-address 0.0.0.0

Your DATABASE_URL will be:
    postgresql+asyncpg://pgadmin:UniversityDB@2026!@university-api-db.postgres.database.azure.com:5432/university_db

---

## Step 6 — Create Azure Cache for Redis

    az redis create \
      --resource-group university-api-rg \
      --name university-api-cache \
      --location uaenorth \
      --sku Basic \
      --vm-size C0

This takes about 10–15 minutes. Get the connection string after:

    # Get hostname
    az redis show \
      --name university-api-cache \
      --resource-group university-api-rg \
      --query hostName \
      --output tsv

    # Get access key
    az redis list-keys \
      --name university-api-cache \
      --resource-group university-api-rg \
      --query primaryKey \
      --output tsv

Your REDIS_URL will be:
    rediss://:<your-primary-key>@<hostname>:6380/0
    (note: rediss:// with double-s = TLS, port 6380)

---

## Step 7 — Create Azure OpenAI resource (for library assistant)

NOTE: Azure OpenAI requires manual approval. Request access at:
https://aka.ms/oai/access

If you don't have access yet, skip this step — the rest of the API
works without it. You can add it later.

Once approved:

    az cognitiveservices account create \
      --name university-api-openai \
      --resource-group university-api-rg \
      --kind OpenAI \
      --sku S0 \
      --location eastus

Deploy the models (OpenAI models aren't available in all regions;
use eastus or westeurope):

    # Embedding model
    az cognitiveservices account deployment create \
      --name university-api-openai \
      --resource-group university-api-rg \
      --deployment-name text-embedding-ada-002 \
      --model-name text-embedding-ada-002 \
      --model-version "2" \
      --model-format OpenAI \
      --capacity 10

    # Chat model
    az cognitiveservices account deployment create \
      --name university-api-openai \
      --resource-group university-api-rg \
      --deployment-name gpt-4o \
      --model-name gpt-4o \
      --model-version "2024-05-13" \
      --model-format OpenAI \
      --capacity 10

Get your endpoint and key:

    az cognitiveservices account show \
      --name university-api-openai \
      --resource-group university-api-rg \
      --query properties.endpoint \
      --output tsv

    az cognitiveservices account keys list \
      --name university-api-openai \
      --resource-group university-api-rg \
      --query key1 \
      --output tsv

---

## Step 8 — Build and push your Docker image

Log in to your container registry:

    az acr login --name universityapiregistry

Build and push (run from your project root where Dockerfile is):

    # Build
    docker build -t universityapiregistry.azurecr.io/university-api:latest .

    # Push
    docker push universityapiregistry.azurecr.io/university-api:latest

---

## Step 9 — Create Container Apps Environment and App

Create the environment (shared networking layer):

    az containerapp env create \
      --name university-api-env \
      --resource-group university-api-rg \
      --location uaenorth

Enable the Container Apps extension if needed:

    az extension add --name containerapp --upgrade

Create the Container App with your secrets inline:

    az containerapp create \
      --name university-api \
      --resource-group university-api-rg \
      --environment university-api-env \
      --image universityapiregistry.azurecr.io/university-api:latest \
      --target-port 8000 \
      --ingress external \
      --min-replicas 1 \
      --max-replicas 5 \
      --cpu 0.5 \
      --memory 1.0Gi \
      --registry-server universityapiregistry.azurecr.io \
      --env-vars \
        ENVIRONMENT=production \
        DATABASE_URL="postgresql+asyncpg://pgadmin:UniversityDB@2026!@university-api-db.postgres.database.azure.com:5432/university_db" \
        SECRET_KEY="replace-this-with-32-random-chars-openssl-rand-hex-32" \
        REDIS_URL="rediss://:your-redis-key@your-redis-host:6380/0" \
        AZURE_OPENAI_ENDPOINT="https://your-openai-resource.openai.azure.com/" \
        AZURE_OPENAI_API_KEY="your-openai-api-key"

IMPORTANT: Replace all placeholder values above with your real values.

Generate a proper SECRET_KEY:
    openssl rand -hex 32

Get your app's public URL:

    az containerapp show \
      --name university-api \
      --resource-group university-api-rg \
      --query properties.configuration.ingress.fqdn \
      --output tsv

It will look like: university-api.something.uaenorth.azurecontainerapps.io

---

## Step 10 — Run migrations and seed data

Run migrations against your live database using a one-off job:

    az containerapp job create \
      --name university-api-migrate \
      --resource-group university-api-rg \
      --environment university-api-env \
      --trigger-type Manual \
      --replica-timeout 300 \
      --image universityapiregistry.azurecr.io/university-api:latest \
      --command "alembic" "upgrade" "head" \
      --env-vars DATABASE_URL="your-database-url"

    az containerapp job start \
      --name university-api-migrate \
      --resource-group university-api-rg

Seed with test data (optional — only for testing):

    az containerapp job create \
      --name university-api-seed \
      --resource-group university-api-rg \
      --environment university-api-env \
      --trigger-type Manual \
      --replica-timeout 300 \
      --image universityapiregistry.azurecr.io/university-api:latest \
      --command "python" "scripts/seed.py" \
      --env-vars DATABASE_URL="your-database-url"

    az containerapp job start \
      --name university-api-seed \
      --resource-group university-api-rg

---

## Step 11 — Verify it's working

Replace YOUR_APP_URL with the URL from Step 9:

    # Health check
    curl https://YOUR_APP_URL/health/ready

    # Should return: {"status":"ready","checks":{"database":{"status":"healthy"},...}}

    # Root endpoint
    curl https://YOUR_APP_URL/

    # API docs (only available in non-production, but we set ENVIRONMENT=production)
    # To enable temporarily for testing:
    # Add env var: ENVIRONMENT=development
    # Then visit: https://YOUR_APP_URL/docs

---

## Step 12 — Set up CI/CD (optional but recommended)

Push your code to GitHub, then:

1. Go to your GitHub repo Settings → Secrets and variables → Actions
2. Add these secrets:

    AZURE_CLIENT_ID         → from: az ad sp create-for-rbac output
    AZURE_TENANT_ID         → from: az account show --query tenantId
    AZURE_SUBSCRIPTION_ID   → from: az account show --query id
    ACR_LOGIN_SERVER        → universityapiregistry.azurecr.io
    AZURE_RESOURCE_GROUP    → university-api-rg
    CONTAINER_APP_NAME      → university-api
    DATABASE_URL            → your full connection string
    SECRET_KEY              → your random secret
    REDIS_URL               → your redis connection string

3. Create the service principal:

    az ad sp create-for-rbac \
      --name sp-university-api-github \
      --role Contributor \
      --scopes /subscriptions/YOUR_SUBSCRIPTION_ID/resourceGroups/university-api-rg

4. Push to main branch — the pipeline runs automatically.

---

## Estimated costs on free trial

The $200 free trial credit easily covers 30 days of running this stack:

    PostgreSQL (B1ms)          ~$15/month
    Redis (Basic C0)           ~$16/month
    Container Apps (0.5 CPU)   ~$10/month (with scale-to-zero)
    Container Registry (Basic) ~$5/month
    Azure OpenAI               ~$5-20/month (depends on usage)

Total: roughly $50-65/month — well within the $200 trial credit.

---

## Clean up (when you're done testing)

Delete everything at once by deleting the resource group:

    az group delete --name university-api-rg --yes

This deletes ALL resources in the group and stops all billing.

---

## Troubleshooting

Container App won't start:
    az containerapp logs show \
      --name university-api \
      --resource-group university-api-rg \
      --follow

Database connection refused:
    - Check firewall rule allows Azure services (Step 5)
    - Verify DATABASE_URL format: postgresql+asyncpg:// not postgresql://

Redis connection refused:
    - Use rediss:// (double s) for TLS, port 6380
    - Check the primary key is correct

Image push fails:
    - Run: az acr login --name universityapiregistry
    - Then retry the docker push

Health check returns 503:
    - The database or Redis isn't reachable
    - Check the Container App environment variables are set correctly
    - Check az containerapp logs for the specific error
