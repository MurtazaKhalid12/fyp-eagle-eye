$ErrorActionPreference = 'Stop'
$root      = 'C:\fyp-eagle-eye\docs'
$inHtml    = Join-Path $root 'poster_brief_pack.html'
$embedHtml = Join-Path $root 'poster_brief_pack.embedded.html'
$outPdf    = Join-Path $root 'EagleEye_Poster_Brief_Pack.pdf'

$html = Get-Content -LiteralPath $inHtml -Raw -Encoding UTF8

# Replace every local <img src="..."> with a base64 data URI so the PDF is self-contained.
$evaluator = [System.Text.RegularExpressions.MatchEvaluator]{
  param($m)
  $rel = $m.Groups['p'].Value
  if ($rel -match '^(https?:|data:)') { return $m.Value }
  $full = Join-Path $root $rel
  if (-not (Test-Path -LiteralPath $full)) { return $m.Value }
  $bytes = [IO.File]::ReadAllBytes($full)
  $b64   = [Convert]::ToBase64String($bytes)
  $ext   = ([IO.Path]::GetExtension($full)).TrimStart('.').ToLower()
  if ($ext -eq 'jpg') { $ext = 'jpeg' }
  return ('src="data:image/' + $ext + ';base64,' + $b64 + '"')
}
$pattern = 'src="(?<p>[^"]+\.(?:png|jpg|jpeg))"'
$html2 = [regex]::Replace($html, $pattern, $evaluator)

$utf8 = New-Object System.Text.UTF8Encoding($false)
[IO.File]::WriteAllText($embedHtml, $html2, $utf8)
('embedded HTML: ' + [math]::Round((Get-Item $embedHtml).Length/1kb,1) + ' KB')

$edge = 'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'
$url  = 'file:///' + ($embedHtml -replace '\\','/')
if (Test-Path -LiteralPath $outPdf) { Remove-Item -LiteralPath $outPdf -Force }

& $edge --headless=new --disable-gpu --no-sandbox --no-pdf-header-footer --print-to-pdf-no-header `
        --run-all-compositor-stages-before-draw --virtual-time-budget=10000 `
        ("--print-to-pdf=" + $outPdf) $url | Out-Null
Start-Sleep -Seconds 1

if (-not (Test-Path -LiteralPath $outPdf)) {
  'retry with --headless (legacy)...'
  & $edge --headless --disable-gpu --no-sandbox --no-pdf-header-footer `
          ("--print-to-pdf=" + $outPdf) $url | Out-Null
  Start-Sleep -Seconds 1
}

if (Test-Path -LiteralPath $outPdf) {
  'OK -> ' + $outPdf + ' (' + [math]::Round((Get-Item $outPdf).Length/1kb,1) + ' KB)'
} else {
  'ERROR: PDF not created'
}
