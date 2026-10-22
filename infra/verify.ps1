param(
    [string]$ResourceGroup = 'rg-genius-rec-demo-krc'
)

$ErrorActionPreference = 'Stop'

function Invoke-AzJson {
    param([string[]]$Arguments)
    $result = & az @Arguments --output json --only-show-errors
    if ($LASTEXITCODE -ne 0) {
        throw "Azure CLI failed: az $($Arguments -join ' ')"
    }
    return ($result | ConvertFrom-Json)
}

function Assert-Equal {
    param($Actual, $Expected, [string]$Label)
    if ($Actual -cne $Expected) {
        throw "${Label}: expected '$Expected', received '$Actual'"
    }
    Write-Output "PASS: $Label = $Expected"
}

$resources = Invoke-AzJson -Arguments @('resource', 'list', '--resource-group', $ResourceGroup)
$versions = @{
    'Microsoft.CognitiveServices/accounts' = '2025-04-01-preview'
    'Microsoft.Search/searchServices' = '2024-06-01-preview'
    'Microsoft.DocumentDB/databaseAccounts' = '2024-11-15'
    'Microsoft.Storage/storageAccounts' = '2023-05-01'
    'Microsoft.KeyVault/vaults' = '2023-07-01'
    'Microsoft.Web/sites' = '2023-12-01'
}

foreach ($type in $versions.Keys) {
    $matches = @($resources | Where-Object { $_.type -eq $type })
    Assert-Equal $matches.Count 1 "$type count"
    $resource = Invoke-AzJson -Arguments @(
        'resource', 'show', '--ids', $matches[0].id, '--api-version', $versions[$type]
    )
    Assert-Equal $resource.properties.publicNetworkAccess.ToLowerInvariant() 'disabled' "$type public access"
    if ($type -in @('Microsoft.CognitiveServices/accounts', 'Microsoft.Search/searchServices',
                    'Microsoft.DocumentDB/databaseAccounts')) {
        Assert-Equal $resource.properties.disableLocalAuth $true "$type local auth disabled"
    }
    if ($type -eq 'Microsoft.Storage/storageAccounts') {
        Assert-Equal $resource.properties.allowSharedKeyAccess $false 'Storage shared key access'
        Assert-Equal $resource.sku.name 'Standard_LRS' 'Storage SKU'
    }
    if ($type -eq 'Microsoft.Search/searchServices') {
        Assert-Equal $resource.sku.name 'basic' 'Search SKU'
    }
    if ($type -eq 'Microsoft.DocumentDB/databaseAccounts') {
        Assert-Equal ($resource.properties.capabilities.name -contains 'EnableServerless') $true 'Cosmos Serverless'
    }
    if ($type -eq 'Microsoft.CognitiveServices/accounts') {
        $account = $resource
        Assert-Equal $resource.properties.networkInjections[0].scenario 'agent' 'Foundry network injection'
    }
}

$endpoints = Invoke-AzJson -Arguments @('network', 'private-endpoint', 'list', '--resource-group', $ResourceGroup)
Assert-Equal @($endpoints).Count 6 'Private Endpoint count'
foreach ($endpoint in $endpoints) {
    Assert-Equal $endpoint.provisioningState 'Succeeded' "$($endpoint.name) provisioning"
    Assert-Equal $endpoint.privateLinkServiceConnections[0].privateLinkServiceConnectionState.status 'Approved' "$($endpoint.name) approval"
}

$zones = Invoke-AzJson -Arguments @('network', 'private-dns', 'zone', 'list', '--resource-group', $ResourceGroup)
Assert-Equal @($zones).Count 8 'Private DNS zone count'
$vm = Invoke-AzJson -Arguments @('vm', 'show', '--resource-group', $ResourceGroup, '--name', 'vm-genius-jump')
Assert-Equal $vm.provisioningState 'Succeeded' 'Linux VM provisioning'
Assert-Equal $vm.storageProfile.osDisk.osType 'Linux' 'Jump host OS'
$nic = Invoke-AzJson -Arguments @('network', 'nic', 'show', '--resource-group', $ResourceGroup, '--name', 'nic-genius-jump')
Assert-Equal (@($nic.ipConfigurations | Where-Object { $_.publicIPAddress }).Count) 0 'Jump host public IP count'
$bastion = Invoke-AzJson -Arguments @('network', 'bastion', 'show', '--resource-group', $ResourceGroup, '--name', 'bas-genius-krc')
Assert-Equal $bastion.sku.name 'Standard' 'Bastion SKU'
Assert-Equal $bastion.enableTunneling $true 'Bastion native tunnel'
Assert-Equal $bastion.provisioningState 'Succeeded' 'Bastion provisioning'
$model = Invoke-AzJson -Arguments @(
    'cognitiveservices', 'account', 'deployment', 'show',
    '--resource-group', $ResourceGroup, '--name', $account.name, '--deployment-name', 'gpt-5.6-terra'
)
Assert-Equal $model.properties.provisioningState 'Succeeded' 'Model provisioning'
Assert-Equal $model.sku.name 'GlobalStandard' 'Model SKU'
$capabilityUrl = "https://management.azure.com$($account.id)/projects/learning/capabilityHosts/agents?api-version=2025-04-01-preview"
$capability = Invoke-AzJson -Arguments @('rest', '--method', 'get', '--url', $capabilityUrl)
Assert-Equal $capability.properties.provisioningState 'Succeeded' 'Agent capability host'
Write-Output 'Management-plane verification finished. DNS, SSH/SOCKS and data-plane flows require separate tests.'
