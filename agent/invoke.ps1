param(
    [Parameter(Mandatory)][string]$Message,
    [Parameter(Mandatory)][string]$OutputFile,
    [string]$AgentName = 'education-consultant',
    [string]$AgentVersion = '6',
    [string]$ProjectEndpoint = 'https://geniusmda53gutai.services.ai.azure.com/api/projects/learning',
    [string]$Proxy = 'socks5h://127.0.0.1:1080',
    [switch]$Stream,
    [ValidateSet('az', 'azd')][string]$AuthCli = 'az'
)

$ErrorActionPreference = 'Stop'
$requestFile = [System.IO.Path]::GetTempFileName()
$token = $null
try {
    @{
        input = $Message
        agent = @{type = 'agent_reference'; name = $AgentName; version = $AgentVersion}
        stream = [bool]$Stream
    } | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $requestFile -Encoding utf8
    $token = if ($AuthCli -eq 'azd') {
        azd auth token --scope https://ai.azure.com/.default --no-prompt
    } else {
        az account get-access-token --resource https://ai.azure.com --query accessToken -o tsv
    }
    if ($LASTEXITCODE -ne 0) { throw 'Foundry token acquisition failed' }
    $token = ($token -join '').Trim()
    if (-not $token) { throw 'Empty Foundry access token' }
    "header = `"Authorization: Bearer $token`"" | curl.exe --config - --proxy $Proxy `
        --connect-timeout 30 --max-time 240 --silent --show-error --fail-with-body `
        --request POST --header 'Content-Type: application/json' --data-binary "@$requestFile" `
        "$ProjectEndpoint/openai/responses?api-version=2025-11-15-preview" `
        --output $OutputFile --write-out "Foundry response HTTP %{http_code}`n"
    if ($LASTEXITCODE -ne 0) { throw "Foundry invocation failed; inspect $OutputFile" }
    if ($Stream) {
        $terminal = @(Get-Content -LiteralPath $OutputFile | Where-Object {
            $_.StartsWith('data: ')
        } | ForEach-Object {
            $_.Substring(6) | ConvertFrom-Json
        } | Where-Object { $_.type -in @('response.completed', 'response.failed', 'response.incomplete') })
        if ($terminal.Count -ne 1) { throw "No unique terminal response; inspect $OutputFile" }
        $response = $terminal[0].response
    } else {
        $response = Get-Content -LiteralPath $OutputFile -Raw | ConvertFrom-Json
    }
    if ($response.status -ne 'completed' -or $response.error) {
        throw "Agent response did not complete: $($response.status); inspect $OutputFile"
    }
    [ordered]@{
        id = $response.id
        status = $response.status
        error = $response.error
        toolCalls = @($response.output | Where-Object type -eq 'openapi_call' |
            Select-Object type, name, status, arguments)
        toolResults = @($response.output | Where-Object type -eq 'openapi_call_output' |
            Select-Object name, status)
        answer = @($response.output | Where-Object type -eq 'message' |
            ForEach-Object { $_.content } | Where-Object type -eq 'output_text' |
            ForEach-Object { $_.text })
        usage = $response.usage
    } | ConvertTo-Json -Depth 15
} finally {
    $token = $null
    Remove-Item -LiteralPath $requestFile
}
