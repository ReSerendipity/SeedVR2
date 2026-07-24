# PowerShell script to explore all sub-repositories under repo/
$baseDir = "c:\Users\HONOR\Seedvr2\repo"
$results = @()

foreach ($repo in Get-ChildItem -Directory -Path $baseDir) {
    $repoName = $repo.Name
    $repoPath = $repo.FullName
    
    # Initialize result object
    $repoInfo = [ordered]@{
        name = $repoName
        path = $repoPath
        has_readme = $false
        readme_preview = $null
        has_requirements = $false
        has_setup_py = $false
        has_pyproject_toml = $false
        has_package_json = $false
        top_level_files = @()
        top_level_dirs = @()
        purpose_guess = $null
    }
    
    # Get top-level items
    $items = Get-ChildItem -Path $repoPath -Force
    $files = @()
    $dirs = @()
    foreach ($item in $items) {
        if ($item.PSIsContainer) {
            $dirs += $item.Name
        } else {
            $files += $item.Name
        }
    }
    $repoInfo.top_level_files = $files
    $repoInfo.top_level_dirs = $dirs
    
    # Check for README.md
    $readmePath = Join-Path $repoPath "README.md"
    if (Test-Path $readmePath) {
        $repoInfo.has_readme = $true
        # Read first 50 lines
        $lines = Get-Content -Path $readmePath -TotalCount 50
        $repoInfo.readme_preview = $lines -join "`n"
    }
    
    # Check for dependency files
    if (Test-Path (Join-Path $repoPath "requirements.txt")) {
        $repoInfo.has_requirements = $true
    }
    if (Test-Path (Join-Path $repoPath "setup.py")) {
        $repoInfo.has_setup_py = $true
    }
    if (Test-Path (Join-Path $repoPath "pyproject.toml")) {
        $repoInfo.has_pyproject_toml = $true
    }
    if (Test-Path (Join-Path $repoPath "package.json")) {
        $repoInfo.has_package_json = $true
    }
    
    # Guess purpose based on name and files
    $purpose = "Unknown"
    $nameLower = $repoName.ToLower()
    if ($nameLower -match "sr|upscale|enhance|super.?resolution") {
        $purpose = "Super-resolution / Upscaling"
    } elseif ($nameLower -match "video") {
        $purpose = "Video processing"
    } elseif ($nameLower -match "diffusion|diff|stable") {
        $purpose = "Diffusion-based model"
    } elseif ($nameLower -match "gan|style|paint") {
        $purpose = "GAN-based style transfer / painting"
    } elseif ($nameLower -match "face|restore|codeformer") {
        $purpose = "Face restoration"
    } elseif ($nameLower -match "old|deoldify|color") {
        $purpose = "Colorization / Restoration"
    } elseif ($nameLower -match "comfy|ui|extension") {
        $purpose = "UI extension / Plugin"
    } elseif ($nameLower -match "train|dataset") {
        $purpose = "Training framework"
    }
    $repoInfo.purpose_guess = $purpose
    
    # Add to results
    $results += $repoInfo
}

# Output as JSON
$results | ConvertTo-Json -Depth 5