"""A7C II Linux 命令行。启动和 doctor 均不会连接相机。"""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent/"src"))
from desktopapp.linuxcli import main
if __name__ == "__main__":
    raise SystemExit(main())

