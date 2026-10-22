param(
    [Parameter(Mandatory)][string]$ApiClientId,
    [string]$Python = '.\.venv\Scripts\python.exe',
    [string]$AgentName = 'education-consultant',
    [string]$ProjectEndpoint = 'https://geniusmda53gutai.services.ai.azure.com/api/projects/learning',
    [string]$Proxy = 'socks5h://127.0.0.1:1080',
    [ValidateSet('az', 'azd')][string]$AuthCli = 'az'
)

$ErrorActionPreference = 'Stop'
$requestFile = [System.IO.Path]::GetTempFileName()
$responseFile = [System.IO.Path]::GetTempFileName()
$token = $null
try {
    & $Python -m agent.build_definition --api-client-id $ApiClientId --output $requestFile
    if ($LASTEXITCODE -ne 0) { throw 'Agent definition validation failed' }
    $token = if ($AuthCli -eq 'azd') {
        azd auth token --scope https://ai.azure.com/.default --no-prompt
    } else {
        az account get-access-token --resource https://ai.azure.com --query accessToken -o tsv
    }
    if ($LASTEXITCODE -ne 0) { throw 'Foundry token acquisition failed' }
    $token = ($token -join '').Trim()
    if (-not $token) { throw 'Empty Foundry access token' }
    "header = `"Authorization: Bearer $token`"" | curl.exe --config - --proxy $Proxy `
        --connect-timeout 30 --max-time 120 --silent --show-error --fail-with-body `
        --request POST --header 'Content-Type: application/json' --data-binary "@$requestFile" `
        "$ProjectEndpoint/agents/$AgentName/versions?api-version=2025-11-15-preview" `
        --output $responseFile
    if ($LASTEXITCODE -ne 0) {
        Get-Content -LiteralPath $responseFile
        throw 'Private Prompt Agent publication failed'
    }
    $agent = Get-Content -LiteralPath $responseFile -Raw | ConvertFrom-Json
    $agent | Select-Object id, name, version, instance_identity | ConvertTo-Json -Depth 5
} finally {
    $token = $null
    Remove-Item -LiteralPath $requestFile
    Remove-Item -LiteralPath $responseFile
}
