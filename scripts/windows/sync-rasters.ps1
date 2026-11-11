<#
.SYNOPSIS
  Sends rasters (GeoTIFF/COG, VRT, .ovr) from a local folder to the Sophia server.

.DESCRIPTION
  Target is derived from the local folder:
    * library     E:\gis\rasters\<series>\...        -> /opt/sophia/data/rasters/<series>/...
    * project     <project folder>\rastry\<name>\... -> /opt/sophia/data/projects/<slug>/rastry/<name>/...
      (project folder = nearest parent folder with a .qgz/.qgs file; slug = -Project or the .qgz name)
  Same relative paths on both sides, so ./rastry/... and ../../rasters/... in the QGIS project work.

  Only new or changed files are sent (size + MD5). Each file is uploaded under a temporary name
  and renamed on the server, so QGIS Server never reads a half-sent file.
  Afterwards QGIS Server is restarted (it caches open rasters and invalid layers); when a file was
  replaced or deleted, the tile cache is purged too (cached tiles would show the old image).

  Files on the server that are missing locally are only listed; -Delete removes them.

.EXAMPLE
  .\sync-rasters.ps1 -Source E:\gis\archiwalne\schmettau\rastry\sbbschmettau -DryRun
.EXAMPLE
  .\sync-rasters.ps1 -Source E:\gis\rasters\tk25
.EXAMPLE
  .\sync-rasters.ps1 -Source E:\gis\archiwalne\schmettau\rastry\sbbschmettau -Project schmettau -Delete
#>
param(
    [Parameter(Mandatory = $true)][string]$Source,
    [string]$Project = "",
    [string]$LibraryRoot = "E:\gis\rasters",
    [string]$SshHost = "sophia",
    [string]$RemoteRoot = "/opt/sophia",
    [switch]$DryRun,
    [switch]$Delete,
    [switch]$NoRestart
)

$ErrorActionPreference = "Stop"
$Extensions = @(".tif", ".tiff", ".vrt", ".ovr", ".jp2", ".msk")

function Fail([string]$msg) { Write-Host "ERROR: $msg" -ForegroundColor Red; exit 1 }

