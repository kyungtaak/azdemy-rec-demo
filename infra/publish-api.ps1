param(
    [Parameter(Mandatory)][string]$Package,
    [Parameter(Mandatory)][string]$ApiName,
    [string]$Proxy = 'socks5h://127.0.0.1:1080',
    [ValidateSet('az', 'azd')][string]$AuthCli = 'az'
)

$ErrorActionPreference = 'Stop'
$packagePath = (Resolve-Path -LiteralPath $Package).Path
$started = [datetime]::UtcNow
$token = $null
try {
    $token = if ($AuthCli -eq 'azd') {
        azd auth token --scope https://management.azure.com/.default --no-prompt
    } else {
        az account get-access-token --resource https://management.azure.com --query accessToken -o tsv
    }
    if ($LASTEXITCODE -ne 0) { throw 'ARM token acquisition failed' }
    $token = ($token -join '').Trim()
    if (-not $token) { throw 'Empty ARM access token' }
    "header = `"Authorization: Bearer $token`"" | curl.exe --config - --proxy $Proxy `
        --connect-timeout 30 --max-time 300 --silent --show-error --fail-with-body `
        --request POST --header 'Content-Type: application/zip' --data-binary "@$packagePath" `
        "https://$ApiName.scm.azurewebsites.net/api/zipdeploy?isAsync=false"
    if ($LASTEXITCODE -ne 0) { throw 'Private ZIP deployment failed' }
    $result = "header = `"Authorization: Bearer $token`"" | curl.exe --config - --proxy $Proxy `
        --max-time 60 --silent --show-error --fail-with-body `
        "https://$ApiName.scm.azurewebsites.net/api/deployments/latest"
    if ($LASTEXITCODE -ne 0) { throw 'Cannot verify private ZIP deployment' }
    $deployment = $result | ConvertFrom-Json
    if ($deployment.status -ne 4 -or -not $deployment.complete -or
        [datetime]$deployment.received_time -lt $started.AddSeconds(-5)) {
        throw "The submitted deployment is not complete: $($deployment.id)"
    }
    $deployment | Select-Object id, status, complete, active, start_time, end_time | ConvertTo-Json
} finally {
    $token = $null
}
