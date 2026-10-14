"""
Windows File Explorer folder picker utility.
Pops open the native OS folder selection dialog and prints the selected folder path to stdout.
"""

import sys
import os

def pick_folder() -> str:
    # Method 1: Python Tkinter with topmost window
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.wm_attributes("-topmost", 1)
        root.focus_force()
        folder = filedialog.askdirectory(title="Select Storage Folder for VYZN Footage and Clips")
        root.destroy()
        if folder:
            return os.path.normpath(folder)
    except Exception:
        pass

    # Method 2: Native Windows Forms FolderBrowserDialog via PowerShell STA
    try:
        import subprocess
        script = (
            "Add-Type -AssemblyName System.Windows.Forms; "
            "$f = New-Object System.Windows.Forms.FolderBrowserDialog; "
            "$f.Description = 'Select Storage Folder for VYZN Footage and Clips'; "
            "$f.ShowNewFolderButton = $true; "
            "if ($f.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) { "
            "  [Console]::WriteLine($f.SelectedPath) "
            "}"
        )
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-STA", "-Command", script],
            capture_output=True,
            text=True,
            timeout=120
        )
        out = proc.stdout.strip()
        if out:
            return os.path.normpath(out)
    except Exception:
        pass

    # Method 3: Shell.Application COM object
    try:
        import subprocess
        script = (
            "$shell = New-Object -ComObject Shell.Application; "
            "$folder = $shell.BrowseForFolder(0, 'Select Storage Folder for VYZN Footage and Clips', 0, 0); "
            "if ($folder) { [Console]::WriteLine($folder.Self.Path) }"
        )
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-STA", "-Command", script],
            capture_output=True,
            text=True,
            timeout=120
        )
        out = proc.stdout.strip()
        if out:
            return os.path.normpath(out)
    except Exception:
        pass

    return ""

if __name__ == "__main__":
    selected = pick_folder()
    if selected:
        print(selected)
