# Creates shortcuts only; does not install packages or change Windows settings.
$ErrorActionPreference = 'Stop'
$courtRoot = Split-Path -Parent $PSScriptRoot
$courtPython = (Get-Command python -ErrorAction Stop).Source
$courtPythonw = Join-Path (Split-Path -Parent $courtPython) 'pythonw.exe'
if (-not (Test-Path -LiteralPath $courtPythonw)) { throw 'pythonw.exe was not found next to Python.' }
$courtDesktop = [Environment]::GetFolderPath('Desktop')
$courtShell = New-Object -ComObject WScript.Shell
foreach ($courtEntry in @(@{Name='猫皇朝堂';Args=''}, @{Name='猫皇朝堂设置';Args=' --configure'})) {
    $courtLink = $courtShell.CreateShortcut((Join-Path $courtDesktop ($courtEntry.Name + '.lnk')))
    $courtLink.TargetPath = $courtPythonw
    $courtLink.Arguments = '"' + (Join-Path $PSScriptRoot 'desktop_court.py') + '"' + $courtEntry.Args
    $courtLink.WorkingDirectory = $courtRoot
    $courtLink.Description = 'Google AI court: starts locally and opens in your browser.'
    $courtLink.IconLocation = $courtPythonw + ',0'
    $courtLink.Save()
}
Write-Output 'Desktop shortcuts created.'
