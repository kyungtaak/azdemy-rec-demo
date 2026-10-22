param workspaceId string
param tenantId string
param location string = 'koreacentral'
param vnetName string = 'vnet-genius-krc'
param tags object = {
  project: 'genius-rec-demo'
  environment: 'demo'
  expiresOn: '2026-10-22'
}

resource vnet 'Microsoft.Network/virtualNetworks@2024-05-01' existing = {
  name: vnetName
}

resource linkService 'Microsoft.Fabric/privateLinkServicesForFabric@2024-06-01' = {
  name: 'pls-genius-fabric'
  location: 'global'
  tags: tags
  properties: {
    tenantId: tenantId
    workspaceId: workspaceId
  }
}

resource dns 'Microsoft.Network/privateDnsZones@2024-06-01' = {
  name: 'privatelink.fabric.microsoft.com'
  location: 'global'
  tags: tags
}

resource dnsLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = {
  parent: dns
  name: 'genius-fabric-vnet'
  location: 'global'
  properties: {
    registrationEnabled: false
    virtualNetwork: { id: vnet.id }
  }
}

resource endpoint 'Microsoft.Network/privateEndpoints@2024-05-01' = {
  name: 'pe-genius-fabric'
  location: location
  tags: tags
  properties: {
    subnet: { id: '${vnet.id}/subnets/private-endpoints' }
    privateLinkServiceConnections: [{
      name: 'fabric-workspace'
      properties: {
        privateLinkServiceId: linkService.id
        groupIds: ['workspace']
      }
    }]
  }
}

resource zoneGroup 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-05-01' = {
  parent: endpoint
  name: 'default'
  properties: {
    privateDnsZoneConfigs: [{
      name: 'fabric'
      properties: { privateDnsZoneId: dns.id }
    }]
  }
}

output fabricWorkspaceId string = workspaceId
output privateEndpointId string = endpoint.id
