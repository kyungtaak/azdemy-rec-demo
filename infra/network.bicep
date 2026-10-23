param location string
param tags object

resource natIp 'Microsoft.Network/publicIPAddresses@2024-05-01' = {
  name: 'pip-azdemy-nat'
  location: location
  tags: tags
  sku: { name: 'Standard' }
  properties: { publicIPAllocationMethod: 'Static' }
}

resource nat 'Microsoft.Network/natGateways@2024-05-01' = {
  name: 'nat-azdemy'
  location: location
  tags: tags
  sku: { name: 'Standard' }
  properties: {
    publicIpAddresses: [{ id: natIp.id }]
    idleTimeoutInMinutes: 10
  }
}

resource jumpNsg 'Microsoft.Network/networkSecurityGroups@2024-05-01' = {
  name: 'nsg-azdemy-jump'
  location: location
  tags: tags
  properties: {
    securityRules: [
      {
        name: 'AllowBastionSsh'
        properties: {
          priority: 100
          direction: 'Inbound'
          access: 'Allow'
          protocol: 'Tcp'
          sourceAddressPrefix: '10.72.3.0/26'
          sourcePortRange: '*'
          destinationAddressPrefix: '*'
          destinationPortRange: '22'
        }
      }
      {
        name: 'DenyOtherInbound'
        properties: {
          priority: 200
          direction: 'Inbound'
          access: 'Deny'
          protocol: '*'
          sourceAddressPrefix: '*'
          sourcePortRange: '*'
          destinationAddressPrefix: '*'
          destinationPortRange: '*'
        }
      }
    ]
  }
}

resource vnet 'Microsoft.Network/virtualNetworks@2024-05-01' = {
  name: 'vnet-azdemy-krc'
  location: location
  tags: tags
  properties: {
    addressSpace: { addressPrefixes: ['10.72.0.0/16'] }
    subnets: [
      {
        name: 'agents'
        properties: {
          addressPrefix: '10.72.0.0/24'
          defaultOutboundAccess: false
          delegations: [{
            name: 'foundry-agent'
            properties: { serviceName: 'Microsoft.App/environments' }
          }]
        }
      }
      {
        name: 'private-endpoints'
        properties: {
          addressPrefix: '10.72.1.0/24'
          defaultOutboundAccess: false
          privateEndpointNetworkPolicies: 'Disabled'
        }
      }
      {
        name: 'jump'
        properties: {
          addressPrefix: '10.72.2.0/24'
          defaultOutboundAccess: false
          natGateway: { id: nat.id }
          networkSecurityGroup: { id: jumpNsg.id }
        }
      }
      {
        name: 'AzureBastionSubnet'
        properties: {
          addressPrefix: '10.72.3.0/26'
          defaultOutboundAccess: false
        }
      }
    ]
  }
}

resource bastionIp 'Microsoft.Network/publicIPAddresses@2024-05-01' = {
  name: 'pip-azdemy-bastion'
  location: location
  tags: tags
  sku: { name: 'Standard' }
  properties: { publicIPAllocationMethod: 'Static' }
}

resource bastion 'Microsoft.Network/bastionHosts@2024-05-01' = {
  name: 'bas-azdemy-krc'
  location: location
  tags: tags
  sku: { name: 'Standard' }
  properties: {
    scaleUnits: 2
    enableTunneling: true
    ipConfigurations: [{
      name: 'bastion'
      properties: {
        subnet: { id: '${vnet.id}/subnets/AzureBastionSubnet' }
        publicIPAddress: { id: bastionIp.id }
      }
    }]
  }
}

output vnetId string = vnet.id
output agentSubnetId string = '${vnet.id}/subnets/agents'
output peSubnetId string = '${vnet.id}/subnets/private-endpoints'
output jumpSubnetId string = '${vnet.id}/subnets/jump'
output bastionName string = bastion.name
