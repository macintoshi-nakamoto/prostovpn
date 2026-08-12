param(
    [string]$Source = ""
)

$ErrorActionPreference = "Stop"

Add-Type -AssemblyName System.Drawing

$repoRoot = Split-Path -Parent $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($Source)) {
    $Source = Join-Path $repoRoot "branding/nexa-master-icon.png"
}

$sourcePath = (Resolve-Path -LiteralPath $Source).Path
$sourceImage = [System.Drawing.Image]::FromFile($sourcePath)

function Ensure-ParentDirectory([string]$Path) {
    $parent = Split-Path -Parent $Path
    if ($parent -and -not (Test-Path -LiteralPath $parent)) {
        New-Item -ItemType Directory -Force -Path $parent | Out-Null
    }
}

function New-SquareBitmap([int]$Size) {
    return [System.Drawing.Bitmap]::new(
        $Size,
        $Size,
        [System.Drawing.Imaging.PixelFormat]::Format32bppArgb
    )
}

function Set-HighQualityGraphics([System.Drawing.Graphics]$Graphics) {
    $Graphics.CompositingMode = [System.Drawing.Drawing2D.CompositingMode]::SourceOver
    $Graphics.CompositingQuality = [System.Drawing.Drawing2D.CompositingQuality]::HighQuality
    $Graphics.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
    $Graphics.PixelOffsetMode = [System.Drawing.Drawing2D.PixelOffsetMode]::HighQuality
    $Graphics.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::HighQuality
}

function New-ResizedBitmap([int]$Size, [bool]$Round = $false) {
    $bitmap = New-SquareBitmap $Size
    $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
    try {
        Set-HighQualityGraphics $graphics
        $graphics.Clear([System.Drawing.Color]::Transparent)

        if ($Round) {
            $clip = [System.Drawing.Drawing2D.GraphicsPath]::new()
            try {
                $clip.AddEllipse(0, 0, $Size, $Size)
                $graphics.SetClip($clip)
                $graphics.DrawImage($sourceImage, 0, 0, $Size, $Size)
                $graphics.ResetClip()
            }
            finally {
                $clip.Dispose()
            }
        }
        else {
            $graphics.DrawImage($sourceImage, 0, 0, $Size, $Size)
        }
    }
    finally {
        $graphics.Dispose()
    }

    return $bitmap
}

function Save-SquarePng([string]$RelativePath, [int]$Size, [bool]$Round = $false) {
    $path = Join-Path $repoRoot $RelativePath
    Ensure-ParentDirectory $path
    $bitmap = New-ResizedBitmap $Size $Round
    try {
        $bitmap.Save($path, [System.Drawing.Imaging.ImageFormat]::Png)
    }
    finally {
        $bitmap.Dispose()
    }
}

function Save-Wordmark([string]$RelativePath, [int]$Width, [int]$Height) {
    $path = Join-Path $repoRoot $RelativePath
    Ensure-ParentDirectory $path

    $bitmap = [System.Drawing.Bitmap]::new(
        $Width,
        $Height,
        [System.Drawing.Imaging.PixelFormat]::Format32bppArgb
    )
    $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
    try {
        Set-HighQualityGraphics $graphics
        $graphics.Clear([System.Drawing.Color]::Transparent)

        $iconSize = $Height
        $icon = New-ResizedBitmap $iconSize
        try {
            $graphics.DrawImage($icon, 0, 0, $iconSize, $iconSize)
        }
        finally {
            $icon.Dispose()
        }

        $fontSize = [Math]::Max(8, [Math]::Floor($Height * 0.54))
        $font = [System.Drawing.Font]::new(
            "Segoe UI",
            $fontSize,
            [System.Drawing.FontStyle]::Bold,
            [System.Drawing.GraphicsUnit]::Pixel
        )
        $brush = [System.Drawing.SolidBrush]::new([System.Drawing.Color]::White)
        $format = [System.Drawing.StringFormat]::new()
        try {
            $format.Alignment = [System.Drawing.StringAlignment]::Near
            $format.LineAlignment = [System.Drawing.StringAlignment]::Center
            $format.FormatFlags = [System.Drawing.StringFormatFlags]::NoWrap
            $textArea = [System.Drawing.RectangleF]::new(
                [single]($iconSize + [Math]::Max(5, $Height * 0.25)),
                0,
                [single]($Width - $iconSize - 4),
                [single]$Height
            )
            $graphics.DrawString("NEXA VPN", $font, $brush, $textArea, $format)
        }
        finally {
            $format.Dispose()
            $brush.Dispose()
            $font.Dispose()
        }

        $bitmap.Save($path, [System.Drawing.Imaging.ImageFormat]::Png)
    }
    finally {
        $graphics.Dispose()
        $bitmap.Dispose()
    }
}

