<#
Deploys this P: working tree onto the C: copy that shortcuts and the
HKCU\...\Run\GPU Monitor autostart entry actually launch.

That C: folder is a deployment target, not a workshop: nobody edits a
file there by hand. Run this after committing a change here, then close
and relaunch GPU_Monitor.bat so the running card picks up the new files
-- Python does not hot-reload.

.git is deliberately excluded: C: carries no git history of its own
since the 2026-09-13 cutover (P: and GitHub are the only two copies of
that history). _backups, tests\_scratch_appdata and docs\_shot_appdata
are P:'s own local/scratch state and have no business overwriting
whatever C: is holding.
#>

$ErrorActionPreference = "Stop"

$Source = Split-Path -Parent $PSScriptRoot
$Dest = "C:\IA\Tools\Apps\GPU_Monitor"

if (-not (Test-Path $Dest)) {
    throw "C: deployment target is missing: $Dest -- this is not a first install, stopping rather than guessing."
}

robocopy $Source $Dest /E /COPY:DAT /DCOPY:DAT /R:2 /W:2 /XJ `
    /XD ".git" "__pycache__" "_scratch_appdata" "_shot_appdata" `
    /NP /TEE

$code = $LASTEXITCODE
if ($code -ge 8) {
    throw "robocopy reported a failure (exit $code) -- inspect the output above before trusting the C: copy."
}

Write-Host ""
Write-Host "Deployed to $Dest (robocopy exit $code, 0-7 is non-fatal)."
Write-Host "Close the running card properly and relaunch GPU_Monitor.bat to pick this up."
