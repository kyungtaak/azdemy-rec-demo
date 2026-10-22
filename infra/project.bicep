param location string
param accountName string
param searchName string
param storageName string
param cosmosName string
param operatorObjectId string

// Adapted from microsoft-foundry/foundry-samples template 19; see THIRD-PARTY-NOTICES.
resource account 'Microsoft.CognitiveServices/accounts@2025-04-01-preview' existing = {
  name: accountName
}
resource search 'Microsoft.Search/searchServices@2024-06-01-preview' existing = {
  name: searchName
}
resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' existing = {
  name: storageName
}
resource cosmos 'Microsoft.DocumentDB/databaseAccounts@2024-11-15' existing = {
  name: cosmosName
}

resource project 'Microsoft.CognitiveServices/accounts/projects@2025-04-01-preview' = {
  parent: account
  name: 'learning'
  location: location
  identity: { type: 'SystemAssigned' }
  properties: {
    displayName: 'Azdemy learning demo'
    description: 'Read-only consultation; synthetic recommendations; private tools.'
  }

  resource searchConnection 'connections@2025-04-01-preview' = {
    name: searchName
    properties: {
      category: 'CognitiveSearch'
      target: 'https://${searchName}.search.windows.net'
      authType: 'AAD'
      metadata: { ApiType: 'Azure', ResourceId: search.id, location: location }
    }
  }
  resource storageConnection 'connections@2025-04-01-preview' = {
    name: storageName
    properties: {
      category: 'AzureStorageAccount'
      target: storage.properties.primaryEndpoints.blob
      authType: 'AAD'
      metadata: { ApiType: 'Azure', ResourceId: storage.id, location: location }
    }
  }
  resource cosmosConnection 'connections@2025-04-01-preview' = {
    name: cosmosName
    properties: {
      category: 'CosmosDB'
      target: cosmos.properties.documentEndpoint
      authType: 'AAD'
      metadata: { ApiType: 'Azure', ResourceId: cosmos.id, location: location }
    }
  }
}

var blobContributor = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'ba92f5b4-2d11-453d-a403-e96b0029c9fe')
resource blobRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: storage
  name: guid(storage.id, project.id, blobContributor)
  properties: {
    principalId: project.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: blobContributor
  }
}

var cosmosOperator = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '230815da-be43-4aae-9cb4-875f7bd000aa')
resource cosmosRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: cosmos
  name: guid(cosmos.id, project.id, cosmosOperator)
  properties: {
    principalId: project.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: cosmosOperator
  }
}

var searchRoles = [
  subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '8ebe5a00-799e-43f5-93ac-243d3dce84a7')
  subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '7ca78c08-252a-4471-8644-bb5ff32d4ba0')
]
resource searchRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for role in searchRoles: {
  scope: search
  name: guid(search.id, project.id, role)
  properties: {
    principalId: project.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: role
  }
}]

resource capability 'Microsoft.CognitiveServices/accounts/projects/capabilityHosts@2025-04-01-preview' = {
  parent: project
  name: 'agents'
  properties: {
    // The official template uses this property; the preview Bicep schema omits it.
    #disable-next-line BCP037
    capabilityHostKind: 'Agents'
    vectorStoreConnections: [project::searchConnection.name]
    storageConnections: [project::storageConnection.name]
    threadStorageConnections: [project::cosmosConnection.name]
  }
  dependsOn: [blobRole, cosmosRole, searchRole]
}

var dataContributor = '${cosmos.id}/sqlRoleDefinitions/00000000-0000-0000-0000-000000000002'
resource cosmosDataRole 'Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments@2024-11-15' = {
  parent: cosmos
  name: guid(cosmos.id, project.id, dataContributor)
  properties: {
    principalId: project.identity.principalId
    roleDefinitionId: dataContributor
    scope: cosmos.id
  }
  dependsOn: [capability]
}

// The service returns a 32-character internalId; container prefixes use its GUID form.
#disable-next-line BCP053
var internalId = project.properties.internalId
var workspaceId = '${substring(internalId, 0, 8)}-${substring(internalId, 8, 4)}-${substring(internalId, 12, 4)}-${substring(internalId, 16, 4)}-${substring(internalId, 20, 12)}'
var blobOwner = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'b7e6dc6d-f1e8-4753-8033-0f276bb0955b')
resource blobTagsRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: storage
  name: guid(storage.id, project.id, blobOwner)
  properties: {
    principalId: project.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: blobOwner
    conditionVersion: '2.0'
    condition: '((!(ActionMatches{\'Microsoft.Storage/storageAccounts/blobServices/containers/blobs/tags/read\'}) AND !(ActionMatches{\'Microsoft.Storage/storageAccounts/blobServices/containers/blobs/filter/action\'}) AND !(ActionMatches{\'Microsoft.Storage/storageAccounts/blobServices/containers/blobs/tags/write\'})) OR (@Resource[Microsoft.Storage/storageAccounts/blobServices/containers:name] StringStartsWithIgnoreCase \'${workspaceId}\' AND @Resource[Microsoft.Storage/storageAccounts/blobServices/containers:name] StringLikeIgnoreCase \'*-azureml-agent\'))'
  }
  dependsOn: [capability]
}

var foundryUser = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '53ca6127-db72-4b80-b1b0-d745d6d5456d')
resource operatorRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: project
  name: guid(project.id, operatorObjectId, foundryUser)
  properties: {
    principalId: operatorObjectId
    principalType: 'User'
    roleDefinitionId: foundryUser
  }
}
