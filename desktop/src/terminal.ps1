param([string]$Python,[string]$Project)
$env:PYTHONUTF8='1'
& $Python -X utf8 -m contract_driven_ai_flow terminal --project $Project
