Set fso = CreateObject("Scripting.FileSystemObject")
dir = fso.GetParentFolderName(WScript.ScriptFullName)
Set shell = CreateObject("WScript.Shell")
shell.CurrentDirectory = dir
shell.Run Chr(34) & dir & "\.venv\Scripts\pythonw.exe" & Chr(34) & " main.py", 0, False
