from textual.app import App
from citation_snowball.tui.screens import (
    DashboardScreen, 
    SnowballingConfigScreen, 
    ExecutionScreen,
    RunDownload,
    ShowResults,
    RunExport,
    RunSnowball
)
from textual.widgets import Footer, Header, Label
import os
import subprocess
import threading
import time

class SnowballApp(App):
    """Citation Snowball TUI Application."""

    CSS_PATH = "tui.css"
    
    BINDINGS = [
        ("q", "quit", "Quit"),
        ("d", "toggle_dark", "Toggle dark mode"),
    ]

    def __init__(self):
        super().__init__()
        # Default config
        self.config_dir = "."
        self.config_keywords = []
        self.config_max_iterations = 3
        self.config_resume = True

    def on_mount(self) -> None:
        self.push_screen(DashboardScreen())

    def on_run_download(self, message: RunDownload) -> None:
        self.run_command("Downloading PDFs", ["download"])

    def on_show_results(self, message: ShowResults) -> None:
        self.run_command("Showing Results", ["results"])

    def on_run_export(self, message: RunExport) -> None:
        self.run_command("Exporting Report", ["export"])

    def on_run_snowball(self, message: RunSnowball) -> None:
        self.run_command("Snowballing", ["run", "--max-iterations", "2"])

    def run_command(self, title: str, args: list[str]) -> None:
        """Run a snowball command in the execution screen."""
        
        full_args = ["uv", "run", "snowball"] + args
        
        # Add directory argument for relevant commands
        if args[0] in ["run", "download", "results", "export"]:
            if self.config_dir and self.config_dir != ".":
                full_args.append(self.config_dir)
            else:
                full_args.append(".")

        # Add keywords for run command
        if args[0] == "run" and self.config_keywords:
            for k in self.config_keywords:
                full_args.extend(["-k", k])
            
            # Add max iterations
            full_args.extend(["--max-iterations", str(self.config_max_iterations)])
            
            # Add resume flag if enabled
            if self.config_resume:
                full_args.append("-r")

        # Create and push execution screen
        screen = ExecutionScreen(title, " ".join(full_args), full_args)
        self.push_screen(screen)
        
        # Start execution in thread
        threading.Thread(target=self._execute_in_background, args=(screen, full_args), daemon=True).start()

    def _execute_in_background(self, screen: ExecutionScreen, args: list[str]) -> None:
        """Execute command in background thread and update screen."""
        import re
        
        # Pattern to strip ANSI escape codes
        ansi_pattern = re.compile(r'\x1b\[[0-9;]*[a-zA-Z]|\x1b\[\?[0-9]*[a-zA-Z]')
        
        def strip_ansi(text: str) -> str:
            return ansi_pattern.sub('', text)
        
        try:
            # Disable Rich colors and fancy output for subprocess
            env = os.environ.copy()
            env["NO_COLOR"] = "1"  # Standard way to disable colors
            env["TERM"] = "dumb"   # Tell Rich it's not a real terminal
            env["PYTHONUNBUFFERED"] = "1"
            
            # Start process
            cmd = " ".join(args)
            self.call_from_thread(screen.write_log, f"[dim]$ {cmd}[/dim]\n")
            
            process = subprocess.Popen(
                args,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=0,  # Unbuffered
                env=env
            )
            
            self.call_from_thread(screen.write_log, "[dim]Process started...[/dim]\n")

            # Read character-by-character
            buffer = ""
            if process.stdout:
                while True:
                    char = process.stdout.read(1)
                    if not char:
                        break
                    buffer += char
                    # Flush buffer on newline OR carriage return
                    if char in ('\n', '\r'):
                        line = strip_ansi(buffer.rstrip())
                        if line and not line.startswith(' Snowballing'):  # Filter progress spam
                            self.call_from_thread(screen.write_log, line)
                        buffer = ""
                
                # Flush any remaining content
                remaining = strip_ansi(buffer.strip())
                if remaining:
                    self.call_from_thread(screen.write_log, remaining)
            
            return_code = process.wait()
            
            if return_code == 0:
                self.call_from_thread(screen.write_log, "\n[green][SUCCESS] Command completed.[/green]")
            else:
                self.call_from_thread(screen.write_log, f"\n[red][FAILED] Exit code {return_code}.[/red]")
                
            self.call_from_thread(self._update_execution_status, screen, "Finished.")
            
        except Exception as e:
            self.call_from_thread(screen.write_log, f"\n[red]Error: {str(e)}[/red]")
            self.call_from_thread(self._update_execution_status, screen, "Error.")

    def _update_execution_status(self, screen: ExecutionScreen, status: str) -> None:
        screen.query_one("#exec-status", Label).update(status)

