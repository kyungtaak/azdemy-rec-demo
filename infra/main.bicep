targetScope = 'resourceGroup'

@allowed(['koreacentral'])
param location string = 'koreacentral'

@secure()
param sshPublicKey string

@description('Object ID of the deploying user, not an email or application ID.')
param operatorObjectId string

@description('Review date only. This tag does not schedule resource deletion.')
param expiresOn string

var suffix = substring(uniqueString(resourceGroup().id), 0, 8)
var prefix = 'genius${suffix}'
var tags = {
  project: 'genius-rec-demo'
  environment: 'demo'
  expiresOn: expiresOn
  dataClassification: 'synthetic'
}

module network 'network.bicep' = {
  name: 'network'
  params: {
    location: location
    tags: tags
  }
}

module services 'services.bicep' = {
  name: 'services'
  params: {
    location: location
    prefix: prefix
    tags: tags
    agentSubnetId: network.outputs.agentSubnetId
  }
}

module privateAccess 'private-access.bicep' = {
  name: 'private-access'
  params: {
    location: location
    tags: tags
    vnetId: network.outputs.vnetId
    peSubnetId: network.outputs.peSubnetId
    accountId: services.outputs.accountId
    searchId: services.outputs.searchId
    storageId: services.outputs.storageId
    cosmosId: services.outputs.cosmosId
    vaultId: services.outputs.vaultId
    apiId: services.outputs.apiId
  }
}

module project 'project.bicep' = {
  name: 'foundry-project'
  params: {
    location: location
    accountName: services.outputs.accountName
    searchName: services.outputs.searchName
    storageName: services.outputs.storageName
    cosmosName: services.outputs.cosmosName
    operatorObjectId: operatorObjectId
  }
  dependsOn: [privateAccess]
}

module jump 'jump.bicep' = {
  name: 'jump'
  params: {
    location: location
    tags: tags
    jumpSubnetId: network.outputs.jumpSubnetId
    sshPublicKey: sshPublicKey
  }
}

output resourceGroupName string = resourceGroup().name
output foundryAccountName string = services.outputs.accountName
output projectEndpoint string = 'https://${services.outputs.accountName}.services.ai.azure.com/api/projects/learning'
output projectName string = 'learning'
output modelDeployment string = 'gpt-5.6-terra'
output apiHostname string = '${services.outputs.apiName}.azurewebsites.net'
output jumpVmId string = jump.outputs.vmId
output jumpPrivateIp string = jump.outputs.privateIp
output bastionName string = network.outputs.bastionName
output reviewAfter string = expiresOn
