$ErrorActionPreference = 'Stop'
$pptx = 'C:\fyp-eagle-eye\docs\EagleEye_Poster_A1.pptx'
$pdf  = 'C:\fyp-eagle-eye\docs\EagleEye_Poster_A1.pdf'
$png  = 'C:\fyp-eagle-eye\docs\_poster_preview.png'
foreach ($f in @($pdf,$png)) { if (Test-Path $f) { Remove-Item $f -Force } }

$pp = New-Object -ComObject PowerPoint.Application
try {
  $pres = $pp.Presentations.Open($pptx, $true, $false, $false)   # ReadOnly, Untitled, WithWindow=false
  $pres.SaveAs($pdf, 32)                                         # 32 = ppSaveAsPDF
  $pres.Slides.Item(1).Export($png, 'PNG', 2382, 3368)          # ~A1 ratio preview (hi-res)
  $pres.Close()
  'OK: ' + $pdf + ' (' + [math]::Round((Get-Item $pdf).Length/1kb,1) + ' KB), preview ' + $png
} finally {
  $pp.Quit()
  [System.Runtime.Interopservices.Marshal]::ReleaseComObject($pp) | Out-Null
}
