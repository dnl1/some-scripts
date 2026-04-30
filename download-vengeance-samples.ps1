$BASE_URL = "https://files.lyberry.com/audio/sounds/Vengeance%20Samples/"
$DOWNLOAD_PATH = "C:/Vengeance Samples/"

# Clean folder and file names
function Clean-Name {
    param([string]$name)
    
    $name = [System.Uri]::UnescapeDataString($name)
    $name = $name -replace '%20', ' '  # Replace %20 with space
    $name = $name -replace '[\\/:*?"<>|]', '_'  # Remove illegal filename characters
    return $name.Trim()
}

# Download a file
function Download-File {
    param([string]$url, [string]$path)
    
    $fileName = Clean-Name ([System.IO.Path]::GetFileName($url))
    $fullPath = Join-Path $path $fileName

    if (-not (Test-Path $path)) {
        New-Item -ItemType Directory -Path $path -Force | Out-Null
    }

    if (Test-Path $fullPath) {
        Write-Host "[Already exists] $fullPath" -ForegroundColor Yellow
        return
    }

    Write-Host "[Downloading] $fullPath" -ForegroundColor Green
    try {
        $response = Invoke-WebRequest -Uri $url -TimeoutSec 60
        $fileBytes = $response.Content
        [System.IO.File]::WriteAllBytes($fullPath, $fileBytes)
    }
    catch {
        Write-Host "[Failed] $url - $($_.Exception.Message)" -ForegroundColor Red
    }
}

# Crawl the folder
function Crawl-Folder {
    param([string]$url, [string]$path)
    
    Write-Host "[Crawling] $url" -ForegroundColor Cyan
    
    try {
        $response = Invoke-WebRequest -Uri $url -TimeoutSec 60
    }
    catch {
        Write-Host "[Error accessing] $url - $($_.Exception.Message)" -ForegroundColor Red
        return
    }

    # Parse HTML links
    $links = $response.Links | Where-Object { 
        $href = $_.href 
        $href -and 
        -not $href.StartsWith('?') -and 
        -not $href.StartsWith('/') -and 
        -not $href.Contains('../')
    }

    foreach ($link in $links) {
        $href = $link.href
        $fullUrl = [System.Uri]::new([System.Uri]$url, $href).AbsoluteUri

        if ($href.EndsWith('/')) {
            $folderName = Clean-Name ($href.TrimEnd('/'))
            $newPath = Join-Path $path $folderName
            Crawl-Folder -url $fullUrl -path $newPath
        }
        else {
            Download-File -url $fullUrl -path $path
        }
    }
}

# Main execution
Crawl-Folder -url $BASE_URL -path $DOWNLOAD_PATH