$content = Get-Content 'C:\Users\Administrator\Desktop\Cato\workspace\SOUL.md' -Raw
$body = @{name='SOUL.md'; content=$content} | ConvertTo-Json -Depth 5
$r = Invoke-WebRequest -Uri 'http://localhost:8080/api/workspace/file' -Method PUT -Body $body -ContentType 'application/json'
Write-Host $r.StatusCode $r.Content
