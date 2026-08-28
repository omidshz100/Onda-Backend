# Azure infrastructure

These files extend the existing `onda-dev-rg` resource group and the existing
`onda-api-omid-2026` Linux App Service. They do not create a second backend app.
The student subscription currently permits Poland Central and exposes a small burstable VM there,
so the stateful/Jitsi resources use that region while the existing App Service remains in France.

The Bicep deployment provisions:

- PostgreSQL Flexible Server 16 (Burstable B1ms, 32 GB, seven-day backup)
- Key Vault for the database URL and API/Jitsi signing secrets
- Ubuntu 24.04 burstable VM (2 vCPU/4 GB) for the official Docker Jitsi Meet distribution
- Static public IP/DNS, HTTPS and UDP 10000 network rules
- Jitsi JWT-only access; the backend and Jitsi share the secret through Key Vault

Applying this template creates billable PostgreSQL and VM resources. Run it only after reviewing
the Azure cost estimate and receiving explicit approval.

## Validation and deployment outline

1. Copy `main.bicepparam.example` to an ignored private parameter file and provide generated
   secrets, the existing App Service outbound IPs, SSH public key and current developer IP.
2. Validate with `az deployment group validate` against `onda-dev-rg`.
3. Run a what-if deployment and review every resource and price-impacting SKU.
4. Deploy the Bicep file.
5. Run `configure-app-service.sh` with the Bicep outputs. This grants the existing App Service
   managed identity access to Key Vault and configures secret references; it does not upload code.
6. Remove the temporary developer PostgreSQL firewall rule after migrations/deployment succeed.
7. Verify Jitsi TLS, UDP 10000, JWT rejection without a token, API readiness and a two-device call.

The VM bootstrap downloads the pinned official stable `docker-jitsi-meet` release, generates
internal component passwords on the VM, fetches only the shared Jitsi JWT secret via managed
identity, enables Let's Encrypt, and starts the stack. Treat cloud-init success as provisioning,
not as production verification; inspect `/var/log/onda-jitsi-install.log` before enabling clients.
