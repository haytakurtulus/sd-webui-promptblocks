# PromptBlocks diagnostics: read-only memory + activity logger for a Forge session.
# Changes nothing in Forge or Windows. Start it before (or while) Forge runs; stop with Ctrl+C or close the window.
#
# Output folder: <extension>\data\diagnostics\ (gitignored: may contain LoRA names)
#   samples-YYYY-MM-DD.csv : one row every $Seconds s (Forge memory, system commit, GPU)
#   events-YYYY-MM-DD.log  : what happened (Forge start/stop, generation start from params.txt with
#                            size / steps / batch / model / LoRAs / ADetailer, images saved, low-memory
#                            warnings from Windows, commit crossing a danger line, top memory users)
# Manual note:  powershell -File memlog.ps1 -Note "test A started"
param(
    [int]$Seconds = 3,
    [int]$MaxHours = 12,
    [double]$WarnCommitGB = 33,
    [string]$Note = ""
)

$ErrorActionPreference = "SilentlyContinue"
$ext = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent       # ...\extensions\sd-promptblocks
$forge = Split-Path (Split-Path $ext -Parent) -Parent              # ...\stable-diffusion-webui-forge
$outDir = Join-Path $ext "data\diagnostics"
New-Item -ItemType Directory -Force -Path $outDir | Out-Null
$utf8 = New-Object System.Text.UTF8Encoding($false)

function Day { Get-Date -Format "yyyy-MM-dd" }
function Now { Get-Date -Format "HH:mm:ss" }
function Write-Event([string]$kind, [string]$text) {
    $line = "$(Day) $(Now) [$kind] $text"
    [IO.File]::AppendAllText((Join-Path $outDir "events-$(Day).log"), $line + "`r`n", $utf8)
    Write-Host $line
}

if ($Note) { Write-Event "NOTE" $Note; exit 0 }

function Write-Sample([string]$row) {
    $f = Join-Path $outDir "samples-$(Day).csv"
    if (-not (Test-Path $f)) {
        [IO.File]::AppendAllText($f, "time,forge_pid,forge_private_gb,forge_ws_gb,free_ram_gb,commit_gb,commit_limit_gb,gpu_used_mb,gpu_util,gpu_temp_c`r`n", $utf8)
    }
    [IO.File]::AppendAllText($f, $row + "`r`n", $utf8)
}

function Get-ForgePid {
    $c = Get-NetTCPConnection -State Listen -LocalPort 7860 | Select-Object -First 1
    if ($c) { return [int]$c.OwningProcess }
    return $null
}

function Get-Loras([string]$text) {
    # "<lora:name:0.8>" -> "name:0.8", in prompt order (Forge compares the LoRA list in this order)
    $m = [regex]::Matches($text, "<lora:([^:>]+)(?::([^:>]+))?[^>]*>")
    $list = foreach ($x in $m) { if ($x.Groups[2].Success) { "$($x.Groups[1].Value):$($x.Groups[2].Value)" } else { "$($x.Groups[1].Value):1" } }
    if ($list) { return ($list -join ", ") }
    return "-"
}

function Get-Param([string]$line, [string]$key) {
    $m = [regex]::Match($line, "(?:^|, )" + [regex]::Escape($key) + ': ("(?:[^"\\]|\\.)*"|[^,]*)')
    if ($m.Success) { return $m.Groups[1].Value.Trim('"') }
    return $null
}

function Describe-Params([string]$path) {
    $lines = [IO.File]::ReadAllLines($path, $utf8)
    if ($lines.Count -eq 0) { return "params.txt empty" }
    $params = $lines[-1]
    $before = $lines[0..([Math]::Max(0, $lines.Count - 2))]
    $prompt = ($before | Where-Object { -not $_.StartsWith("Negative prompt:") }) -join " "
    if ($lines.Count -eq 1) { $prompt = "" }
    $parts = @()
    foreach ($k in "Size", "Steps", "Sampler", "Batch size", "Hires upscale", "Hires steps", "Denoising strength", "Model") {
        $v = Get-Param $params $k
        if ($v) { $parts += "$k=$v" }
    }
    $parts += "main LoRAs=[" + (Get-Loras $prompt) + "]"
    $adModels = @(); $adLoras = @(); $differs = $false
    $mainSet = Get-Loras $prompt
    foreach ($suffix in "", " 2nd", " 3rd", " 4th") {
        $model = Get-Param $params "ADetailer model$suffix"
        if (-not $model) { continue }
        $adModels += $model
        $adPrompt = Get-Param $params "ADetailer prompt$suffix"
        if ($adPrompt) {
            $l = Get-Loras ($adPrompt -replace '\\n', ' ')
            $adLoras += "$model=[$l]"
            if ($l -ne "-" -and $l -ne $mainSet) { $differs = $true }
        } else {
            $adLoras += "$model=[same as main]"
        }
    }
    if ($adModels.Count -gt 0) {
        $parts += "ADetailer: " + ($adLoras -join "; ")
        if ($differs) { $parts += "!! ADetailer LoRA set differs from main (Forge re-merges LoRAs twice per image)" }
    } else {
        $parts += "ADetailer off"
    }
    if ($params -match "PromptBlocks template") { $parts += "PromptBlocks used" }
    if ($params -match "PromptBlocks ADetailer") { $parts += "PromptBlocks ADetailer text" }
    return ($parts -join " | ")
}

