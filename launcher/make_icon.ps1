# Draws the K-Visa Law Assistant logo (passport with a taegeuk circle) and writes assets\kvisa.ico.
Add-Type -AssemblyName System.Drawing

$root = Split-Path -Parent $PSScriptRoot
New-Item -ItemType Directory -Force (Join-Path $root "assets") | Out-Null
$icoPath = Join-Path $root "assets\kvisa.ico"

function RoundedRect([single]$x, [single]$y, [single]$w, [single]$h, [single]$r) {
    $path = New-Object System.Drawing.Drawing2D.GraphicsPath
    $path.AddArc($x, $y, $r * 2, $r * 2, 180, 90)
    $path.AddArc($x + $w - $r * 2, $y, $r * 2, $r * 2, 270, 90)
    $path.AddArc($x + $w - $r * 2, $y + $h - $r * 2, $r * 2, $r * 2, 0, 90)
    $path.AddArc($x, $y + $h - $r * 2, $r * 2, $r * 2, 90, 90)
    $path.CloseFigure()
    return $path
}

$images = @()
foreach ($size in 16, 24, 32, 48, 64, 128, 256) {
    $s = [single]$size
    $bmp = New-Object System.Drawing.Bitmap $size, $size
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
    $g.Clear([System.Drawing.Color]::Transparent)
    $blue = [System.Drawing.ColorTranslator]::FromHtml("#0b3d91")
    $red = [System.Drawing.ColorTranslator]::FromHtml("#cd2e3a")
    $white = [System.Drawing.Color]::White
    $g.FillPath((New-Object System.Drawing.SolidBrush $blue), (RoundedRect ($s * 0.16) ($s * 0.06) ($s * 0.68) ($s * 0.88) ($s * 0.11)))
    # Taegeuk circle: white ring, red upper half, blue lower half.
    $cx = $s * 0.5; $cy = $s * 0.42; $r = $s * 0.19
    $g.FillEllipse((New-Object System.Drawing.SolidBrush $white), $cx - $r - $s * 0.03, $cy - $r - $s * 0.03, ($r + $s * 0.03) * 2, ($r + $s * 0.03) * 2)
    $g.FillPie((New-Object System.Drawing.SolidBrush $red), $cx - $r, $cy - $r, $r * 2, $r * 2, 180, 180)
    $g.FillPie((New-Object System.Drawing.SolidBrush $blue), $cx - $r, $cy - $r, $r * 2, $r * 2, 0, 180)
    $g.FillEllipse((New-Object System.Drawing.SolidBrush $red), $cx, $cy - $r / 2, $r, $r)
    $g.FillEllipse((New-Object System.Drawing.SolidBrush $blue), $cx - $r, $cy - $r / 2, $r, $r)
    $g.FillPath((New-Object System.Drawing.SolidBrush $white), (RoundedRect ($s * 0.31) ($s * 0.71) ($s * 0.38) ($s * 0.07) ($s * 0.03)))
    $g.Dispose()

    $stream = New-Object System.IO.MemoryStream
    $bmp.Save($stream, [System.Drawing.Imaging.ImageFormat]::Png)
    $images += , @($size, $stream.ToArray())
    $bmp.Dispose()
}

$out = New-Object System.IO.MemoryStream
$w = New-Object System.IO.BinaryWriter $out
$w.Write([UInt16]0); $w.Write([UInt16]1); $w.Write([UInt16]$images.Count)
$offset = 6 + 16 * $images.Count
foreach ($img in $images) {
    $dim = if ($img[0] -ge 256) { 0 } else { $img[0] }
    $w.Write([byte]$dim); $w.Write([byte]$dim); $w.Write([byte]0); $w.Write([byte]0)
    $w.Write([UInt16]1); $w.Write([UInt16]32)
    $w.Write([UInt32]$img[1].Length); $w.Write([UInt32]$offset)
    $offset += $img[1].Length
}
foreach ($img in $images) { $w.Write($img[1]) }
$w.Flush()
[System.IO.File]::WriteAllBytes($icoPath, $out.ToArray())
Write-Output "Icon written: $icoPath"
