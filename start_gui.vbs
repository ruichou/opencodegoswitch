Set wsh = CreateObject("WScript.Shell")
pyw = "C:\Users\34632\.workbuddy\binaries\python\envs\default\Scripts\pythonw.exe"
scr = "C:\Users\34632\WorkBuddy\2026-07-14-13-32-12\opencode-go-switch\desktop_app.py"
wsh.Run Chr(34) & pyw & Chr(34) & " " & Chr(34) & scr & Chr(34), 0, False
