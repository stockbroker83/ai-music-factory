"""바탕화면에 AI Music Factory 바로가기 생성"""
import os
import subprocess

desktop = os.path.join(os.path.expanduser("~"), "Desktop")
shortcut_path = os.path.join(desktop, "AI Music Factory.lnk")
target = r"C:\Users\csu\projects\ai-music-factory\start_dashboard.bat"
working_dir = r"C:\Users\csu\projects\ai-music-factory"

# PowerShell로 바로가기 생성
ps_script = f'''
$ws = New-Object -ComObject WScript.Shell
$s = $ws.CreateShortcut("{shortcut_path}")
$s.TargetPath = "{target}"
$s.WorkingDirectory = "{working_dir}"
$s.Description = "AI Music Factory Dashboard"
$s.Save()
'''

subprocess.run(["powershell", "-Command", ps_script], capture_output=True)

if os.path.exists(shortcut_path):
    print(f"바탕화면 바로가기 생성 완료: {shortcut_path}")
else:
    print("바로가기 생성 실패")
