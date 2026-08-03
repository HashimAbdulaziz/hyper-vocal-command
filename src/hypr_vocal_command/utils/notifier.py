"""Desktop notification feedback via notify-send."""

import subprocess


def notify(title: str, body: str = "", urgency: str = "normal") -> None:
    try:
        subprocess.run(
            ["notify-send", "--app-name=hypr-vocal-command", f"--urgency={urgency}", title, body],
            check=False,
        )
    except OSError:
        pass