function Remote([string]$cmd) {
    # PowerShell 5.1: stderr of a native program (docker compose progress) becomes an error record;
    # with ErrorActionPreference=Stop that would abort the script - judge by the exit code instead.
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try { $out = & ssh -o BatchMode=yes $SshHost $cmd 2>&1 | ForEach-Object { "$_" } }
    finally { $ErrorActionPreference = $prev }
    if ($LASTEXITCODE -ne 0) { Fail "ssh: $cmd`n$($out -join "`n")" }
    return $out
}

function Quote([string]$s) { return "'" + $s.Replace("'", "'\''") + "'" }

# ------------------------------------------------------------------ source and target
$src = (Resolve-Path -LiteralPath $Source -ErrorAction SilentlyContinue)
if (-not $src) { Fail "Folder not found: $Source" }
$src = $src.Path.TrimEnd("\")
if (-not (Test-Path -LiteralPath $src -PathType Container)) { Fail "Not a folder: $src" }

$libRoot = $LibraryRoot.TrimEnd("\")
if ($src.StartsWith($libRoot + "\", [StringComparison]::OrdinalIgnoreCase)) {
    $rel = $src.Substring($libRoot.Length + 1).Replace("\", "/")
    $dest = "data/rasters/$rel"
    $kind = "library"
} else {
    $dir = Get-Item -LiteralPath $src
    $projDir = $null
    while ($dir -ne $null) {
        if (Get-ChildItem -LiteralPath $dir.FullName -File | Where-Object { $_.Extension -in ".qgz", ".qgs" }) { $projDir = $dir; break }
        $dir = $dir.Parent
    }
    if (-not $projDir) { Fail "No .qgz/.qgs in $src or its parents - use a folder inside a project or under $libRoot" }
    if (-not $Project) {
        $qgz = Get-ChildItem -LiteralPath $projDir.FullName -File | Where-Object { $_.Extension -in ".qgz", ".qgs" } | Select-Object -First 1
        $Project = [IO.Path]::GetFileNameWithoutExtension($qgz.Name).ToLower()
    }
    if ($Project -notmatch '^[a-z0-9][a-z0-9_-]*$') { Fail "Invalid project slug '$Project' - pass -Project <slug> (as in the Sophia URL ?p=...)" }
    $exists = Remote "test -d $RemoteRoot/data/projects/$Project && echo yes || echo no"
    if (($exists | Select-Object -Last 1) -ne "yes") { Fail "Project '$Project' not published on the server - publish it with Fia first, or pass -Project <slug>" }
    if ($src.Length -le $projDir.FullName.Length) { Fail "Pick a raster subfolder of the project (e.g. rastry\...), not the project folder itself" }
    $rel = $src.Substring($projDir.FullName.TrimEnd("\").Length + 1).Replace("\", "/")
    $dest = "data/projects/$Project/$rel"
    $kind = "project '$Project'"
}
$remoteDir = "$RemoteRoot/$dest"
Write-Host "Source: $src"
Write-Host "Target: ${SshHost}:$remoteDir  ($kind)"

# ------------------------------------------------------------------ compare
$local = @{}
Get-ChildItem -LiteralPath $src -File -Recurse | Where-Object { $Extensions -contains $_.Extension.ToLower() } | ForEach-Object {
    $r = $_.FullName.Substring($src.Length + 1).Replace("\", "/")
    $local[$r] = $_
}
if ($local.Count -eq 0) { Fail "No raster files ($($Extensions -join ', ')) in $src" }

$remote = @{}
$listing = Remote "cd $(Quote $remoteDir) 2>/dev/null && find . -type f ! -name '*.part' -exec md5sum {} + 2>/dev/null; true"
foreach ($line in $listing) {
    if ($line -match '^([0-9a-f]{32})\s+\./(.+)$') { $remote[$Matches[2]] = $Matches[1] }
}

$toSend = @()
$replaced = 0
foreach ($r in ($local.Keys | Sort-Object)) {
    if ($remote.ContainsKey($r)) {
        $md5 = (Get-FileHash -LiteralPath $local[$r].FullName -Algorithm MD5).Hash.ToLower()
        if ($md5 -eq $remote[$r]) { continue }
        $replaced++
    }
    $toSend += $r
}
$extra = @($remote.Keys | Where-Object { -not $local.ContainsKey($_) -and $Extensions -contains [IO.Path]::GetExtension($_).ToLower() } | Sort-Object)

$sendMB = [math]::Round((($toSend | ForEach-Object { $local[$_].Length }) | Measure-Object -Sum).Sum / 1MB, 1)
Write-Host ("Local files: {0}, on server: {1}, to send: {2} ({3} MB, {4} replaced), only on server: {5}" -f `
    $local.Count, $remote.Count, $toSend.Count, $sendMB, $replaced, $extra.Count)
foreach ($r in $toSend) { Write-Host ("  send    {0}  ({1} MB)" -f $r, [math]::Round($local[$r].Length / 1MB, 1)) }
foreach ($r in $extra) { Write-Host ("  {0}  {1}" -f $(if ($Delete) { "delete " } else { "extra  " }), $r) }

if ($DryRun) { Write-Host "Dry run - nothing changed."; exit 0 }
if ($toSend.Count -eq 0 -and (-not $Delete -or $extra.Count -eq 0)) { Write-Host "Server is up to date."; exit 0 }

# ------------------------------------------------------------------ upload
# Folder may belong to root (created by the API on publish): prepare it through the api container.
$apiPath = $remoteDir.Replace("$RemoteRoot/data/projects", "/projects")
if ($kind -like "project*") {
    Remote "cd $RemoteRoot && docker compose exec -T api sh -c $(Quote "mkdir -p '$apiPath' && chown -R 1000:1000 '$apiPath'")" | Out-Null
} else {
    Remote "mkdir -p $(Quote $remoteDir)" | Out-Null
}
$dirs = @($toSend | ForEach-Object { Split-Path $_ -Parent } | Where-Object { $_ } | Sort-Object -Unique | ForEach-Object { "$remoteDir/" + $_.Replace("\", "/") })
if ($dirs.Count) { Remote ("mkdir -p " + (($dirs | ForEach-Object { Quote $_ }) -join " ")) | Out-Null }

$i = 0
foreach ($r in $toSend) {
    $i++
    $f = $local[$r]
    $target = "$remoteDir/$r"
    $part = "$target.part"
    Write-Host ("[{0}/{1}] {2} ({3} MB)" -f $i, $toSend.Count, $r, [math]::Round($f.Length / 1MB, 1))
    & scp -q -o BatchMode=yes $f.FullName "${SshHost}:$part"
    if ($LASTEXITCODE -ne 0) { Fail "scp failed for $r" }
    Remote "mv -f $(Quote $part) $(Quote $target)" | Out-Null
}
if ($Delete -and $extra.Count) {
    Remote ("rm -f " + (($extra | ForEach-Object { Quote "$remoteDir/$_" }) -join " ")) | Out-Null
    Write-Host "Deleted on server: $($extra.Count)"
}

# ------------------------------------------------------------------ QGIS Server, tile cache
if ($NoRestart) { Write-Host "Done (QGIS Server not restarted: -NoRestart)."; exit 0 }
Write-Host "Restarting QGIS Server..."
Remote "cd $RemoteRoot && docker compose restart qgis" | Out-Null
if ($replaced -gt 0 -or ($Delete -and $extra.Count -gt 0)) {
    Write-Host "Purging tile cache (files were replaced or deleted)..."
    Remote "cd $RemoteRoot && docker compose exec -T tilecache sh -c 'rm -rf /var/cache/tiles/*'" | Out-Null
}
Write-Host "Done." -ForegroundColor Green
