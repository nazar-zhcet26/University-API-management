# API Versioning & Deprecation Policy
# University Services API — IT Department

## Versioning Strategy

We use **URI versioning** (`/v1/`, `/v2/`) for all API endpoints.

### Why URI Versioning
- Visible and explicit — consumers know exactly which version they're calling
- Simple to route in Azure APIM — different versions point to different backends
- Easy to test directly in a browser or curl
- Industry standard for enterprise APIs

### Version Format
- Major versions only: `v1`, `v2`, `v3`
- Minor/patch changes (backwards-compatible) do NOT get a new version
- Breaking changes always require a new major version

### What Counts as a Breaking Change
These changes REQUIRE a new version:

| Change | Breaking? |
|--------|-----------|
| Removing a field from a response | ✅ YES |
| Renaming a field | ✅ YES |
| Changing a field's data type | ✅ YES |
| Changing a required field to different format | ✅ YES |
| Removing an endpoint | ✅ YES |
| Changing HTTP method for an endpoint | ✅ YES |
| Adding a new required request field | ✅ YES |

These changes do NOT require a new version:

| Change | Breaking? |
|--------|-----------|
| Adding a new optional field to a response | ❌ NO |
| Adding a new endpoint | ❌ NO |
| Adding a new optional query parameter | ❌ NO |
| Performance improvements | ❌ NO |
| Bug fixes that don't change the contract | ❌ NO |

## Azure APIM Routing

Each API version is a separate API definition in APIM.
Both versions run simultaneously until v1 is retired.

```
Consumer calls: https://university-apim.azure-api.net/v1/students
APIM routes to:  https://api-backend-v1.university.ac.ae/v1/students

Consumer calls: https://university-apim.azure-api.net/v2/students
APIM routes to:  https://api-backend-v2.university.ac.ae/v2/students
```

The backend URL can be different — you can run v1 and v2 on separate
deployments, or the same deployment can handle both (if the code
supports both versions internally).

## Deprecation Process

When a new major version is released, the old version enters deprecation.

### Timeline
- **Announcement**: Minimum 6 months notice before retirement
- **Deprecation period**: Old version continues working but shows deprecation headers
- **Retirement**: Old version is disabled in APIM

### Deprecation Headers
Once a version is deprecated, every response includes:

```http
Deprecation: true
Sunset: Sat, 31 Dec 2026 23:59:59 GMT
Link: <https://developer.university.ac.ae/migration/v1-to-v2>; rel="successor-version"
```

Consumers' monitoring tools will detect these headers and alert their teams.

### Communication Channels
1. Email to all registered subscribers via APIM developer portal
2. Banner on developer portal
3. Entry in API changelog
4. Direct notification to high-traffic consumers

### APIM Deprecation Policy (applied at retirement)
```xml
<inbound>
  <choose>
    <when condition="@(context.Api.Version == 'v1')">
      <return-response>
        <set-status code="410" reason="Gone" />
        <set-body>{
  "error": {
    "code": "API_VERSION_RETIRED",
    "message": "API v1 has been retired. Please migrate to v2.",
    "migration_guide": "https://developer.university.ac.ae/migration/v1-to-v2"
  }
}</set-body>
      </return-response>
    </when>
  </choose>
</inbound>
```

## Developer Portal

All API consumers interact with the developer portal at:
`https://university-apim.developer.azure-api.net`

The portal provides:
- Interactive API documentation (rendered from our OpenAPI spec)
- Subscription management (request access to products)
- API key management (view and rotate subscription keys)
- Usage analytics (consumers can see their own usage)
- Changelog and announcements

## Adding a New API Consumer (Process)

1. Consumer registers on the developer portal
2. Consumer requests access to the appropriate product
   - Student Portal, Faculty Dashboard, Admin, or Partner Read-Only
3. For auto-approved products: access granted immediately
4. For manual-approval products (Admin, Partner): IT team reviews and approves
5. Consumer receives subscription key via developer portal
6. Consumer includes key in all requests: `Ocp-Apim-Subscription-Key: <key>`

## Monitoring & Alerts

Azure APIM + Application Insights provides:
- Request volume per API, per operation, per product
- Error rate and latency percentiles (p50, p95, p99)
- Consumer breakdown — which subscription is generating which traffic
- Geographic distribution of requests
- Failed request analysis with full request/response logging

Alerts configured for:
- Error rate > 5% for any product over 5 minutes → PagerDuty
- p95 latency > 2000ms → Slack notification
- Rate limit hits > 100/hour for any subscription → Review consumer usage