function Get-TopMemory {
    (Get-Process | Sort-Object PrivateMemorySize64 -Descending | Select-Object -First 6 |
        ForEach-Object { "$($_.Name)=$([math]::Round($_.PrivateMemorySize64 / 1GB, 1))GB" }) -join ", "
}

$paramsPath = Join-Path $forge "params.txt"
$lastParams = if (Test-Path $paramsPath) { (Get-Item $paramsPath).LastWriteTime } else { $null }
$lastPid = $null
$lastImageCheck = Get-Date
$lastEventCheck = Get-Date
$lastTop = (Get-Date).AddMinutes(-10)
$overWarn = $false
$peak = 0.0
$end = (Get-Date).AddHours($MaxHours)

Write-Event "START" "logger started (every $Seconds s, max $MaxHours h, warn at commit >= $WarnCommitGB GB). Top memory: $(Get-TopMemory)"

while ((Get-Date) -lt $end) {
    # ---- Forge process ----
    $fpid = Get-ForgePid
    if ($fpid -ne $lastPid) {
        if ($fpid) { Write-Event "FORGE" "Forge running (pid $fpid)" } else { Write-Event "FORGE" "Forge stopped (was pid $lastPid); peak commit this run $peak GB" ; $peak = 0.0 }
        $lastPid = $fpid
    }
    $priv = ""; $ws = ""
    if ($fpid) {
        $p = Get-Process -Id $fpid
        if ($p) { $priv = [math]::Round($p.PrivateMemorySize64 / 1GB, 2); $ws = [math]::Round($p.WorkingSet64 / 1GB, 2) }
    }

    # ---- system memory / GPU ----
    $os = Get-CimInstance Win32_OperatingSystem
    $free = [math]::Round($os.FreePhysicalMemory / 1MB, 2)
    $mem = Get-CimInstance Win32_PerfFormattedData_PerfOS_Memory
    $commit = [math]::Round($mem.CommittedBytes / 1GB, 2)
    $limit = [math]::Round($mem.CommitLimit / 1GB, 2)
    if ($commit -gt $peak) { $peak = $commit }
    $gpu = ""; $util = ""; $temp = ""
    $g = (& nvidia-smi --query-gpu=memory.used,utilization.gpu,temperature.gpu --format=csv,noheader,nounits)
    if ($g) { $g = $g -split ","; $gpu = $g[0].Trim(); $util = $g[1].Trim(); $temp = $g[2].Trim() }
    Write-Sample "$(Now),$fpid,$priv,$ws,$free,$commit,$limit,$gpu,$util,$temp"

    if ($commit -ge $WarnCommitGB -and -not $overWarn) {
        Write-Event "DANGER" "commit $commit / $limit GB (Forge $priv GB). Top memory: $(Get-TopMemory)"
        $overWarn = $true
    } elseif ($commit -lt ($WarnCommitGB - 2) -and $overWarn) {
        Write-Event "OK" "commit back to $commit GB"
        $overWarn = $false
    }

    # ---- generation start: params.txt rewritten by Forge ----
    if (Test-Path $paramsPath) {
        $t = (Get-Item $paramsPath).LastWriteTime
        if ($t -ne $lastParams) {
            $lastParams = $t
            Write-Event "GEN" ("generation params: " + (Describe-Params $paramsPath) + " | commit now $commit GB")
        }
    }

    # ---- images saved since last check (today's output folders) ----
    if (((Get-Date) - $lastImageCheck).TotalSeconds -ge 10) {
        $since = $lastImageCheck; $lastImageCheck = Get-Date
        foreach ($tab in "txt2img-images", "img2img-images") {
            $dir = Join-Path $forge "outputs\$tab\$(Day)"
            if (Test-Path $dir) {
                $n = @(Get-ChildItem $dir -File | Where-Object { $_.LastWriteTime -gt $since }).Count
                if ($n -gt 0) { Write-Event "IMAGES" "$n new in $tab | commit $commit GB, Forge $priv GB" }
            }
        }
    }

    # ---- Windows low-memory warnings ----
    if (((Get-Date) - $lastEventCheck).TotalSeconds -ge 30) {
        $since = $lastEventCheck; $lastEventCheck = Get-Date
        $ev = Get-WinEvent -FilterHashtable @{ LogName = 'System'; Id = 2004; StartTime = $since } | Select-Object -First 1
        if ($ev) { Write-Event "WINDOWS" "low virtual memory warning (Resource-Exhaustion 2004). Top memory: $(Get-TopMemory)" }
    }

    # ---- top memory users every 5 minutes ----
    if (((Get-Date) - $lastTop).TotalMinutes -ge 5) {
        $lastTop = Get-Date
        Write-Event "TOP" (Get-TopMemory)
    }

    Start-Sleep -Seconds $Seconds
}
Write-Event "STOP" "logger stopped after $MaxHours h"