function Save-Banner([string]$RelativePath, [int]$Width, [int]$Height) {
    $path = Join-Path $repoRoot $RelativePath
    Ensure-ParentDirectory $path

    $bitmap = [System.Drawing.Bitmap]::new(
        $Width,
        $Height,
        [System.Drawing.Imaging.PixelFormat]::Format32bppArgb
    )
    $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
    try {
        Set-HighQualityGraphics $graphics
        $graphics.Clear([System.Drawing.Color]::FromArgb(255, 3, 12, 48))

        $iconSize = [Math]::Floor($Height * 0.62)
        $iconX = [Math]::Floor($Width * 0.09)
        $iconY = [Math]::Floor(($Height - $iconSize) / 2)
        $icon = New-ResizedBitmap $iconSize
        try {
            $graphics.DrawImage($icon, $iconX, $iconY, $iconSize, $iconSize)
        }
        finally {
            $icon.Dispose()
        }

        $font = [System.Drawing.Font]::new(
            "Segoe UI",
            [Math]::Max(12, [Math]::Floor($Height * 0.16)),
            [System.Drawing.FontStyle]::Bold,
            [System.Drawing.GraphicsUnit]::Pixel
        )
        $brush = [System.Drawing.SolidBrush]::new([System.Drawing.Color]::White)
        $format = [System.Drawing.StringFormat]::new()
        try {
            $format.Alignment = [System.Drawing.StringAlignment]::Near
            $format.LineAlignment = [System.Drawing.StringAlignment]::Center
            $format.FormatFlags = [System.Drawing.StringFormatFlags]::NoWrap
            $textX = $iconX + $iconSize + [Math]::Floor($Width * 0.055)
            $textArea = [System.Drawing.RectangleF]::new(
                [single]$textX,
                0,
                [single]($Width - $textX - 4),
                [single]$Height
            )
            $graphics.DrawString("NEXA VPN", $font, $brush, $textArea, $format)
        }
        finally {
            $format.Dispose()
            $brush.Dispose()
            $font.Dispose()
        }

        $bitmap.Save($path, [System.Drawing.Imaging.ImageFormat]::Png)
    }
    finally {
        $graphics.Dispose()
        $bitmap.Dispose()
    }
}

function Get-PngBytes([int]$Size) {
    $bitmap = New-ResizedBitmap $Size
    $stream = [System.IO.MemoryStream]::new()
    try {
        $bitmap.Save($stream, [System.Drawing.Imaging.ImageFormat]::Png)
        return $stream.ToArray()
    }
    finally {
        $stream.Dispose()
        $bitmap.Dispose()
    }
}

function Save-Ico([string]$RelativePath, [int[]]$Sizes) {
    $path = Join-Path $repoRoot $RelativePath
    Ensure-ParentDirectory $path

    $images = @($Sizes | ForEach-Object {
        [PSCustomObject]@{ Size = $_; Bytes = Get-PngBytes $_ }
    })

    $stream = [System.IO.File]::Create($path)
    $writer = [System.IO.BinaryWriter]::new($stream)
    try {
        $writer.Write([uint16]0)
        $writer.Write([uint16]1)
        $writer.Write([uint16]$images.Count)

        $offset = 6 + (16 * $images.Count)
        foreach ($image in $images) {
            $dimension = if ($image.Size -ge 256) { 0 } else { $image.Size }
            $writer.Write([byte]$dimension)
            $writer.Write([byte]$dimension)
            $writer.Write([byte]0)
            $writer.Write([byte]0)
            $writer.Write([uint16]1)
            $writer.Write([uint16]32)
            $writer.Write([uint32]$image.Bytes.Length)
            $writer.Write([uint32]$offset)
            $offset += $image.Bytes.Length
        }

        foreach ($image in $images) {
            $writer.Write([byte[]]$image.Bytes)
        }
    }
    finally {
        $writer.Dispose()
        $stream.Dispose()
    }
}

function Write-BigEndianUInt32([System.IO.BinaryWriter]$Writer, [uint32]$Value) {
    $Writer.Write([byte](($Value -shr 24) -band 0xff))
    $Writer.Write([byte](($Value -shr 16) -band 0xff))
    $Writer.Write([byte](($Value -shr 8) -band 0xff))
    $Writer.Write([byte]($Value -band 0xff))
}

