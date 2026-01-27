from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Grid, Horizontal, Vertical, Container
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Input, Label, Static, Switch, RichLog
from textual.message import Message


class RunDownload(Message): ...
class ShowResults(Message): ...
class RunExport(Message): ...
class RunSnowball(Message): ...


class DashboardScreen(Screen):
    """Main dashboard screen."""

    BINDINGS = [
        ("q", "quit", "Quit"),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Container(
            Vertical(
                Label("Project Directory:", classes="field-label"),
                Input(value=".", placeholder="Enter directory path", id="input-dir"),
                
                Grid(
                    Button("▶️ Snowballing", id="btn-run", variant="primary"),
                    Button("⬇️ Download PDFs", id="btn-download", variant="primary"),
                    Button("📊 Show Results", id="btn-results"),
                    Button("📄 Export Report", id="btn-export"),
                    Button("❌ Quit", id="btn-quit", variant="error"),
                    id="dashboard-grid",
                ),
                classes="dashboard-content"
            ),
            id="dashboard-container"
        )
        yield Footer()

    def on_mount(self) -> None:
        """Load directory from app config."""
        self.query_one("#input-dir", Input).value = self.app.config_dir

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id
        
        # Save directory before any action
        directory = self.query_one("#input-dir", Input).value.strip()
        self.app.config_dir = directory if directory else "."
        
        if button_id == "btn-quit":
            self.app.exit()
        elif button_id == "btn-run":
            self.app.push_screen(SnowballingConfigScreen())
        elif button_id == "btn-download":
            self.app.post_message(RunDownload())
        elif button_id == "btn-results":
            self.app.post_message(ShowResults())
        elif button_id == "btn-export":
            self.app.post_message(RunExport())


class SnowballingConfigScreen(Screen):
    """Snowballing configuration screen."""

    BINDINGS = [("escape", "app.pop_screen", "Back")]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Container(
            Vertical(
                Label("Keywords (comma separated):", classes="field-label"),
                Input(placeholder="TMS, tDCS, neuromodulation, ...", id="input-keywords"),
                
                Label("Max Iterations:", classes="field-label"),
                Input(value="3", placeholder="3", id="input-max-iter"),
                
                Horizontal(
                    Label("Resume:"),
                    Switch(id="switch-resume", value=True),
                    classes="switch-row"
                ),
                
                Horizontal(
                    Button("▶️ Start", variant="success", id="btn-start"),
                    Button("⬅️ Back", variant="default", id="btn-back"),
                    classes="button-row"
                ),
                classes="config-content"
            ),
            id="config-container"
        )
        yield Footer()

    def on_mount(self) -> None:
        """Load current values from App when screen mounts."""
        self.query_one("#input-keywords", Input).value = ", ".join(self.app.config_keywords)
        self.query_one("#input-max-iter", Input).value = str(self.app.config_max_iterations)
        # Set switch value after a small delay to ensure it's rendered
        switch = self.query_one("#switch-resume", Switch)
        switch.value = self.app.config_resume

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-start":
            # Save settings
            keywords_str = self.query_one("#input-keywords", Input).value
            max_iter_str = self.query_one("#input-max-iter", Input).value.strip()
            resume = self.query_one("#switch-resume", Switch).value
            
            # Parse keywords
            keywords = [k.strip() for k in keywords_str.split(",") if k.strip()]
            
            # Parse max iterations
            try:
                max_iterations = int(max_iter_str) if max_iter_str else 2
            except ValueError:
                max_iterations = 2
                self.app.notify("Invalid max iterations, using default: 2", severity="warning")
            
            self.app.config_keywords = keywords
            self.app.config_max_iterations = max_iterations
            self.app.config_resume = resume
            
            # Trigger snowballing
            self.app.pop_screen()
            self.app.post_message(RunSnowball())
            
        elif event.button.id == "btn-back":
            self.app.pop_screen()


class ExecutionScreen(Screen):
    """Screen to show command execution output."""
    
    BINDINGS = [("escape", "app.pop_screen", "Back")]
    
    def __init__(self, title: str, command: str, args: list[str]):
        super().__init__()
        self.page_title = title
        self.command = command
        self.args = args

    def compose(self) -> ComposeResult:
        yield Header()
        yield Vertical(
            Label(f"Executing: {self.page_title}", classes="exec-title"),
            Label("Running command...", classes="exec-status", id="exec-status"),
            RichLog(id="exec-output", classes="exec-output", highlight=True, markup=True, auto_scroll=True),
            Button("⬅️ Back to Dashboard", id="btn-back", variant="primary"),
            id="exec-container"
        )
        yield Footer()
        
    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-back":
            self.app.pop_screen()

    def write_log(self, content: str) -> None:
        """Write content to the log widget."""
        log = self.query_one("#exec-output", RichLog)
        log.write(content)


