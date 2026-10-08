[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Assets = Join-Path $ProjectRoot 'assets'
$Output = Join-Path $Assets 'jarvislocal-control-center.ico'
[System.IO.Directory]::CreateDirectory($Assets) | Out-Null

$Bitmap = [System.Drawing.Bitmap]::new(256, 256, [System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
$Graphics = [System.Drawing.Graphics]::FromImage($Bitmap)
$Graphics.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
$Graphics.TextRenderingHint = [System.Drawing.Text.TextRenderingHint]::AntiAliasGridFit
$Graphics.Clear([System.Drawing.Color]::Transparent)

$Path = [System.Drawing.Drawing2D.GraphicsPath]::new()
$Radius = 48.0
$Path.AddArc(8, 8, $Radius, $Radius, 180, 90)
$Path.AddArc(200, 8, $Radius, $Radius, 270, 90)
$Path.AddArc(200, 200, $Radius, $Radius, 0, 90)
$Path.AddArc(8, 200, $Radius, $Radius, 90, 90)
$Path.CloseFigure()
$Graphics.FillPath([System.Drawing.SolidBrush]::new([System.Drawing.Color]::FromArgb(255, 17, 20, 22)), $Path)
$Graphics.DrawPath([System.Drawing.Pen]::new([System.Drawing.Color]::FromArgb(255, 115, 122, 128), 8), $Path)
$Graphics.DrawEllipse([System.Drawing.Pen]::new([System.Drawing.Color]::FromArgb(255, 52, 58, 63), 6), 49, 49, 158, 158)

$Font = [System.Drawing.Font]::new('Segoe UI', 132, [System.Drawing.FontStyle]::Bold, [System.Drawing.GraphicsUnit]::Pixel)
$Format = [System.Drawing.StringFormat]::new()
$Format.Alignment = [System.Drawing.StringAlignment]::Center
$Format.LineAlignment = [System.Drawing.StringAlignment]::Center
$Graphics.DrawString('J', $Font, [System.Drawing.Brushes]::White, [System.Drawing.RectangleF]::new(47, 49, 162, 166), $Format)
$Graphics.FillEllipse([System.Drawing.SolidBrush]::new([System.Drawing.Color]::FromArgb(255, 141, 148, 154)), 180, 54, 22, 22)

$PngStream = [System.IO.MemoryStream]::new()
$Bitmap.Save($PngStream, [System.Drawing.Imaging.ImageFormat]::Png)
$PngBytes = $PngStream.ToArray()
$File = [System.IO.File]::Open($Output, [System.IO.FileMode]::Create, [System.IO.FileAccess]::Write)
$Writer = [System.IO.BinaryWriter]::new($File)
$Writer.Write([uint16]0)
$Writer.Write([uint16]1)
$Writer.Write([uint16]1)
$Writer.Write([byte]0)
$Writer.Write([byte]0)
$Writer.Write([byte]0)
$Writer.Write([byte]0)
$Writer.Write([uint16]1)
$Writer.Write([uint16]32)
$Writer.Write([uint32]$PngBytes.Length)
$Writer.Write([uint32]22)
$Writer.Write($PngBytes)
$Writer.Dispose()
$File.Dispose()
$PngStream.Dispose()
$Format.Dispose()
$Font.Dispose()
$Path.Dispose()
$Graphics.Dispose()
$Bitmap.Dispose()

$Icon = [System.Drawing.Icon]::new($Output)
$Icon.Dispose()
Write-Host "Icono creado y validado: $Output"
