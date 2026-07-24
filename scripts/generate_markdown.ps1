# PowerShell script to generate a Markdown summary from the JSON data
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

# Create Markdown output
$output = @()
$output += "# Sub-repositories Analysis Summary"
$output += ""
$output += "Total repositories: $($repos.Count)"
$output += ""
$output += "## Overview"
$output += ""
$output += "| Repository | Has README | Dependency Files | Purpose Guess |"
output += "|------------|------------|------------------|---------------|"

foreach ($repo in $repos) {
    $depFiles = @()
    if ($repo.has_requirements) { $depFiles += "requirements.txt" }
    if ($repo.has_setup_py) { $depFiles += "setup.py" }
    if ($repo.has_pyproject_toml) { $depFiles += "pyproject.toml" }
    if ($repo.has_package_json) { $depFiles += "package.json" }
    $depString = if ($depFiles.Count -gt 0) { $depFiles -join ", " } else { "None" }
    
    $readmeStatus = if ($repo.has_readme) { "Yes" } else { "No" }
    
    $output += "| $($repo.name) | $readmeStatus | $depString | $($repo.purpose_guess) |"
}

$output += ""
$output += "## Detailed Information"
$output += ""

foreach ($repo in $repos) {
    $output += "### $($repo.name)"
    $output += ""
    $output += "- **Path**: $($repo.path)"
    $output += "- **Has README**: $($repo.has_readme)"
    if ($repo.has_readme -and $repo.readme_preview) {
        $previewLines = $repo.readme_preview -split "`n" | Select-Object -First 5
        $output += "- **README Preview (first 5 lines)**:"
        foreach ($line in $previewLines) {
            $output += "  ```"
            $output += "  $($line)"
            $output += "  ```"
        }
    }
    $output += "- **Dependency files**:"
    $output += "  - requirements.txt: $($repo.has_requirements)"
    $output += "  - setup.py: $($repo.has_setup_py)"
    $output += "  - pyproject.toml: $($repo.has_pyproject_toml)"
    $output += "  - package.json: $($repo.has_package_json)"
    $output += "- **Top-level files**: $($repo.top_level_files -join ', ')"
    $output += "- **Top-level directories**: $($repo.top_level_dirs -join ', ')"
    $output += "- **Purpose guess**: $($repo.purpose_guess)"
    $output += ""
}

# Write to file
$outputPath = "c:\Users\HONOR\Seedvr2\repo_analysis_summary.md"
$output | Out-File -FilePath $outputPath -Encoding UTF8
Write-Host "Markdown summary generated at: $outputPath"