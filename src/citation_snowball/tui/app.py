from textual.app import App
from citation_snowball.tui.screens import DashboardScreen, SnowballingConfigScreen, ExecutionScreen
from textual.widgets import Footer, Header
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

    def on_dashboard_screen_run_download(self, message: DashboardScreen.RunDownload) -> None:
        self.run_command("Downloading PDFs", ["download"])

    def on_dashboard_screen_show_results(self, message: DashboardScreen.ShowResults) -> None:
        self.run_command("Showing Results", ["results"])

    def on_dashboard_screen_run_export(self, message: DashboardScreen.RunExport) -> None:
        self.run_command("Exporting Report", ["export"])

    def on_snowballing_config_screen_run_snowball(self, message) -> None:
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
        try:
            # This is a bit hacky to update UI from thread, but Textual usually handles call_from_thread
            result = subprocess.run(args, capture_output=True, text=True)
            
            output = f"$ {' '.join(args)}\n\n"
            if result.stdout:
                output += f"[STDOUT]\n{result.stdout}\n"
            if result.stderr:
                output += f"[STDERR]\n{result.stderr}\n"
            
            if result.returncode == 0:
                output += "\n\n[SUCCESS] Command completed successfully."
            else:
                output += f"\n\n[FAILED] Command failed with exit code {result.returncode}."
                
            self.call_from_thread(self._update_execution_output, screen, output)
            
        except Exception as e:
            self.call_from_thread(self._update_execution_output, screen, f"Error launching command: {str(e)}")

    def _update_execution_output(self, screen: ExecutionScreen, output: str) -> None:
        screen.query_one("#exec-output").update(output)
        screen.query_one(".exec-status").update("Finished.")

