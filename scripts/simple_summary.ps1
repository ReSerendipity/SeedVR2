# Simple summary script
$filePath = "C:\Users\HONOR\.qoder-cn\cache\projects\Seedvr2-b7768a41\agent-tools\task-77e\045359aa.txt"
$jsonContent = Get-Content -Path $filePath -Raw
$lines = $jsonContent -split "`n"
$jsonStart = 0
for ($i = 0; $i -lt $lines.Count; $i++) {
    if ($lines[$i].Trim() -eq '[') {
        $jsonStart = $i
        break
    }
}
$jsonString = $lines[$jsonStart..($lines.Count-1)] -join "`n"
$repos = $jsonString | ConvertFrom-Json

Write-Host "=== REPOSITORIES SUMMARY ==="
Write-Host ""
Write-Host "Total repositories: $($repos.Count)"
Write-Host ""
Write-Host "OVERVIEW TABLE:"
Write-Host "---------------"
Write-Host ("{0,-35} {1,-10} {2,-50} {3,-30}" -f "Repository", "README", "Dependency Files", "Purpose")
Write-Host ("{0,-35} {1,-10} {2,-50} {3,-30}" -f "----------", "------", "----------------", "-------")

foreach ($repo in $repos) {
    $depFiles = @()
    if ($repo.has_requirements) { $depFiles += "requirements.txt" }
    if ($repo.has_setup_py) { $depFiles += "setup.py" }
    if ($repo.has_pyproject_toml) { $depFiles += "pyproject.toml" }
    if ($repo.has_package_json) { $depFiles += "package.json" }
    $depString = if ($depFiles.Count -gt 0) { $depFiles -join ", " } else { "None" }
    
    $readmeStatus = if ($repo.has_readme) { "Yes" } else { "No" }
    
    Write-Host ("{0,-35} {1,-10} {2,-50} {3,-30}" -f $repo.name, $readmeStatus, $depString, $repo.purpose_guess)
}

Write-Host ""
Write-Host "DETAILED INFORMATION:"
Write-Host "---------------------"

foreach ($repo in $repos) {
    Write-Host ""
    Write-Host "=== $($repo.name) ==="
    Write-Host "Path: $($repo.path)"
    Write-Host "Has README: $($repo.has_readme)"
    if ($repo.has_readme -and $repo.readme_preview) {
        $previewLines = $repo.readme_preview -split "`n" | Select-Object -First 3
        Write-Host "README preview (first 3 lines):"
        foreach ($line in $previewLines) {
            Write-Host "  $line"
        }
    }
    Write-Host "Dependency files:"
    Write-Host "  requirements.txt: $($repo.has_requirements)"
    Write-Host "  setup.py: $($repo.has_setup_py)"
    Write-Host "  pyproject.toml: $($repo.has_pyproject_toml)"
    Write-Host "  package.json: $($repo.has_package_json)"
    Write-Host "Top-level files: $($repo.top_level_files -join ', ')"
    Write-Host "Top-level directories: $($repo.top_level_dirs -join ', ')"
    Write-Host "Purpose guess: $($repo.purpose_guess)"
}