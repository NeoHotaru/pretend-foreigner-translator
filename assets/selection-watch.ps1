param([int]$OwnerProcess,[string]$WindowPrefix='')
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
try {
    Add-Type -AssemblyName UIAutomationClient
    Add-Type -AssemblyName UIAutomationTypes
    Add-Type -AssemblyName System.Web.Extensions
    $frameworkFolder = [System.Runtime.InteropServices.RuntimeEnvironment]::GetRuntimeDirectory()
    $references = @(
        (Join-Path $frameworkFolder 'WPF/UIAutomationClient.dll'),
        (Join-Path $frameworkFolder 'WPF/UIAutomationTypes.dll'),
        (Join-Path $frameworkFolder 'WPF/WindowsBase.dll'),
        (Join-Path $frameworkFolder 'System.Web.Extensions.dll')
    )
    Add-Type -Path (Join-Path $PSScriptRoot 'selection-bridge.cs') -ReferencedAssemblies $references
    [PftSelection]::Watch($OwnerProcess,$WindowPrefix)
} catch {
    [Console]::WriteLine('{"type":"error"}')
    exit 1
}
