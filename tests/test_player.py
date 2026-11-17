from pathlib import Path
import subprocess


def test_player_startup_and_recovery_regressions():
    subprocess.run(["node", "--test", str(Path(__file__).with_name("test_player.cjs"))], check=True)