function Save-Icns([string]$RelativePath) {
    $path = Join-Path $repoRoot $RelativePath
    Ensure-ParentDirectory $path

    $entries = @(
        [PSCustomObject]@{ Type = "ic10"; Bytes = Get-PngBytes 1024 },
        [PSCustomObject]@{ Type = "ic09"; Bytes = Get-PngBytes 512 },
        [PSCustomObject]@{ Type = "ic08"; Bytes = Get-PngBytes 256 },
        [PSCustomObject]@{ Type = "ic07"; Bytes = Get-PngBytes 128 },
        [PSCustomObject]@{ Type = "icp6"; Bytes = Get-PngBytes 64 },
        [PSCustomObject]@{ Type = "icp5"; Bytes = Get-PngBytes 32 },
        [PSCustomObject]@{ Type = "icp4"; Bytes = Get-PngBytes 16 }
    )

    $totalLength = 8
    foreach ($entry in $entries) {
        $totalLength += 8 + $entry.Bytes.Length
    }

    $stream = [System.IO.File]::Create($path)
    $writer = [System.IO.BinaryWriter]::new($stream)
    try {
        $writer.Write([System.Text.Encoding]::ASCII.GetBytes("icns"))
        Write-BigEndianUInt32 $writer ([uint32]$totalLength)

        foreach ($entry in $entries) {
            $writer.Write([System.Text.Encoding]::ASCII.GetBytes($entry.Type))
            Write-BigEndianUInt32 $writer ([uint32](8 + $entry.Bytes.Length))
            $writer.Write([byte[]]$entry.Bytes)
        }
    }
    finally {
        $writer.Dispose()
        $stream.Dispose()
    }
}

try {
    Save-SquarePng "client/images/nexaBigLogo.png" 1024
    Save-SquarePng "client/images/icon.png" 256
    Save-SquarePng "deploy/data/linux/NexaVPN.png" 512
    Save-SquarePng "metadata/en-US/images/icon.png" 512
    Save-SquarePng "client/ios/app/launch.png" 1024
    Save-Wordmark "client/images/NexaVPN.png" 300 44

    $androidDensities = @{
        "ldpi" = 36
        "mdpi" = 48
        "hdpi" = 72
        "xhdpi" = 96
        "xxhdpi" = 144
        "xxxhdpi" = 192
    }
    foreach ($density in $androidDensities.Keys) {
        $size = $androidDensities[$density]
        Save-SquarePng "client/android/res/mipmap-$density/icon.png" $size
        Save-SquarePng "client/android/res/mipmap-$density/icon_round.png" $size $true
    }

    $androidForegrounds = @{
        "mdpi" = 108
        "hdpi" = 162
        "xhdpi" = 216
        "xxhdpi" = 324
        "xxxhdpi" = 432
    }
    foreach ($density in $androidForegrounds.Keys) {
        Save-SquarePng "client/android/res/mipmap-$density/ic_launcher_foreground.png" $androidForegrounds[$density]
    }

    $androidBanners = @{
        "mdpi" = @(160, 90)
        "hdpi" = @(240, 135)
        "xhdpi" = @(320, 180)
    }
    foreach ($density in $androidBanners.Keys) {
        $dimensions = $androidBanners[$density]
        Save-Banner "client/android/res/mipmap-$density/ic_banner.png" $dimensions[0] $dimensions[1]
    }

    foreach ($density in @("ldpi", "mdpi", "hdpi", "xhdpi", "xxhdpi", "xxxhdpi")) {
        Save-Wordmark "client/android/res/drawable-$density/logo.png" 150 22
    }

    foreach ($size in @(20, 29, 40, 50, 57, 58, 60, 72, 76, 80, 87, 100, 114, 120, 144, 152, 167, 180, 1024)) {
        Save-SquarePng "client/ios/app/Media.xcassets/AppIcon.appiconset/$size.png" $size
    }

    $macIconSizes = @{
        "16.png" = 16
        "16@2x.png" = 32
        "32.png" = 32
        "32@2x.png" = 64
        "128.png" = 128
        "128@2x.png" = 256
        "256.png" = 256
        "256@2x.png" = 512
        "512.png" = 512
        "512@2x.png" = 1024
    }
    foreach ($catalog in @("Images.xcassets", "Images-beta.xcassets")) {
        foreach ($name in $macIconSizes.Keys) {
            Save-SquarePng "client/macos/app/$catalog/AppIcon.appiconset/$name" $macIconSizes[$name]
        }
    }

    Save-Ico "client/images/app.ico" @(16, 24, 32, 48, 64, 128, 256)
    Save-Icns "client/images/app.icns"
}
finally {
    $sourceImage.Dispose()
}

Write-Host "Nexa VPN brand assets generated from $sourcePath"
