param(
    [string]$ResourceGroup = 'rg-azdemy-rec-demo-krc',
    [Parameter(Mandatory)][string]$ApiName,
    [Parameter(Mandatory)][string]$ToolPrincipalId
)

$ErrorActionPreference = 'Stop'

function Invoke-AzJson([string[]]$Arguments) {
    $result = & az @Arguments --only-show-errors --output json
    if ($LASTEXITCODE -ne 0) { throw "Azure CLI failed: $($Arguments[0]) $($Arguments[1])" }
    if ($result) { return ($result | ConvertFrom-Json) }
}

function Invoke-GraphWrite([string]$Method, [string]$Url, [object]$Body) {
    $temporary = [System.IO.Path]::GetTempFileName()
    try {
        $Body | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $temporary -Encoding utf8
        Invoke-AzJson @('rest', '--method', $Method, '--url', $Url,
                       '--headers', 'Content-Type=application/json', '--body', "@$temporary")
    } finally {
        Remove-Item -LiteralPath $temporary
    }
}

$account = Invoke-AzJson @('account', 'show')
$api = Invoke-AzJson @('webapp', 'show', '-g', $ResourceGroup, '-n', $ApiName)
if ($api.publicNetworkAccess -ne 'Disabled') { throw 'The API must remain Private' }
$currentSettings = @(Invoke-AzJson @('webapp', 'config', 'appsettings', 'list',
    '-g', $ResourceGroup, '-n', $ApiName))
$publicationSetting = @($currentSettings | Where-Object name -eq 'AZDEMY_PUBLICATION_ROOT')
if ($publicationSetting.Count -gt 1) { throw 'Duplicate publication root settings' }
$publicationRoot = if ($publicationSetting.Count -eq 1) { $publicationSetting[0].value } else { '' }
$displayName = 'azdemy-rec-demo-api'
$description = "Synthetic read-only education API for $($api.id)"
$applications = @(Invoke-AzJson @('ad', 'app', 'list', '--display-name', $displayName))
if ($applications.Count -gt 1) { throw 'Multiple Entra applications match; refusing to choose' }
$roleId = '6ca79394-bb79-4b4b-8538-b5d45ddbcb27'
$scopeId = '994b589b-78bb-49fa-9f85-3ba5f5425f63'
if ($applications.Count -eq 0) {
    $application = Invoke-GraphWrite 'POST' 'https://graph.microsoft.com/v1.0/applications' @{
        displayName = $displayName
        description = $description
        signInAudience = 'AzureADMyOrg'
        api = @{
            requestedAccessTokenVersion = 2
            oauth2PermissionScopes = @(@{
                id = $scopeId; value = 'access_as_user'; type = 'Admin'; isEnabled = $true
                adminConsentDisplayName = 'Read synthetic education as the signed-in demo learner'
                adminConsentDescription = 'Read-only access to synthetic courses and the mapped learner.'
            })
        }
        appRoles = @(@{
            id = $roleId; value = 'Learner.Read'; isEnabled = $true
            allowedMemberTypes = @('Application')
            displayName = 'Read synthetic learner education'
            description = 'Read-only education queries for an explicitly mapped synthetic learner.'
        })
    }
    Invoke-GraphWrite 'PATCH' "https://graph.microsoft.com/v1.0/applications/$($application.id)" @{
        identifierUris = @("api://$($application.appId)")
    } | Out-Null
} else {
    $application = $applications[0]
    if ($application.description -ne $description) {
        throw 'An unrelated application uses this name; refusing to modify it'
    }
}
$principals = @(Invoke-AzJson @('ad', 'sp', 'list', '--filter', "appId eq '$($application.appId)'"))
if ($principals.Count -eq 0) {
    $principal = Invoke-GraphWrite 'POST' 'https://graph.microsoft.com/v1.0/servicePrincipals' @{
        appId = $application.appId; appRoleAssignmentRequired = $true
    }
} elseif ($principals.Count -eq 1) {
    $principal = $principals[0]
} else {
    throw 'Multiple API service principals match'
}
$assignments = Invoke-AzJson @('rest', '--method', 'GET', '--url',
    "https://graph.microsoft.com/v1.0/servicePrincipals/$ToolPrincipalId/appRoleAssignments")
$existing = @($assignments.value | Where-Object {
    $_.resourceId -eq $principal.id -and $_.appRoleId -eq $roleId
})
if ($existing.Count -eq 0) {
    Invoke-GraphWrite 'POST' "https://graph.microsoft.com/v1.0/servicePrincipals/$ToolPrincipalId/appRoleAssignments" @{
        principalId = $ToolPrincipalId; resourceId = $principal.id; appRoleId = $roleId
    } | Out-Null
}
$parameterFile = [System.IO.Path]::GetTempFileName()
try {
    @{
        apiName = @{value = $ApiName}
        tenantId = @{value = $account.tenantId}
        apiClientId = @{value = $application.appId}
        principalLearners = @{value = @{$ToolPrincipalId = 'learner-a'}}
        publicationRoot = @{value = $publicationRoot}
    } | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $parameterFile -Encoding utf8
    $deployment = Invoke-AzJson @('deployment', 'group', 'create', '-g', $ResourceGroup,
        '-n', 'azdemy-api-config', '--template-file', "$PSScriptRoot\api-config.bicep",
        '--parameters', "@$parameterFile")
    if ($deployment.properties.provisioningState -ne 'Succeeded') { throw 'API configuration failed' }
} finally {
    Remove-Item -LiteralPath $parameterFile
}
[ordered]@{
    apiClientId = $application.appId
    apiApplicationObjectId = $application.id
    apiServicePrincipalId = $principal.id
    audience = "api://$($application.appId)"
    allowedToolPrincipal = $ToolPrincipalId
    learner = 'learner-a'
} | ConvertTo-Json
