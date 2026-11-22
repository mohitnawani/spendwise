"""Setup Keycloak spendwise realm, client, roles, and test users."""

import asyncio
import json
from pathlib import Path

import httpx


async def setup_keycloak() -> None:
    base_url = "http://localhost:8080"
    async with httpx.AsyncClient(base_url=base_url, timeout=30.0) as client:
        # 1. Obtain admin token from master realm
        print("Obtaining admin token...")
        token_resp = await client.post(
            "/realms/master/protocol/openid-connect/token",
            data={
                "client_id": "admin-cli",
                "username": "admin",
                "password": "admin",
                "grant_type": "password",
            },
        )
        token_resp.raise_for_status()
        admin_token = token_resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {admin_token}"}

        # 2. Check or create realm 'spendwise'
        realm_resp = await client.get("/admin/realms/spendwise", headers=headers)
        if realm_resp.status_code == 404:
            print("Creating realm 'spendwise'...")
            create_realm_resp = await client.post(
                "/admin/realms",
                headers=headers,
                json={"realm": "spendwise", "enabled": True},
            )
            create_realm_resp.raise_for_status()
            print("Realm 'spendwise' created.")
        else:
            print("Realm 'spendwise' already exists.")

        # 3. Create realm roles USER and ADMIN
        for role_name in ["USER", "ADMIN"]:
            role_resp = await client.get(
                f"/admin/realms/spendwise/roles/{role_name}",
                headers=headers,
            )
            if role_resp.status_code == 404:
                print(f"Creating role '{role_name}'...")
                r = await client.post(
                    "/admin/realms/spendwise/roles",
                    headers=headers,
                    json={"name": role_name},
                )
                r.raise_for_status()
                print(f"Role '{role_name}' created.")
            else:
                print(f"Role '{role_name}' already exists.")

        # 4. Check or create client 'spendwise-api'
        clients_resp = await client.get(
            "/admin/realms/spendwise/clients?clientId=spendwise-api",
            headers=headers,
        )
        clients = clients_resp.json()
        if not clients:
            print("Creating client 'spendwise-api'...")
            client_payload = {
                "clientId": "spendwise-api",
                "enabled": True,
                "publicClient": True,
                "standardFlowEnabled": True,
                "directAccessGrantsEnabled": True,
                "redirectUris": [
                    "http://localhost:8000/*",
                    "http://localhost:8080/*",
                    "https://oauth.pstmn.io/v1/callback",
                ],
                "webOrigins": ["*"],
            }
            create_client_resp = await client.post(
                "/admin/realms/spendwise/clients",
                headers=headers,
                json=client_payload,
            )
            create_client_resp.raise_for_status()
            # Fetch created client
            clients_resp = await client.get(
                "/admin/realms/spendwise/clients?clientId=spendwise-api",
                headers=headers,
            )
            client_id = clients_resp.json()[0]["id"]
            print(f"Client 'spendwise-api' created with ID {client_id}.")
        else:
            client_id = clients[0]["id"]
            print(f"Client 'spendwise-api' already exists with ID {client_id}.")

        # 5. Add audience protocol mapper to spendwise-api client
        mappers_resp = await client.get(
            f"/admin/realms/spendwise/clients/{client_id}/protocol-mappers/models",
            headers=headers,
        )
        mappers = mappers_resp.json()
        has_aud_mapper = any(m.get("name") == "spendwise-api-audience" for m in mappers)
        if not has_aud_mapper:
            print("Adding audience mapper to 'spendwise-api'...")
            aud_mapper = {
                "name": "spendwise-api-audience",
                "protocol": "openid-connect",
                "protocolMapper": "oidc-audience-mapper",
                "config": {
                    "included.client.audience": "spendwise-api",
                    "id.token.claim": "false",
                    "access.token.claim": "true",
                },
            }
            r = await client.post(
                f"/admin/realms/spendwise/clients/{client_id}/protocol-mappers/models",
                headers=headers,
                json=aud_mapper,
            )
            r.raise_for_status()
            print("Audience mapper added.")
        else:
            print("Audience mapper already present.")

        # Helper to get role representation
        async def get_role(name: str) -> dict:
            r = await client.get(
                f"/admin/realms/spendwise/roles/{name}",
                headers=headers,
            )
            r.raise_for_status()
            return r.json()

        user_role = await get_role("USER")
        admin_role = await get_role("ADMIN")

        # 6. Create users
        users_config = [
            {
                "username": "testuser",
                "email": "user@spendwise.local",
                "password": "testuser123",
                "roles": [user_role],
            },
            {
                "username": "adminuser",
                "email": "admin@spendwise.local",
                "password": "adminuser123",
                "roles": [user_role, admin_role],
            },
        ]

        for u in users_config:
            u_resp = await client.get(
                f"/admin/realms/spendwise/users?username={u['username']}",
                headers=headers,
            )
            existing_users = u_resp.json()
            if not existing_users:
                print(f"Creating user '{u['username']}'...")
                create_u = await client.post(
                    "/admin/realms/spendwise/users",
                    headers=headers,
                    json={
                        "username": u["username"],
                        "email": u["email"],
                        "enabled": True,
                        "emailVerified": True,
                    },
                )
                create_u.raise_for_status()
                u_resp = await client.get(
                    f"/admin/realms/spendwise/users?username={u['username']}",
                    headers=headers,
                )
                user_id = u_resp.json()[0]["id"]

                # Set password
                pwd_resp = await client.put(
                    f"/admin/realms/spendwise/users/{user_id}/reset-password",
                    headers=headers,
                    json={
                        "type": "password",
                        "value": u["password"],
                        "temporary": False,
                    },
                )
                pwd_resp.raise_for_status()

                # Assign roles
                role_map_resp = await client.post(
                    f"/admin/realms/spendwise/users/{user_id}/role-mappings/realm",
                    headers=headers,
                    json=u["roles"],
                )
                role_map_resp.raise_for_status()
                print(f"User '{u['username']}' created and roles assigned.")
            else:
                user_id = existing_users[0]["id"]
                print(f"User '{u['username']}' already exists.")

        # 7. Export realm for persistence and repository
        print("Exporting realm configuration...")
        export_resp = await client.get(
            "/admin/realms/spendwise",
            headers=headers,
        )
        export_resp.raise_for_status()
        realm_data = export_resp.json()

        keycloak_dir = Path("keycloak")
        keycloak_dir.mkdir(exist_ok=True)
        export_path = keycloak_dir / "realm-export.json"
        export_path.write_text(json.dumps(realm_data, indent=2), encoding="utf-8")
        print(f"Realm configuration saved to {export_path}")


if __name__ == "__main__":
    asyncio.run(setup_keycloak())
