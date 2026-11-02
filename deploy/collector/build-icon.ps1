# Rebuild the Collector icon using Windows drawing APIs; no extra dependencies.
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing

function New-RoundedTile {
    $path = [System.Drawing.Drawing2D.GraphicsPath]::new()
    $path.AddArc(12, 12, 88, 88, 180, 90)
    $path.AddArc(156, 12, 88, 88, 270, 90)
    $path.AddArc(156, 156, 88, 88, 0, 90)
    $path.AddArc(12, 156, 88, 88, 90, 90)
    $path.CloseFigure()
    return $path
}

$frames = @()
foreach ($size in @(16, 20, 24, 32, 40, 48, 64, 128, 256)) {
    # Render above target resolution so edges stay smooth at taskbar sizes.
    $canvas = [System.Drawing.Bitmap]::new(1024, 1024)
    $graphics = [System.Drawing.Graphics]::FromImage($canvas)
    $graphics.SmoothingMode = 'AntiAlias'
    $graphics.ScaleTransform(4, 4)
    $tile = New-RoundedTile
    $background = [System.Drawing.Drawing2D.LinearGradientBrush]::new(
        [System.Drawing.Point]::new(24, 12), [System.Drawing.Point]::new(224, 244),
        [System.Drawing.ColorTranslator]::FromHtml('#233E60'),
        [System.Drawing.ColorTranslator]::FromHtml('#101E34'))
    $graphics.FillPath($background, $tile)
    $white = [System.Drawing.SolidBrush]::new([System.Drawing.ColorTranslator]::FromHtml('#EDF7FF'))
    $teal = [System.Drawing.SolidBrush]::new([System.Drawing.ColorTranslator]::FromHtml('#46E0CB'))
    $body = [System.Drawing.SolidBrush]::new([System.Drawing.ColorTranslator]::FromHtml('#294C69'))
    $outline = [System.Drawing.Pen]::new($white, 8)
    $outline.StartCap = 'Round'
    $outline.EndCap = 'Round'
    $signal = [System.Drawing.Pen]::new($teal, 8)
    $signal.LineJoin = 'Round'
    $signal.StartCap = 'Round'
    $signal.EndCap = 'Round'

    # Stacked storage, with the original SCADA signal on its front face.
    $graphics.FillRectangle($body, 51, 78, 108, 103)
    $graphics.FillEllipse($body, 51, 163, 108, 36)
    $graphics.DrawLine($outline, 51, 78, 51, 181)
    $graphics.DrawLine($outline, 159, 78, 159, 181)
    $graphics.DrawArc($outline, 51, 163, 108, 36, 0, 180)
    $graphics.DrawArc($outline, 51, 118, 108, 36, 0, 180)
    $graphics.FillEllipse($white, 47, 56, 116, 44)
    if ($size -ge 24) {
        $points = [System.Drawing.PointF[]]@(
            [System.Drawing.PointF]::new(69, 116), [System.Drawing.PointF]::new(83, 116),
            [System.Drawing.PointF]::new(92, 104), [System.Drawing.PointF]::new(105, 129),
            [System.Drawing.PointF]::new(115, 114), [System.Drawing.PointF]::new(140, 114))
        $graphics.DrawLines($signal, $points)
    }
    # One bold outbound arrow remains readable even at 16 pixels.
    $arrow = [System.Drawing.PointF[]]@(
        [System.Drawing.PointF]::new(192, 70), [System.Drawing.PointF]::new(222, 103),
        [System.Drawing.PointF]::new(203, 103), [System.Drawing.PointF]::new(203, 185),
        [System.Drawing.PointF]::new(181, 185), [System.Drawing.PointF]::new(181, 103),
        [System.Drawing.PointF]::new(162, 103))
    $graphics.FillPolygon($teal, $arrow)

    $scaled = [System.Drawing.Bitmap]::new($size, $size)
    $outputGraphics = [System.Drawing.Graphics]::FromImage($scaled)
    $outputGraphics.InterpolationMode = 'HighQualityBicubic'
    $outputGraphics.PixelOffsetMode = 'HighQuality'
    $outputGraphics.DrawImage($canvas, 0, 0, $size, $size)
    $stream = [System.IO.MemoryStream]::new()
    $scaled.Save($stream, [System.Drawing.Imaging.ImageFormat]::Png)
    $frames += ,$stream.ToArray()
    if ($size -eq 256) { $scaled.Save((Join-Path $PSScriptRoot 'collector.png')) }
    foreach ($resource in @($stream, $outputGraphics, $scaled, $signal, $outline, $body, $teal, $white, $background, $tile, $graphics, $canvas)) {
        $resource.Dispose()
    }
}

$file = [System.IO.File]::Create((Join-Path $PSScriptRoot 'collector.ico'))
$writer = [System.IO.BinaryWriter]::new($file)
try {
    $writer.Write([uint16]0)
    $writer.Write([uint16]1)
    $writer.Write([uint16]$frames.Count)
    $offset = 6 + 16 * $frames.Count
    foreach ($index in 0..($frames.Count - 1)) {
        $size = @(16, 20, 24, 32, 40, 48, 64, 128, 256)[$index]
        $dimension = if ($size -eq 256) { 0 } else { $size }
        $writer.Write([byte]$dimension)
        $writer.Write([byte]$dimension)
        $writer.Write([uint16]0)
        $writer.Write([uint16]1)
        $writer.Write([uint16]32)
        $writer.Write([uint32]$frames[$index].Length)
        $writer.Write([uint32]$offset)
        $offset += $frames[$index].Length
    }
    foreach ($frame in $frames) { $writer.Write([byte[]]$frame) }
} finally { $writer.Dispose() }
