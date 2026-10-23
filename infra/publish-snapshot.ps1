param(
    [Parameter(Mandatory)][string]$State,
    [Parameter(Mandatory)][string]$ApiName,
    [string]$Export,
    [string]$Python = '.\.venv\Scripts\python.exe',
    [ValidateSet('az', 'azd')][string]$AuthCli = 'az',
    [switch]$Rollback
)

$ErrorActionPreference = 'Stop'
if ($Rollback) {
    & $Python -m fabric.run rollback --state $State --auth-cli $AuthCli --api-name $ApiName
} else {
    if (-not $Export) { throw 'Export is required for publication' }
    & $Python -m fabric.run publish --state $State --auth-cli $AuthCli --api-name $ApiName --output $Export
}
if ($LASTEXITCODE -ne 0) { throw 'Snapshot staging failed; activation was not confirmed' }
az webapp restart --subscription b214e225-c96c-489e-a778-a1f25bd40cdb `
    --resource-group rg-azdemy-rec-demo-krc --name $ApiName --only-show-errors
if ($LASTEXITCODE -ne 0) { throw 'API restart failed; inspect the staged request before retrying' }
& $Python -m fabric.run confirm --state $State --auth-cli $AuthCli --api-name $ApiName
if ($LASTEXITCODE -ne 0) { throw 'Snapshot activation was not confirmed; inspect its request receipt' }
