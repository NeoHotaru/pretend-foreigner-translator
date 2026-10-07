' Pretend Foreigner Translator - launch without a console window.
' Keep comments ASCII: wscript reads .vbs as ANSI, non-ASCII turns to garbage.
' If pythonw is not on PATH, replace PYTHONW with its full path.

Option Explicit

Dim fso, sh, here, base, PYTHONW, target
Set fso = CreateObject("Scripting.FileSystemObject")
Set sh  = CreateObject("WScript.Shell")

here = fso.GetParentFolderName(WScript.ScriptFullName)
base = fso.GetParentFolderName(here)
target = base & "\src\translate_app.py"

If Not fso.FileExists(target) Then
    MsgBox "Cannot find " & target & vbCrLf & vbCrLf & _
           "This launcher must sit in the project's run\ folder.", 16, _
           "Pretend Foreigner Translator"
    WScript.Quit 1
End If

PYTHONW = "pythonw.exe"

sh.CurrentDirectory = base & "\src"
sh.Run """" & PYTHONW & """ """ & target & """", 0, False