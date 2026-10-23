param apiName string
param tenantId string
param apiClientId string
param principalLearners object
param publicationRoot string = ''

resource api 'Microsoft.Web/sites@2023-12-01' existing = {
  name: apiName
}

resource settings 'Microsoft.Web/sites/config@2023-12-01' = {
  parent: api
  name: 'appsettings'
  properties: {
    AZDEMY_TENANT_ID: tenantId
    AZDEMY_API_CLIENT_ID: apiClientId
    AZDEMY_PRINCIPAL_LEARNERS: string(principalLearners)
    SCM_DO_BUILD_DURING_DEPLOYMENT: 'false'
    AZDEMY_PUBLICATION_ROOT: publicationRoot
  }
}

resource runtime 'Microsoft.Web/sites/config@2023-12-01' = {
  parent: api
  name: 'web'
  properties: {
    linuxFxVersion: 'PYTHON|3.12'
    appCommandLine: 'PYTHONPATH=/home/site/wwwroot/.python_packages/lib/site-packages python -m uvicorn api.main:app --host 0.0.0.0 --port 8000'
    alwaysOn: false
    ftpsState: 'Disabled'
    minTlsVersion: '1.2'
    scmMinTlsVersion: '1.2'
    remoteDebuggingEnabled: false
  }

}

resource logs 'Microsoft.Web/sites/config@2023-12-01' = {
  parent: api
  name: 'logs'
  properties: {
    applicationLogs: {
      fileSystem: { level: 'Information' }
    }
    httpLogs: {
      fileSystem: { enabled: true, retentionInDays: 1, retentionInMb: 25 }
    }
  }
}
