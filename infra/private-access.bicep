param location string
param tags object
param vnetId string
param peSubnetId string
param accountId string
param searchId string
param storageId string
param cosmosId string
param vaultId string
param apiId string

var zones = [
  'privatelink.services.ai.azure.com'
  'privatelink.openai.azure.com'
  'privatelink.cognitiveservices.azure.com'
  'privatelink.search.windows.net'
  'privatelink.blob.${environment().suffixes.storage}'
  'privatelink.documents.azure.com'
  'privatelink.vaultcore.azure.net'
  'privatelink.azurewebsites.net'
]

resource dns 'Microsoft.Network/privateDnsZones@2024-06-01' = [for zone in zones: {
  name: zone
  location: 'global'
  tags: tags
}]

resource links 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = [for (zone, i) in zones: {
  parent: dns[i]
  name: 'genius-vnet'
  location: 'global'
  properties: {
    registrationEnabled: false
    virtualNetwork: { id: vnetId }
  }
}]

var endpoints = [
  { name: 'foundry', id: accountId, group: 'account', zones: [0, 1, 2] }
  { name: 'search', id: searchId, group: 'searchService', zones: [3] }
  { name: 'blob', id: storageId, group: 'blob', zones: [4] }
  { name: 'cosmos', id: cosmosId, group: 'Sql', zones: [5] }
  { name: 'vault', id: vaultId, group: 'vault', zones: [6] }
  { name: 'api', id: apiId, group: 'sites', zones: [7] }
]

resource pe 'Microsoft.Network/privateEndpoints@2024-05-01' = [for endpoint in endpoints: {
  name: 'pe-genius-${endpoint.name}'
  location: location
  tags: tags
  properties: {
    subnet: { id: peSubnetId }
    privateLinkServiceConnections: [{
      name: endpoint.name
      properties: {
        privateLinkServiceId: endpoint.id
        groupIds: [endpoint.group]
      }
    }]
  }
}]

resource groups 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-05-01' = [for (endpoint, i) in endpoints: {
  parent: pe[i]
  name: 'default'
  properties: {
    privateDnsZoneConfigs: [for zoneIndex in endpoint.zones: {
      name: 'zone-${zoneIndex}'
      properties: { privateDnsZoneId: dns[zoneIndex].id }
    }]
  }
}]
