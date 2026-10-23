"""Validate the compiled ARM resource inventory without contacting Azure."""

import json
import re
import sys
from collections import Counter
from pathlib import Path


def resources(template):
    for resource in template["resources"]:
        yield resource
        if resource["type"] == "Microsoft.Resources/deployments":
            yield from resources(resource["properties"]["template"])


def validate(path):
    template = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    inventory = list(resources(template))
    assert not re.search(r"genius|\bkt\b|\bkt[-_]", json.dumps(template), re.IGNORECASE)
    assert template["variables"]["prefix"] == "[format('azdemy{0}', variables('suffix'))]"
    assert template["variables"]["tags"]["project"] == "azdemy-rec-demo"
    by_type = {}
    for resource in inventory:
        by_type.setdefault(resource["type"], []).append(resource)

    def one(resource_type):
        matches = by_type[resource_type]
        assert len(matches) == 1, (resource_type, len(matches))
        return matches[0]

    foundry = one("Microsoft.CognitiveServices/accounts")
    assert foundry["properties"]["disableLocalAuth"] is True
    assert foundry["properties"]["publicNetworkAccess"] == "Disabled"
    assert foundry["properties"]["networkInjections"][0]["scenario"] == "agent"
    model = one("Microsoft.CognitiveServices/accounts/deployments")
    assert model["sku"] == {"name": "GlobalStandard", "capacity": 100}
    assert model["properties"]["model"]["name"] == "gpt-5.6-terra"
    assert model["properties"]["model"]["version"] == "2026-07-09"
    assert model["properties"]["versionUpgradeOption"] == "NoAutoUpgrade"
    search = one("Microsoft.Search/searchServices")
    assert search["sku"]["name"] == "basic"
    assert search["properties"]["disableLocalAuth"] is True
    assert search["properties"]["publicNetworkAccess"] == "disabled"
    cosmos = one("Microsoft.DocumentDB/databaseAccounts")
    assert cosmos["properties"]["capabilities"] == [{"name": "EnableServerless"}]
    assert cosmos["properties"]["disableLocalAuth"] is True
    assert cosmos["properties"]["publicNetworkAccess"] == "Disabled"
    storage = one("Microsoft.Storage/storageAccounts")
    assert storage["sku"]["name"] == "Standard_LRS"
    assert storage["properties"]["allowSharedKeyAccess"] is False
    assert storage["properties"]["publicNetworkAccess"] == "Disabled"
    assert one("Microsoft.KeyVault/vaults")["properties"]["publicNetworkAccess"] == "Disabled"
    assert one("Microsoft.Web/sites")["properties"]["publicNetworkAccess"] == "Disabled"
    assert all(r["properties"]["allow"] is False for r in
               by_type["Microsoft.Web/sites/basicPublishingCredentialsPolicies"])
    bastion = one("Microsoft.Network/bastionHosts")
    assert bastion["name"] == "bas-azdemy-krc"
    assert bastion["sku"]["name"] == "Standard"
    assert bastion["properties"]["scaleUnits"] == 2
    assert bastion["properties"]["enableTunneling"] is True
    nic = one("Microsoft.Network/networkInterfaces")
    assert nic["name"] == "nic-azdemy-jump"
    assert all("publicIPAddress" not in c["properties"]
               for c in nic["properties"]["ipConfigurations"])
    vm = one("Microsoft.Compute/virtualMachines")
    assert vm["name"] == "vm-azdemy-jump"
    assert vm["properties"]["osProfile"]["computerName"] == "azdemy-jump"
    assert vm["properties"]["storageProfile"]["osDisk"]["name"] == "disk-azdemy-jump"
    assert one("Microsoft.Network/virtualNetworks")["name"] == "vnet-azdemy-krc"
    assert one("Microsoft.Web/serverfarms")["name"] == "asp-azdemy-api"
    assert vm["properties"]["hardwareProfile"]["vmSize"] == "Standard_B2as_v2"
    assert vm["properties"]["osProfile"]["linuxConfiguration"]["disablePasswordAuthentication"] is True
    subnets = one("Microsoft.Network/virtualNetworks")["properties"]["subnets"]
    assert len(subnets) == 4
    assert all(s["properties"]["defaultOutboundAccess"] is False for s in subnets)
    agents = next(s for s in subnets if s["name"] == "agents")
    assert agents["properties"]["delegations"][0]["properties"]["serviceName"] == "Microsoft.App/environments"
    project_template = next(r["properties"]["template"] for r in template["resources"]
                            if r["name"] == "foundry-project")
    expected_roles = {
        "blobContributor": "ba92f5b4-2d11-453d-a403-e96b0029c9fe",
        "cosmosOperator": "230815da-be43-4aae-9cb4-875f7bd000aa",
        "blobOwner": "b7e6dc6d-f1e8-4753-8033-0f276bb0955b",
        "foundryUser": "53ca6127-db72-4b80-b1b0-d745d6d5456d",
    }
    for variable, role_id in expected_roles.items():
        assert project_template["variables"][variable] == (
            f"[subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '{role_id}')]")
    for assignment in by_type["Microsoft.Authorization/roleAssignments"]:
        assert assignment["scope"].startswith("[resourceId("), assignment["scope"]
    assert "8e3af657-a8ff-443c-a75c-2fe8c4bcb635" not in json.dumps(project_template)
    for resource_type in ("Microsoft.ContainerRegistry/registries",
                          "Microsoft.OperationalInsights/workspaces",
                          "Microsoft.ContainerService/managedClusters"):
        assert resource_type not in by_type, resource_type

    private_template = next(r["properties"]["template"] for r in template["resources"]
                            if r["name"] == "private-access")
    assert len(private_template["variables"]["endpoints"]) == 6
    assert len(private_template["variables"]["zones"]) == 8
    assert template["parameters"]["sshPublicKey"]["type"].lower() == "securestring"
    print("PASS: Azdemy naming, inventory, private/keyless boundaries, model, SKUs, Linux and Bastion invariants")
    print(json.dumps(Counter(r["type"] for r in inventory), indent=2))


if __name__ == "__main__":
    validate(sys.argv[1])
