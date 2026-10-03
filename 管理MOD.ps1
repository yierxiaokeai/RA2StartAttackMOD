param(
    [ValidateSet('Enable', 'Disable')][string]$Action = 'Enable',
    [string]$GameDirectory = (Split-Path -Parent $PSScriptRoot),
    [ValidateSet('YR', 'RA2')][string]$Variant = 'YR',
    [switch]$Interactive
)
$ErrorActionPreference = 'Stop'

function Invoke-ModChange {
    $target = [IO.Path]::GetFullPath($GameDirectory).TrimEnd('\')
    $processNames = if ($Variant -eq 'YR') { @('gamemd', 'ra2md', 'yuri') } else { @('game', 'ra2') }
    if (Get-Process -Name $processNames -ErrorAction SilentlyContinue) {
        throw '请先退出红警2和尤里的复仇，再切换 MOD。'
    }
    if (-not (Test-Path -LiteralPath $target -PathType Container)) {
        throw "游戏目录不存在：$target"
    }
    $name = if ($Variant -eq 'YR') { '尤里的复仇' } else { '原版红警2' }
    $suffix = if ($Variant -eq 'YR') { 'md' } else { '' }
    $filenames = @("rules$suffix.ini", "ai$suffix.ini", "ra2$suffix.csf")
    $payload = Join-Path $PSScriptRoot "安装文件\$name"
    $filenames += @("art$suffix.ini", 'sgsticon.shp', 'gastrt.shp', 'ggstrt.shp')
    $engineName = if ($Variant -eq 'YR') { 'gamemd.exe' } else { 'game.exe' }
    if (Test-Path -LiteralPath (Join-Path $payload $engineName) -PathType Leaf) {
        $filenames += $engineName
    }
    $statePath = Join-Path $PSScriptRoot "state-$Variant.json"
    $state = $null
    if (Test-Path -LiteralPath $statePath) {
        $state = Get-Content -LiteralPath $statePath -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($state.gameDirectory -ne $target) {
            throw '此管理目录已经关联另一个游戏目录，请使用另一份安装包。'
        }
    }
    $stamp = [TimeZoneInfo]::ConvertTimeBySystemTimeZoneId([DateTime]::UtcNow, 'China Standard Time').ToString('yyyyMMdd-HHmmss-fff')
    if ($Action -eq 'Enable') {
        if ($state -and $state.active) { return 'MOD 已经启用。' }
        foreach ($file in $filenames) {
            if (-not (Test-Path -LiteralPath (Join-Path $payload $file) -PathType Leaf)) {
                throw "安装文件缺失：$file"
            }
        }
        $backup = Join-Path $PSScriptRoot "原文件备份\$Variant-$stamp"
        New-Item -ItemType Directory -Path $backup | Out-Null
        $originals = @()
        foreach ($file in $filenames) {
            $existing = Test-Path -LiteralPath (Join-Path $target $file) -PathType Leaf
            if ($existing) { Copy-Item -LiteralPath (Join-Path $target $file) -Destination (Join-Path $backup $file) }
            $originals += @{ name = $file; existed = $existing }
        }
        $newState = @{ gameDirectory = $target; variant = $Variant; active = $false; backupDirectory = $backup; originals = $originals; time = $stamp }
        $newState | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $statePath -Encoding UTF8
        $written = @()
        try {
            foreach ($file in $filenames) {
                Copy-Item -LiteralPath (Join-Path $payload $file) -Destination (Join-Path $target $file) -Force
                $written += $file
            }
        } catch {
            $failed = Join-Path $PSScriptRoot "安装失败保存\$Variant-$stamp"
            New-Item -ItemType Directory -Path $failed | Out-Null
            foreach ($file in $written) {
                Move-Item -LiteralPath (Join-Path $target $file) -Destination (Join-Path $failed $file)
            }
            foreach ($entry in $originals) {
                if ($entry.existed) { Copy-Item -LiteralPath (Join-Path $backup $entry.name) -Destination (Join-Path $target $entry.name) -Force }
            }
            throw
        }
        $newState.active = $true
        $newState | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $statePath -Encoding UTF8
        return "$name MOD 已启用；原文件已备份。"
    }
    if (-not $state -or -not $state.active) { return 'MOD 当前已停用。' }
    foreach ($entry in $state.originals) {
        if ($entry.name -notin $filenames) { throw '状态文件中的文件名异常，已停止。' }
        if ($entry.existed -and -not (Test-Path -LiteralPath (Join-Path $state.backupDirectory $entry.name) -PathType Leaf)) {
            throw "原文件备份缺失：$($entry.name)；未执行还原。"
        }
    }
    $archive = Join-Path $PSScriptRoot "停用时保存\$Variant-$stamp"
    New-Item -ItemType Directory -Path $archive | Out-Null
    foreach ($entry in $state.originals) {
        $activeFile = Join-Path $target $entry.name
        if (Test-Path -LiteralPath $activeFile -PathType Leaf) {
            Move-Item -LiteralPath $activeFile -Destination (Join-Path $archive $entry.name)
        }
        if ($entry.existed) {
            Copy-Item -LiteralPath (Join-Path $state.backupDirectory $entry.name) -Destination $activeFile
        }
    }
    $state.active = $false
    $state | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $statePath -Encoding UTF8
    return 'MOD 已停用并还原原文件；停用前的配置已保存。'
}

try {
    $message = Invoke-ModChange
    Write-Output $message
    if ($Interactive) {
        Add-Type -AssemblyName System.Windows.Forms
        [Windows.Forms.MessageBox]::Show($message, '开始进攻 MOD') | Out-Null
    }
} catch {
    if ($Interactive) {
        Add-Type -AssemblyName System.Windows.Forms
        [Windows.Forms.MessageBox]::Show($_.Exception.Message, '开始进攻 MOD') | Out-Null
    }
    throw
}
