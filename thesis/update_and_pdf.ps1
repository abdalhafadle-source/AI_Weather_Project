# Open the report in Word, fill the table of contents and fields, save, and export a PDF copy.
$doc = (Resolve-Path "$PSScriptRoot\Hilla_PV_AI_Report.docx").Path
$pdf = [IO.Path]::ChangeExtension($doc, ".pdf")
$word = New-Object -ComObject Word.Application
$word.Visible = $false
try {
    $d = $word.Documents.Open($doc)
    foreach ($t in $d.TablesOfContents) { $t.Update() }
    $d.Fields.Update() | Out-Null
    $d.Save()
    $d.ExportAsFixedFormat($pdf, 17)   # 17 = PDF
    "pages: " + $d.ComputeStatistics(2)
    $d.Close()
} finally { $word.Quit() }
"saved $pdf"
