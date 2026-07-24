# PowerShell script to parse the JSON output and generate a structured summary
$filePath = "C:\Users\HONOR\.qoder-cn\cache\projects\Seedvr2-b7768a41\agent-tools\task-77e\045359aa.txt"
$jsonContent = Get-Content -Path $filePath -Raw
# The output includes a leading line with the command, we need to skip it
# Find the first line that starts with '['
$lines = $jsonContent -split "`n"
$jsonStart = 0
for ($i = 0; $i -lt $lines.Count; $i++) {
    if ($lines[$i].Trim() -eq '[') {
        $jsonStart = $i
        break
    }
}
$jsonString = $lines[$jsonStart..($lines.Count-1)] -join "`n"
# Parse JSON
try {
    $repos = $jsonString | ConvertFrom-Json
} catch {
    Write-Error "Failed to parse JSON: $_"
    exit 1
}

# Generate summary for each repo
foreach ($repo in $repos) {
    Write-Host "=== $($repo.name) ==="
    Write-Host "Path: $($repo.path)"
    Write-Host "Has README: $($repo.has_readme)"
    if ($repo.has_readme -and $repo.readme_preview) {
        $previewLines = $repo.readme_preview -split "`n" | Select-Object -First 10
        Write-Host "README preview (first 10 lines):"
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
    Write-Host ""
}