param location string
@minLength(3)
param prefix string
param tags object
param agentSubnetId string

// Adapted from microsoft-foundry/foundry-samples template 19; see THIRD-PARTY-NOTICES.
resource account 'Microsoft.CognitiveServices/accounts@2025-04-01-preview' = {
  name: '${prefix}ai'
  location: location
  tags: tags
  kind: 'AIServices'
  sku: { name: 'S0' }
  identity: { type: 'SystemAssigned' }
  properties: {
    allowProjectManagement: true
    customSubDomainName: '${prefix}ai'
    publicNetworkAccess: 'Disabled'
    disableLocalAuth: true
    networkAcls: {
      defaultAction: 'Deny'
      bypass: 'AzureServices'
      ipRules: []
      virtualNetworkRules: []
    }
    networkInjections: [{
      scenario: 'agent'
      subnetArmId: agentSubnetId
      useMicrosoftManagedNetwork: false
    }]
  }
}

resource model 'Microsoft.CognitiveServices/accounts/deployments@2025-04-01-preview' = {
  parent: account
  name: 'gpt-5.6-terra'
  sku: {
    name: 'GlobalStandard'
    capacity: 100
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: 'gpt-5.6-terra'
      version: '2026-07-09'
    }
    versionUpgradeOption: 'NoAutoUpgrade'
    raiPolicyName: 'Microsoft.DefaultV2'
  }
}

resource search 'Microsoft.Search/searchServices@2024-06-01-preview' = {
  name: '${prefix}search'
  location: location
  tags: tags
  sku: { name: 'basic' }
  identity: { type: 'SystemAssigned' }
  properties: {
    disableLocalAuth: true
    hostingMode: 'default'
    partitionCount: 1
    replicaCount: 1
    publicNetworkAccess: 'disabled'
    semanticSearch: 'disabled'
    networkRuleSet: { bypass: 'None', ipRules: [] }
  }
}

resource cosmos 'Microsoft.DocumentDB/databaseAccounts@2024-11-15' = {
  name: '${prefix}cosmos'
  location: location
  tags: tags
  kind: 'GlobalDocumentDB'
  properties: {
    databaseAccountOfferType: 'Standard'
    capabilities: [{ name: 'EnableServerless' }]
    consistencyPolicy: { defaultConsistencyLevel: 'Session' }
    disableLocalAuth: true
    publicNetworkAccess: 'Disabled'
    enableAutomaticFailover: false
    enableMultipleWriteLocations: false
    locations: [{
      locationName: location
      failoverPriority: 0
      isZoneRedundant: false
    }]
  }
}

resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: '${prefix}st'
  location: location
  tags: tags
  kind: 'StorageV2'
  sku: { name: 'Standard_LRS' }
  properties: {
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
    allowBlobPublicAccess: false
    allowSharedKeyAccess: false
    publicNetworkAccess: 'Disabled'
    networkAcls: {
      bypass: 'AzureServices'
      defaultAction: 'Deny'
    }
  }
}

resource vault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: '${prefix}kv'
  location: location
  tags: tags
  properties: {
    tenantId: tenant().tenantId
    sku: { family: 'A', name: 'standard' }
    enableRbacAuthorization: true
    enableSoftDelete: true
    softDeleteRetentionInDays: 7
    publicNetworkAccess: 'Disabled'
    networkAcls: { bypass: 'AzureServices', defaultAction: 'Deny' }
  }
}

resource plan 'Microsoft.Web/serverfarms@2023-12-01' = {
  name: 'asp-azdemy-api'
  location: location
  tags: tags
  kind: 'linux'
  sku: { name: 'B1', tier: 'Basic', capacity: 1 }
  properties: { reserved: true }
}

resource api 'Microsoft.Web/sites@2023-12-01' = {
  name: '${prefix}api'
  location: location
  tags: tags
  kind: 'app,linux'
  identity: { type: 'SystemAssigned' }
  properties: {
    serverFarmId: plan.id
    httpsOnly: true
    publicNetworkAccess: 'Disabled'
    siteConfig: {
      linuxFxVersion: 'PYTHON|3.12'
      alwaysOn: false
      ftpsState: 'Disabled'
      minTlsVersion: '1.2'
      scmMinTlsVersion: '1.2'
      remoteDebuggingEnabled: false
    }
  }
}

resource ftp 'Microsoft.Web/sites/basicPublishingCredentialsPolicies@2023-12-01' = {
  parent: api
  name: 'ftp'
  properties: { allow: false }
}

resource scm 'Microsoft.Web/sites/basicPublishingCredentialsPolicies@2023-12-01' = {
  parent: api
  name: 'scm'
  properties: { allow: false }
}

output accountName string = account.name
output accountId string = account.id
output searchName string = search.name
output searchId string = search.id
output storageName string = storage.name
output storageId string = storage.id
output cosmosName string = cosmos.name
output cosmosId string = cosmos.id
output vaultId string = vault.id
output apiName string = api.name
output apiId string = api.id
