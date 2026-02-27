#Requires AutoHotkey v2.0
#SingleInstance Force

base := "C:\MRSEC\openclaw-node\"
stop := base . "STOP_NODE.bat"
toggle := base . "TOGGLE_NODE.bat"
status := base . "STATUS_NODE.bat"

^!+F12:: Run(stop)
^!+F11:: Run(toggle)
^!+F10:: Run(status)
